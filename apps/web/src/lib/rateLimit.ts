/**
 * VEDA AI — Fixed-window rate limiter (in memory)
 *
 * Slows password guessing and sign-up abuse. State lives in this server
 * process, so with several app instances each one limits on its own; put
 * a shared store (Redis) behind `hit` when running more than one.
 */

interface Window {
  count: number;
  resetAt: number;
}

const windows = new Map<string, Window>();
const MAX_KEYS = 10_000;

/**
 * Count one attempt for `key`. Returns how many seconds to wait when the
 * limit is exceeded, or 0 when the attempt is allowed.
 */
export function hit(key: string, limit: number, windowSeconds: number): number {
  const now = Date.now();
  let entry = windows.get(key);
  if (!entry || entry.resetAt <= now) {
    if (windows.size >= MAX_KEYS) {
      for (const [k, w] of windows) if (w.resetAt <= now) windows.delete(k);
      if (windows.size >= MAX_KEYS) windows.delete(windows.keys().next().value as string);
    }
    entry = { count: 0, resetAt: now + windowSeconds * 1000 };
    windows.set(key, entry);
  }
  entry.count += 1;
  return entry.count > limit ? Math.ceil((entry.resetAt - now) / 1000) : 0;
}

/** Forget a key (e.g. after a successful login). */
export function reset(key: string): void {
  windows.delete(key);
}

/** The caller's address as reported by the proxy, for rate-limit keys. */
export function clientIp(headers: Headers): string {
  return (
    headers.get("x-forwarded-for")?.split(",")[0].trim() || headers.get("x-real-ip") || "unknown"
  );
}

/** Test helper: clear all windows. */
export function _resetAll(): void {
  windows.clear();
}
