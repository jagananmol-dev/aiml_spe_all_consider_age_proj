/**
 * VEDA AI — Compute node (hosted mode)
 *
 * - direct mode: the configured intelligence URL, no database calls
 * - tunnel mode: activity is recorded (throttled), the live tunnel address
 *   is used, and a closed tunnel raises ComputeNodeOfflineError
 * - Ollama is routed through the /llm proxy with the internal key
 */

const mockQueries: string[] = [];
let mockRows: Record<string, unknown>[] = [];

jest.mock("@/lib/db", () => ({
  client: (strings: TemplateStringsArray) => {
    mockQueries.push(strings.join("?"));
    return Promise.resolve(strings.join("?").includes("SELECT") ? mockRows : []);
  },
}));

import {
  _resetComputeNode,
  ComputeNodeOfflineError,
  resolveIntelligenceUrl,
  routeLlmThroughComputeNode,
} from "@/lib/computeNode";
import type { LlmConfig } from "@/lib/llm";

const ollama: LlmConfig = {
  provider: "ollama",
  baseUrl: "http://localhost:11434",
  model: "llama3",
  numCtx: 6144,
  temperature: 0.2,
  keepAlive: "24h",
};

const savedEnv = { ...process.env };

beforeEach(() => {
  _resetComputeNode();
  mockQueries.length = 0;
  mockRows = [];
  process.env = { ...savedEnv };
});

afterAll(() => {
  process.env = savedEnv;
});

describe("direct mode", () => {
  it("uses the configured URL without touching the database", async () => {
    expect(await resolveIntelligenceUrl("http://127.0.0.1:8002")).toBe("http://127.0.0.1:8002");
    expect(await routeLlmThroughComputeNode(ollama)).toBe(ollama);
    expect(mockQueries).toEqual([]);
  });
});

describe("tunnel mode", () => {
  beforeEach(() => {
    process.env.COMPUTE_NODE = "tunnel";
    process.env.INTERNAL_API_KEY = "internal-key-123456";
  });

  it("records activity and returns the tunnel address", async () => {
    mockRows = [{ tunnel_url: "https://abc.trycloudflare.com/" }];
    expect(await resolveIntelligenceUrl("http://unused")).toBe("https://abc.trycloudflare.com");
    expect(mockQueries[0]).toContain("UPDATE compute_node SET wanted_at = NOW()");
    expect(mockQueries[1]).toContain("seen_at > NOW()");
  });

  it("throttles activity writes and caches the address", async () => {
    mockRows = [{ tunnel_url: "https://abc.trycloudflare.com" }];
    await resolveIntelligenceUrl("");
    await resolveIntelligenceUrl("");
    expect(mockQueries.filter((q) => q.includes("UPDATE"))).toHaveLength(1);
    expect(mockQueries.filter((q) => q.includes("SELECT"))).toHaveLength(1);
  });

  it("is offline while no tunnel is open", async () => {
    await expect(resolveIntelligenceUrl("")).rejects.toBeInstanceOf(ComputeNodeOfflineError);
    // the request still counted as activity, which is what wakes the PC
    expect(mockQueries[0]).toContain("wanted_at");
  });

  it("routes Ollama through the authenticated /llm proxy", async () => {
    mockRows = [{ tunnel_url: "https://abc.trycloudflare.com" }];
    const routed = await routeLlmThroughComputeNode(ollama);
    expect(routed.baseUrl).toBe("https://abc.trycloudflare.com/llm");
    expect(routed.headers).toEqual({ "X-Internal-Key": "internal-key-123456" });
  });

  it("leaves a hosted OpenAI-compatible API alone", async () => {
    const hosted: LlmConfig = { ...ollama, provider: "openai", baseUrl: "https://api.groq.com/openai/v1" };
    expect(await routeLlmThroughComputeNode(hosted)).toBe(hosted);
  });
});
