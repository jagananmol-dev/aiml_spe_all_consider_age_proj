/**
 * VEDA AI — LLM provider layer and chat prompt tests
 */

import { getLlmConfig, LlmError, streamChat, type LlmConfig } from "@/lib/llm";
import { buildMessages, buildSystemPrompt, numberSources } from "@/lib/chatPrompt";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

async function collect(gen: AsyncGenerator<string>): Promise<string> {
  let out = "";
  for await (const t of gen) out += t;
  return out;
}

const OLLAMA: LlmConfig = {
  provider: "ollama",
  baseUrl: "http://localhost:11434",
  model: "llama3",
  numCtx: 6144,
  temperature: 0.2,
  keepAlive: "24h",
};

afterEach(() => jest.restoreAllMocks());

describe("getLlmConfig", () => {
  it("returns null when no provider is configured", () => {
    expect(getLlmConfig({} as NodeJS.ProcessEnv)).toBeNull();
  });

  it("reads Ollama settings with defaults", () => {
    const config = getLlmConfig({ LLM_PROVIDER: "ollama", LLM_MODEL: "llama3" } as never);
    expect(config).toEqual({ ...OLLAMA, apiKey: undefined });
  });

  it("rejects unknown providers and a missing model", () => {
    expect(() => getLlmConfig({ LLM_PROVIDER: "foo", LLM_MODEL: "x" } as never)).toThrow(LlmError);
    expect(() => getLlmConfig({ LLM_PROVIDER: "ollama" } as never)).toThrow(LlmError);
  });
});

describe("streamChat — ollama", () => {
  it("streams NDJSON fragments split across network chunks", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        new Response(
          streamOf([
            '{"message":{"content":"Rev"},"done":false}\n{"message":{"con',
            'tent":"enue [1]"},"done":false}\n',
            '{"message":{"content":""},"done":true}\n',
          ])
        )
      );
    const text = await collect(streamChat([{ role: "user", content: "q" }], OLLAMA));
    expect(text).toBe("Revenue [1]");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:11434/api/chat");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({ model: "llama3", stream: true, options: { num_ctx: 6144 } });
  });

  it("surfaces model errors", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(streamOf(['{"error":"model not found"}\n'])));
    await expect(collect(streamChat([], OLLAMA))).rejects.toThrow("model not found");
  });

  it("reports an unreachable server clearly", async () => {
    jest.spyOn(global, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    await expect(collect(streamChat([], OLLAMA))).rejects.toThrow(/Could not reach/);
  });

  it("reports HTTP errors with status", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(new Response("no such model", { status: 404 }));
    await expect(collect(streamChat([], OLLAMA))).rejects.toThrow(/404/);
  });
});

describe("streamChat — openai-compatible", () => {
  it("parses SSE deltas and sends the bearer key", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        new Response(
          streamOf([
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: [DONE]\n\n',
          ])
        )
      );
    const config: LlmConfig = {
      ...OLLAMA,
      provider: "openai",
      baseUrl: "http://vllm:8000/v1",
      apiKey: "k",
    };
    expect(await collect(streamChat([], config))).toBe("Hello");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://vllm:8000/v1/chat/completions");
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer k" });
  });
});

describe("chat prompt", () => {
  const chunks = [
    {
      text: "Q3 revenue was 5M.",
      document_id: "d1",
      relevance_score: 0.9,
      metadata: { title: "q3.pdf" },
    },
    {
      text: "Q3 revenue was 5M.",
      document_id: "d1",
      relevance_score: 0.8,
      metadata: { title: "q3.pdf" },
    },
    { text: "Costs fell 3%.", document_id: "d2", relevance_score: 0.7, metadata: {} },
  ];

  it("numbers and deduplicates sources", () => {
    const sources = numberSources(chunks);
    expect(sources.map((s) => [s.index, s.title])).toEqual([
      [1, "q3.pdf"],
      [2, "Untitled document"],
    ]);
  });

  it("names the company and forbids invented facts", () => {
    const prompt = buildSystemPrompt("Acme Hospital");
    expect(prompt).toContain("AI assistant for Acme Hospital");
    expect(prompt).toMatch(/Never invent/);
    expect(prompt).toMatch(/Acme Hospital's policy in the context, apply its rules/);
  });

  it("puts numbered context and the question in the last user message", () => {
    const messages = buildMessages("Acme", "What was Q3 revenue?", numberSources(chunks), [
      { role: "user", content: "hi" },
      { role: "assistant", content: "x".repeat(5000) },
    ]);
    expect(messages[0].role).toBe("system");
    expect(messages[2].content.length).toBeLessThan(2100);
    const last = messages[messages.length - 1];
    expect(last.content).toContain("[1] Source: q3.pdf\nQ3 revenue was 5M.");
    expect(last.content).toContain("Question: What was Q3 revenue?");
  });
});
