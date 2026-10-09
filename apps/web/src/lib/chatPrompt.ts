import type { ChatMessage } from "@/lib/llm";

/**
 * VEDA AI — Chat prompt construction
 *
 * Builds the messages sent to the LLM for one chatbot turn: a domain-neutral
 * system prompt naming the company, a short recent history, and the
 * retrieved context with numbered sources the model must cite.
 */

export interface RetrievedSource {
  index: number;
  documentId: string;
  title: string;
  text: string;
  score: number;
}

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export const MAX_HISTORY_TURNS = 6;
const MAX_HISTORY_CHARS = 2000;

export function buildSystemPrompt(companyName: string): string {
  return `You are the AI assistant for ${companyName}. You answer questions for ${companyName}'s staff using ONLY the numbered context passages taken from ${companyName}'s own uploaded documents and data.

Rules:
1. Use only the context. If it does not contain the answer, say you couldn't find it in ${companyName}'s documents. Never invent facts, numbers, names, or dates.
2. Cite the passages you used with their numbers in square brackets, like [1] or [2][3], right after the statement they support.
3. Copy figures, units, names, and identifiers exactly as written in the context.
4. If passages disagree, say so and cite each.
5. When the question is about what is allowed, how much, who approves, or what to do, find ${companyName}'s policy in the context, apply its rules to the situation asked about, and name the policy you used. If no policy in the context covers it, say so.
6. Be concise and clear. Use bullet points or a short table when it helps.
7. For medical, legal, or financial matters, end with one short line noting the answer comes from ${companyName}'s documents and should be confirmed by a qualified person.
8. Do not add a list of references at the end: the sources are shown to the user separately.
9. If the message is a greeting, thanks, or small talk rather than a question, reply in one or two friendly sentences and offer to help with ${companyName}'s documents; no citations are needed.
10. Reply in the same language as the question.`;
}

/** Number and deduplicate retrieved chunks for citation. */
export function numberSources(
  chunks: {
    text: string;
    document_id: string;
    relevance_score: number;
    metadata?: Record<string, unknown>;
  }[]
): RetrievedSource[] {
  const seen = new Set<string>();
  const sources: RetrievedSource[] = [];
  for (const chunk of chunks) {
    const text = chunk.text?.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    const title = typeof chunk.metadata?.title === "string" ? chunk.metadata.title : "";
    sources.push({
      index: sources.length + 1,
      documentId: chunk.document_id,
      title: title || "Untitled document",
      text,
      score: chunk.relevance_score,
    });
  }
  return sources;
}

export function buildMessages(
  companyName: string,
  question: string,
  sources: RetrievedSource[],
  history: HistoryTurn[] = [],
  options: { overview?: boolean; weakMatch?: boolean } = {}
): ChatMessage[] {
  // Most relevant passage last, right before the question: small models
  // weigh text near the question most. Numbering still follows relevance.
  const context = [...sources]
    .reverse()
    .map((s) => `[${s.index}] Source: ${s.title}\n${s.text}`)
    .join("\n\n---\n\n");

  const recent = history.slice(-MAX_HISTORY_TURNS).map((turn) => ({
    role: turn.role,
    content:
      turn.content.length > MAX_HISTORY_CHARS
        ? `${turn.content.slice(0, MAX_HISTORY_CHARS)}…`
        : turn.content,
  }));

  return [
    { role: "system", content: buildSystemPrompt(companyName) },
    ...recent,
    {
      role: "user",
      content:
        `Context passages:\n\n${context}\n\n---\n\nQuestion: ${question}\n\nAnswer using only the context passages above, citing them like [1].` +
        (options.overview
          ? " Give a short overview in at most 8 bullet points: what the company does, then the main areas its documents cover, then the most important recent events."
          : "") +
        (options.weakMatch && !options.overview
          ? " Note: no passage matched the question closely; these are only the nearest matches. Use any part that does answer it. If none does, say plainly that the documents do not answer this, then name the closest related documents from the catalog that the user could ask about."
          : ""),
    },
  ];
}

// ── Questions about the whole collection, and follow-ups ──────────

