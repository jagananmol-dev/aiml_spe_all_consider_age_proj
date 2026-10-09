/**
 * VEDA AI — Intelligence Service Client
 *
 * All calls to the Python intelligence service go through here so that:
 * - the tenant id always comes from the verified session (passed in by the caller)
 * - the shared internal API key is attached, letting the service reject
 *   requests that don't come from this app
 */

const INTELLIGENCE_URL = process.env.INTELLIGENCE_SERVICE_URL || "http://127.0.0.1:8002";

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

  return fetch(`${INTELLIGENCE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}
