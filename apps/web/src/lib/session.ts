/**
 * VEDA AI — Signed Session Tokens
 *
 * Sessions are stored in the `veda-session` cookie as
 *   base64url(JSON payload) + "." + base64url(HMAC-SHA256(payload))
 *
 * The signature makes the cookie tamper-proof: a client cannot change its
 * tenant, role, or user id without invalidating the token. Uses only the
 * Web Crypto API so it works in both the Edge middleware and Node routes.
 */

export const SESSION_COOKIE = "veda-session";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24; // 24 hours

export interface SessionPayload {
  userId: string;
  email: string;
  name: string;
  role: string;
  tenantId: string;
  tenantSlug: string;
  /** Expiry as a Unix timestamp in seconds */
  exp: number;
}

const DEV_FALLBACK_SECRET = "veda-dev-only-insecure-session-secret";
let warnedAboutFallback = false;

function getSecret(): string {
  const secret = process.env.SESSION_SECRET || process.env.BETTER_AUTH_SECRET;
  if (secret && secret.length >= 16) return secret;

  if (process.env.NODE_ENV === "production") {
    throw new Error("SESSION_SECRET (min 16 chars) must be set in production");
  }
  if (!warnedAboutFallback) {
    console.warn("[session] SESSION_SECRET not set — using insecure development secret");
    warnedAboutFallback = true;
  }
  return DEV_FALLBACK_SECRET;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function getKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(getSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

/**
 * Create a signed session token. `exp` is set automatically.
 */
export async function createSessionToken(
  data: Omit<SessionPayload, "exp">,
  maxAgeSeconds: number = SESSION_MAX_AGE_SECONDS
): Promise<string> {
  const payload: SessionPayload = {
    ...data,
    exp: Math.floor(Date.now() / 1000) + maxAgeSeconds,
  };
  const body = toBase64Url(encoder.encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign("HMAC", await getKey(), encoder.encode(body));
  return `${body}.${toBase64Url(new Uint8Array(signature))}`;
}

/**
 * Verify a session token. Returns the payload, or null if the token is
 * missing, malformed, tampered with, or expired.
 */
export async function verifySessionToken(
  token: string | undefined | null
): Promise<SessionPayload | null> {
  if (!token) return null;

  const parts = token.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  const [body, signature] = parts;

  try {
    const valid = await crypto.subtle.verify(
      "HMAC",
      await getKey(),
      fromBase64Url(signature),
      encoder.encode(body)
    );
    if (!valid) return null;

    const payload = JSON.parse(decoder.decode(fromBase64Url(body))) as SessionPayload;
    if (
      typeof payload.userId !== "string" ||
      typeof payload.tenantId !== "string" ||
      typeof payload.tenantSlug !== "string" ||
      typeof payload.exp !== "number"
    ) {
      return null;
    }
    if (payload.exp * 1000 <= Date.now()) return null;

    return payload;
  } catch {
    return null;
  }
}
