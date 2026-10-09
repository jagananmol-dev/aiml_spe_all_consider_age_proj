import { NextRequest, NextResponse } from "next/server";
import { getSession, withTenant } from "@/lib/db";
import { intelligenceFetch } from "@/lib/intelligence";
import { getLlmConfig, LlmError, streamChat } from "@/lib/llm";
import {
  buildCatalogChunk,
  buildSmallTalkMessages,
  buildMessages,
  isOverviewQuestion,
  isSmallTalk,
  MAX_HISTORY_TURNS,
  noResultsAnswer,
  numberSources,
  retrievalQuery,
  type CatalogDocument,
  type HistoryTurn,
} from "@/lib/chatPrompt";

/**
 * POST /api/chat
 *
 * The company chatbot. For one question:
 * 1. Retrieves the most relevant passages from this company's uploaded data
 *    (intelligence service /query/prepare, scoped to the session tenant)
 * 2. Sends them, with a short history, to the configured LLM
 * 3. Streams the answer back as newline-delimited JSON events:
 *      {"type":"sources","sources":[...]}   — first, the passages used
 *      {"type":"token","text":"..."}        — answer fragments
 *      {"type":"done"} | {"type":"error","message":"..."}
 */

const MAX_QUESTION_CHARS = 4000;

interface PreparedChunk {
  text: string;
  document_id: string;
  relevance_score: number;
  metadata?: Record<string, unknown>;
}

function parseHistory(value: unknown): HistoryTurn[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (turn): turn is HistoryTurn =>
        !!turn &&
        (turn.role === "user" || turn.role === "assistant") &&
        typeof turn.content === "string" &&
        turn.content.trim().length > 0
    )
    .slice(-MAX_HISTORY_TURNS);
}

export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  let body: { message?: unknown; history?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const question = typeof body.message === "string" ? body.message.trim() : "";
  if (!question) {
    return NextResponse.json({ error: "Message is required" }, { status: 400 });
  }
  if (question.length > MAX_QUESTION_CHARS) {
    return NextResponse.json(
      { error: `Message is too long (max ${MAX_QUESTION_CHARS} characters)` },
      { status: 400 }
    );
  }

  let llm;
  try {
    llm = getLlmConfig();
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
  if (!llm) {
    return NextResponse.json(
      { error: "The chatbot is not configured. Set LLM_PROVIDER and LLM_MODEL." },
      { status: 503 }
    );
  }

  const { tenantId } = session;

  // The company name (for the system prompt) and the search run in parallel
  const startedAt = Date.now();
  const companyNameLookup = withTenant(
    tenantId,
    (sql) => sql`SELECT name FROM tenants WHERE id = ${tenantId} LIMIT 1`
  )
    .then((rows) => (rows[0]?.name as string) || session.tenantSlug)
    .catch((error) => {
      console.warn("[chat] Could not load company name:", error);
      return session.tenantSlug;
    });

  const history = parseHistory(body.history);

  // A greeting needs no search: answer straight from the model, briefly
  if (isSmallTalk(question)) {
    const name = await companyNameLookup;
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (event: Record<string, unknown>) =>
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        send({ type: "sources", sources: [] });
        try {
          for await (const text of streamChat(buildSmallTalkMessages(name, question, history), llm, request.signal)) {
            send({ type: "token", text });
          }
          send({ type: "done" });
        } catch (error) {
          if (!request.signal.aborted) {
            console.error("[chat] LLM failed:", error);
            send({
              type: "error",
              message: error instanceof LlmError ? error.message : "The language model failed to answer. Please try again.",
            });
          }
        } finally {
          try {
            controller.close();
          } catch {
            // already closed by an aborted client
          }
        }
      },
    });
    return new Response(stream, {
      headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store", "X-Accel-Buffering": "no" },
    });
  }
  const overview = isOverviewQuestion(question);

  const loadCatalog = (): Promise<CatalogDocument[]> =>
    withTenant(
      tenantId,
      (sql) => sql`
        SELECT title, document_type, to_char(created_at, 'YYYY-MM-DD') AS uploaded_at
        FROM documents
        WHERE tenant_id = ${tenantId} AND status = 'indexed'
        ORDER BY created_at
      `
    )
      .then((rows) =>
        rows.map((r) => ({
          title: String(r.title),
          documentType: String(r.document_type ?? "Document"),
          uploadedAt: String(r.uploaded_at),
        }))
      )
      .catch((error) => {
        console.warn("[chat] Could not load the document catalog:", error);
        return [];
      });

  // Questions about the whole collection get the document catalog, loaded at
  // the same time as the search
  const overviewCatalog = overview ? loadCatalog() : null;

  // Retrieve this company's most relevant passages
  let chunks: PreparedChunk[];
  let retrieval: Record<string, unknown> = {};
  try {
    const response = await intelligenceFetch("/query/prepare", tenantId, {
      query: retrievalQuery(question, history),
    });
    if (!response.ok) {
      console.error("[chat] Retrieval failed:", response.status, await response.text());
      return NextResponse.json(
        { error: "Could not search your company's data right now." },
        { status: 502 }
      );
    }
    const prepared = await response.json();
    chunks = prepared.chunks ?? [];
    retrieval = prepared.retrieval_metadata ?? {};
  } catch (error) {
    console.error("[chat] Intelligence service unreachable:", error);
    return NextResponse.json(
      { error: "The search service is not running. Start it and try again." },
      { status: 503 }
    );
  }
  const companyName = await companyNameLookup;
  // Nothing cleared the similarity cut-off: the search returned its closest
  // passages instead. The model still answers, with the catalog to point at
  // what the company's documents do cover.
  const weakMatch = retrieval.low_confidence === true;
  const catalog = await (overviewCatalog ?? (weakMatch ? loadCatalog() : Promise.resolve([])));
  // The catalog plus a few passages: enough context, and a small prompt keeps
  // the answer fast
  if (catalog.length > 0) chunks = [buildCatalogChunk(companyName, catalog), ...chunks.slice(0, 4)];
  const contextMs = Date.now() - startedAt;

  const sources = numberSources(chunks);
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: Record<string, unknown>) =>
        controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));

      // How the answer's context was gathered, for the "context" line in the UI
      send({
        type: "context",
        documentsSearched: retrieval.documents_searched ?? null,
        passagesSearched: retrieval.chunks_searched ?? null,
        passagesUsed: sources.length,
        documentsUsed: new Set(sources.map((s) => s.documentId)).size,
        retrievalMs: retrieval.retrieval_latency_ms ?? null,
        weakMatch,
        contextMs,
      });
      send({
        type: "sources",
        sources: sources.map((s) => ({
          index: s.index,
          documentId: s.documentId,
          title: s.title,
          excerpt: s.text.length > 400 ? `${s.text.slice(0, 400)}…` : s.text,
          score: s.score,
        })),
      });

      // Nothing relevant: answer directly instead of letting the model guess
      if (sources.length === 0) {
        send({ type: "token", text: noResultsAnswer(companyName) });
        send({ type: "done" });
        controller.close();
        return;
      }

      try {
        const messages = buildMessages(companyName, question, sources, history, { overview, weakMatch });
        for await (const text of streamChat(messages, llm, request.signal)) {
          send({ type: "token", text });
        }
        send({ type: "done" });
      } catch (error) {
        if (!request.signal.aborted) {
          console.error("[chat] LLM failed:", error);
          send({
            type: "error",
            message:
              error instanceof LlmError
                ? error.message
                : "The language model failed to answer. Please try again.",
          });
        }
      } finally {
        try {
          controller.close();
        } catch {
          // already closed by an aborted client
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    },
  });
}
