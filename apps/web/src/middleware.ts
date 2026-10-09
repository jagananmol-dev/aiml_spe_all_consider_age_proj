import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

/**
 * VEDA AI — Auth & Tenant Context Middleware
 *
 * The tenant is derived ONLY from the signed session cookie. Tenant headers
 * sent by the client are stripped, so a caller cannot choose another tenant
 * by setting `x-tenant-slug` or a subdomain.
 *
 * Flow:
 * 1. Public paths pass through (with spoofable context headers removed)
 * 2. Protected pages without a valid session redirect to /login
 * 3. Protected API routes without a valid session get 401
 * 4. Valid sessions get tenant/user context injected into request headers
 */

const PUBLIC_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/terms",
  "/privacy",
  "/api/auth",
  "/api/health",
  "/_next",
  "/favicon.ico",
  "/assets",
];

const CONTEXT_HEADERS = ["x-tenant-slug", "x-tenant-id", "x-user-id", "x-user-role"];

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

function stripContextHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  for (const name of CONTEXT_HEADERS) headers.delete(name);
  return headers;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const requestHeaders = stripContextHeaders(request);

  if (isPublicPath(pathname)) {
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  const session = await verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value);

  if (!session) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    const response = NextResponse.redirect(loginUrl);
    // Drop any stale or forged session cookie
    response.cookies.delete(SESSION_COOKIE);
    return response;
  }

  // ── Inject verified tenant context ─────────────────
  requestHeaders.set("x-tenant-slug", session.tenantSlug);
  requestHeaders.set("x-tenant-id", session.tenantId);
  requestHeaders.set("x-user-id", session.userId);
  requestHeaders.set("x-user-role", session.role);
  requestHeaders.set("x-request-id", crypto.randomUUID());
  requestHeaders.set("x-request-timestamp", new Date().toISOString());

  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: [
    // Match all paths except static files
    "/((?!_next/static|_next/image|favicon.ico|assets/).*)",
  ],
};
