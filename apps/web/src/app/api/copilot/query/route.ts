import { NextRequest, NextResponse } from "next/server";
import { getSession } from "@/lib/db";
import { intelligenceFetch } from "@/lib/intelligence";

/**
 * POST /api/copilot/query
 *
 * Proxies queries to the Intelligence Service's RAG pipeline.
 * Returns prepared chunks + graph context ready for LLM consumption.
 *
 * When a paid LLM is configured (LLM_PROVIDER env var), this endpoint
 * can optionally forward the prepared context to the LLM and return
 * the generated answer alongside the chunks.
 */

interface PreparedChunk {
  text: string;
  source_type: string;
  relevance_score: number;
  document_id: string;
  metadata: Record<string, unknown>;
  token_estimate: number;
  entities_in_chunk: Array<{
    type: string;
    value: string;
    normalized_value: string;
    confidence: number;
  }>;
  graph_context: Array<Record<string, unknown>>;
}

interface PreparedContextResponse {
  query: string;
  chunks: PreparedChunk[];
  graph_context: Array<Record<string, unknown>>;
  system_prompt: string;
  formatted_prompt: string;
  total_token_estimate: number;
  entities_found: Array<{
    entity_type: string;
    value: string;
    normalized_value: string;
    confidence: number;
  }>;
  retrieval_metadata: Record<string, unknown>;
}

export async function POST(request: NextRequest) {
  try {
    const session = await getSession();
    if (!session) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    const { tenantId } = session;

    const body = await request.json();
    const { query, filters } = body;

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return NextResponse.json({ error: "Query is required" }, { status: 400 });
    }

    // Forward to Intelligence Service (chunk preparation mode)
    const response = await intelligenceFetch("/query/prepare", tenantId, {
      query: query.trim(),
      filters: filters || {},
    });

    if (!response.ok) {
      const error = await response.text();
      console.error("Intelligence service error:", error);
      return NextResponse.json({ error: "Failed to prepare query context" }, { status: 502 });
    }

    const prepared: PreparedContextResponse = await response.json();

    // TODO: Save message to conversations table

    // Build response with chunks + context
    // The frontend or a future LLM integration layer will use these
    // chunks + formatted_prompt to call a paid LLM
    const sources = prepared.chunks.map((chunk, idx) => ({
      index: idx + 1,
      document_id: chunk.document_id,
      source_type: chunk.source_type,
      relevance_score: chunk.relevance_score,
      excerpt: chunk.text.substring(0, 300),
      entities: chunk.entities_in_chunk,
      title: (chunk.metadata as Record<string, string>)?.title || "",
    }));

    return NextResponse.json({
      // Prepared context for LLM
      formatted_prompt: prepared.formatted_prompt,
      system_prompt: prepared.system_prompt,
      total_token_estimate: prepared.total_token_estimate,

      // Structured chunks for display/processing
      chunks: prepared.chunks,
      sources,

      // Graph context
      graph_context: prepared.graph_context,
      entities_found: prepared.entities_found,

      // Retrieval performance metrics
      retrieval_metadata: prepared.retrieval_metadata,

      // Confidence from retrieval (not LLM)
      confidence_score: (prepared.retrieval_metadata?.confidence_score as number) || 0,

      // Placeholder — will be filled when paid LLM is integrated
      answer: null,
      model_used: null,
      latency_ms: prepared.retrieval_metadata?.retrieval_latency_ms || 0,
    });
  } catch (error) {
    console.error("Copilot query failed:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
