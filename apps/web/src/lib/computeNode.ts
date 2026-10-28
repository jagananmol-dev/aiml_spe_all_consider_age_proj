import { client } from "@/lib/db";
import type { LlmConfig } from "@/lib/llm";

/**
 * VEDA AI — Compute node (hosted mode)
 *
 * With COMPUTE_NODE=tunnel the web app runs on a serverless host, and the
 * heavy parts (intelligence service, ingestion worker, Ollama) run on the
 * owner's own PC. The two meet in the single `compute_node` row
 * (006_hosted_mode.sql):
 *
 * - while a signed-in user is active, the web app stamps `wanted_at`
 * - scripts/compute-node.js on the PC sees that, opens a Cloudflare tunnel
 *   to its intelligence service, and writes `tunnel_url` + `seen_at`
 * - when nobody has been active for a while, the agent closes the tunnel
 *
 * Ollama is not exposed on its own: chat goes to the intelligence service's
 * /llm proxy, which requires the internal API key.
 */

// The agent refreshes seen_at every 30 s while the tunnel is open
const SEEN_WITHIN_SECONDS = 90;
const URL_CACHE_MS = 5_000;
const ACTIVITY_THROTTLE_MS = 15_000;

let cachedUrl: { url: string | null; at: number } | null = null;
let lastActivityMark = 0;

export class ComputeNodeOfflineError extends Error {
  constructor(
    message = "The assistant is starting on the host computer. Try again in a few seconds."
  ) {
    super(message);
    this.name = "ComputeNodeOfflineError";
  }
}

export function isTunnelMode(): boolean {
  return process.env.COMPUTE_NODE === "tunnel";
}

/** Record that someone is using the site, so the agent opens (or keeps) the tunnel. */
export async function markActivity(): Promise<void> {
  if (Date.now() - lastActivityMark < ACTIVITY_THROTTLE_MS) return;
  lastActivityMark = Date.now();
  // Writes at most every 15 s across all instances
  await client`
    UPDATE compute_node SET wanted_at = NOW()
    WHERE id = 1 AND (wanted_at IS NULL OR wanted_at < NOW() - INTERVAL '15 seconds')
  `;
}

/** The tunnel's address while the agent reports it alive, else null. */
export async function getComputeNodeUrl(): Promise<string | null> {
  if (cachedUrl && Date.now() - cachedUrl.at < URL_CACHE_MS) return cachedUrl.url;
  const rows = await client`
    SELECT tunnel_url FROM compute_node
    WHERE id = 1 AND tunnel_url IS NOT NULL
      AND seen_at > NOW() - make_interval(secs => ${SEEN_WITHIN_SECONDS})
  `;
  const url = rows.length > 0 ? String(rows[0].tunnel_url).replace(/\/+$/, "") : null;
  cachedUrl = { url, at: Date.now() };
  return url;
}

/** Drop the cached address, e.g. after a request through it failed. */
export function forgetComputeNodeUrl(): void {
  cachedUrl = null;
}

/**
 * The intelligence service's base URL. In tunnel mode this also counts as
 * activity, and throws ComputeNodeOfflineError while the tunnel is closed.
 */
export async function resolveIntelligenceUrl(directUrl: string): Promise<string> {
  if (!isTunnelMode()) return directUrl;
  try {
    await markActivity();
  } catch (error) {
    console.warn("[compute-node] Could not record activity:", error);
  }
  const url = await getComputeNodeUrl();
  if (!url) throw new ComputeNodeOfflineError();
  return url;
}

/**
 * Point an Ollama config at the PC's /llm proxy in tunnel mode. Other
 * providers (a hosted OpenAI-compatible API) are used directly.
 */
export async function routeLlmThroughComputeNode(config: LlmConfig): Promise<LlmConfig> {
  if (!isTunnelMode() || config.provider !== "ollama") return config;
  const url = await resolveIntelligenceUrl("");
  const headers: Record<string, string> = {};
  if (process.env.INTERNAL_API_KEY) headers["X-Internal-Key"] = process.env.INTERNAL_API_KEY;
  return { ...config, baseUrl: `${url}/llm`, headers };
}

/** Test helper: clear module state. */
export function _resetComputeNode(): void {
  cachedUrl = null;
  lastActivityMark = 0;
}
