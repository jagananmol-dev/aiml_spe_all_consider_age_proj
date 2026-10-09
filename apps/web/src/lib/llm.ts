/**
 * VEDA AI — LLM provider layer
 *
 * One streaming interface over two wire protocols:
 * - "ollama": Ollama's native /api/chat (lets us set the context window,
 *   which its OpenAI-compatible endpoint does not)
 * - "openai": any OpenAI-compatible /chat/completions server — vLLM,
 *   LiteLLM, LM Studio, or a hosted API
 *
 * Configured with environment variables:
 *   LLM_PROVIDER   ollama | openai        (empty = chatbot disabled)
 *   LLM_BASE_URL   e.g. http://localhost:11434 or https://host/v1
 *   LLM_MODEL      e.g. llama3
 *   LLM_API_KEY    optional bearer token (openai only)
 *   LLM_NUM_CTX    context window in tokens (ollama only, default 6144)
 *   LLM_TEMPERATURE                        (default 0.2 — factual answers)
 *   LLM_KEEP_ALIVE how long Ollama keeps the model loaded (default 24h,
 *                  so answers never wait for the model to reload)
 */

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface LlmConfig {
  provider: "ollama" | "openai";
  baseUrl: string;
  model: string;
  apiKey?: string;
  numCtx: number;
  temperature: number;
  keepAlive: string;
}

export class LlmError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LlmError";
  }
}

export function getLlmConfig(env: NodeJS.ProcessEnv = process.env): LlmConfig | null {
  const provider = env.LLM_PROVIDER?.trim().toLowerCase();
  if (!provider) return null;
  if (provider !== "ollama" && provider !== "openai") {
    throw new LlmError(`Unsupported LLM_PROVIDER "${provider}" (use "ollama" or "openai")`);
  }
  const model = env.LLM_MODEL?.trim();
  if (!model) throw new LlmError("LLM_MODEL must be set");

  const defaultUrl = provider === "ollama" ? "http://localhost:11434" : "http://localhost:8000/v1";
  return {
    provider,
    baseUrl: (env.LLM_BASE_URL?.trim() || defaultUrl).replace(/\/+$/, ""),
    model,
    apiKey: env.LLM_API_KEY?.trim() || undefined,
    numCtx: Number(env.LLM_NUM_CTX) || 6144,
    temperature: env.LLM_TEMPERATURE !== undefined ? Number(env.LLM_TEMPERATURE) : 0.2,
    keepAlive: env.LLM_KEEP_ALIVE?.trim() || "24h",
  };
}

/** Split a byte stream into lines. */
async function* readLines(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) yield line;
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) yield buffer.trim();
  } finally {
    reader.releaseLock();
  }
}

async function request(
  url: string,
  body: unknown,
  config: LlmConfig,
  signal?: AbortSignal
): Promise<ReadableStream<Uint8Array>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (config.apiKey) headers.Authorization = `Bearer ${config.apiKey}`;

  let response: Response;
  try {
    response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new LlmError(`Could not reach the language model at ${config.baseUrl}`);
  }
  if (!response.ok || !response.body) {
    const detail = (await response.text().catch(() => "")).slice(0, 300);
    throw new LlmError(`Language model error (${response.status}): ${detail}`);
  }
  return response.body;
}

/**
 * Stream a chat completion, yielding text fragments as they arrive.
 */
export async function* streamChat(
  messages: ChatMessage[],
  config: LlmConfig,
  signal?: AbortSignal
): AsyncGenerator<string> {
  if (config.provider === "ollama") {
    const body = await request(
      `${config.baseUrl}/api/chat`,
      {
        model: config.model,
        messages,
        stream: true,
        keep_alive: config.keepAlive,
        options: { num_ctx: config.numCtx, temperature: config.temperature },
      },
      config,
      signal
    );
    for await (const line of readLines(body)) {
      const event = JSON.parse(line);
      if (event.error) throw new LlmError(`Language model error: ${event.error}`);
      if (event.message?.content) yield event.message.content as string;
      if (event.done) return;
    }
    return;
  }

  const body = await request(
    `${config.baseUrl}/chat/completions`,
    { model: config.model, messages, stream: true, temperature: config.temperature },
    config,
    signal
  );
  for await (const line of readLines(body)) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (data === "[DONE]") return;
    const event = JSON.parse(data);
    const text = event.choices?.[0]?.delta?.content;
    if (text) yield text as string;
  }
}