const OVERVIEW_PATTERNS = [
  /\bsumm?\w*r\w*\b/i, // summary, summarise, summarize, and typos like "summanry"
  /\boverview\b/i,
  /\bwhat (?:topics|subjects|areas|kinds? of (?:documents|data|files))\b/i,
  /\bwhat (?:documents|files|data|information)\b/i,
  /\bwhich (?:documents|files)\b/i,
  /\blist (?:all |the |our |my )?(?:documents|files|uploads|data)\b/i,
  /\b(?:documents|files|uploads) (?:do we|have we|are there)\b/i,
  /\bwhat (?:do|does|did) (?:our|the|my) (?:documents|files|data|uploads)\b/i,
];

/** True for questions about the document collection as a whole ("summary", "what topics…"). */
export function isOverviewQuestion(question: string): boolean {
  return OVERVIEW_PATTERNS.some((p) => p.test(question));
}

const SHORT_FOLLOW_UP_WORDS = 6;

/**
 * The text to search with. A short follow-up ("give a summary", "and
 * Pimpri?") means little on its own, so it is searched together with the
 * previous question.
 */
export function retrievalQuery(question: string, history: HistoryTurn[]): string {
  const words = question.trim().split(/\s+/).length;
  const lastQuestion = [...history].reverse().find((t) => t.role === "user")?.content;
  const query =
    lastQuestion && words <= SHORT_FOLLOW_UP_WORDS ? `${lastQuestion}\n${question}` : question;
  // "summary" alone matches nothing; ask the search for the passages that
  // summarise the organisation (board papers, manual introductions, reviews)
  return isOverviewQuestion(question)
    ? `${query}\nOverview and summary of the organisation, its services, and its recent key events and results`
    : query;
}

export interface CatalogDocument {
  title: string;
  documentType: string;
  uploadedAt: string; // YYYY-MM-DD
}

const MAX_CATALOG_LINES = 150;

/**
 * One context passage listing the company's documents, for questions about
 * the collection as a whole. Newest documents are kept if there are many.
 */
export function buildCatalogChunk(companyName: string, documents: CatalogDocument[]) {
  const shown = documents.slice(-MAX_CATALOG_LINES);
  const lines = shown.map(
    (d) => `- ${d.uploadedAt} · ${d.documentType} · ${d.title.replace(/[_]+/g, " ")}`
  );
  const header =
    `${companyName} has ${documents.length} uploaded documents` +
    (documents.length > shown.length ? ` (the ${shown.length} most recent are listed)` : "") +
    ". Each line gives the upload date, the format and the document name." +
    " This whole list is one source: cite it as [1], never by line number.";
  return {
    text: `${header}\n${lines.join("\n")}`,
    document_id: "catalog",
    relevance_score: 1,
    metadata: { title: "Company document catalog" },
  };
}

const SMALL_TALK =
  /^(?:hi+|hello|hey|hiya|namaste|good (?:morning|afternoon|evening)|thanks|thank you|thx|ty|ok(?:ay)?|cool|great|nice|bye|goodbye|see you)(?:\s+(?:there|team|bot|all))?[\s!.,?]*$/i;

/** A greeting or acknowledgement that needs no document search. */
export function isSmallTalk(message: string): boolean {
  return SMALL_TALK.test(message.trim());
}

/** Messages for a greeting: no search, just a short friendly reply. */
export function buildSmallTalkMessages(
  companyName: string,
  message: string,
  history: HistoryTurn[] = []
): ChatMessage[] {
  return [
    { role: "system", content: buildSystemPrompt(companyName) },
    ...history.slice(-MAX_HISTORY_TURNS),
    {
      role: "user",
      content: `${message}\n\n(This is a greeting or small talk. Reply in one or two friendly sentences and offer to help with questions about ${companyName}'s documents and data.)`,
    },
  ];
}

export function noResultsAnswer(companyName: string): string {
  return `I couldn't find anything about that in ${companyName}'s uploaded data. Try rephrasing the question, or upload documents that cover this topic on the Data Uploads page.`;
}
