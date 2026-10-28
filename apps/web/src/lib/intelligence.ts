/**
 * VEDA AI — Intelligence Service Client
 *
 * All calls to the Python intelligence service go through here so that:
 * - the tenant id always comes from the verified session (passed in by the caller)
 * - the shared internal API key is attached, letting the service reject
 *   requests that don't come from this app
 * - in hosted mode (COMPUTE_NODE=tunnel) requests go through the tunnel to
 *   the owner's PC; see lib/computeNode.ts
 */

import { forgetComputeNodeUrl, isTunnelMode, resolveIntelligenceUrl } from "@/lib/computeNode";

const INTELLIGENCE_URL = process.env.INTELLIGENCE_SERVICE_URL || "http://127.0.0.1:8002";
// A search takes milliseconds; the first call after start-up may load models
const TIMEOUT_MS = Number(process.env.INTELLIGENCE_TIMEOUT_MS) || 60_000;

export async function intelligenceFetch(
  path: string,
  tenantId: string,
  body: unknown
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Tenant-ID": tenantId,
  };
  if (process.env.INTERNAL_API_KEY) {
    headers["X-Internal-Key"] = process.env.INTERNAL_API_KEY;
  }

  const baseUrl = await resolveIntelligenceUrl(INTELLIGENCE_URL);
  try {
    return await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    // A tunnel that just closed: look the address up again next time
    if (isTunnelMode()) forgetComputeNodeUrl();
    throw error;
  }
}
