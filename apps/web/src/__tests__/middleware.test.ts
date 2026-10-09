/**
 * VEDA AI — Middleware Unit Tests
 *
 * Critical security tests:
 * 1. Tenant context comes only from the signed session cookie
 * 2. Client-supplied x-tenant-* headers and ?tenant= are ignored
 * 3. Forged / malformed / expired cookies are rejected
 * 4. Protected pages redirect to /login; protected APIs return 401
 * 5. Public routes pass through
 */

import { middleware } from "@/middleware";
import { NextRequest } from "next/server";
import { createSessionToken } from "@/lib/session";

function makeRequest(
  path: string,
  opts: {
    cookies?: Record<string, string>;
    headers?: Record<string, string>;
  } = {}
): NextRequest {
  const headers = new Headers(opts.headers ?? {});
  if (opts.cookies) {
    const cookieStr = Object.entries(opts.cookies)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("; ");
    headers.set("Cookie", cookieStr);
  }
  return new NextRequest(`http://localhost${path}`, { method: "GET", headers });
}

/** Header the middleware forwarded to the route handler */
function forwarded(res: Response, name: string): string | null {
  return res.headers.get(`x-middleware-request-${name}`);
}

const SESSION_DATA = {
  userId: "u1",
  email: "admin@refinery.com",
  name: "Admin",
  role: "admin",
  tenantId: "tenant-uuid-001",
  tenantSlug: "refinery",
};

let validToken: string;

beforeAll(async () => {
  validToken = await createSessionToken(SESSION_DATA);
});

describe("Middleware — tenant context", () => {
  it("injects tenant context from a valid signed session", async () => {
    const res = await middleware(
      makeRequest("/dashboard", { cookies: { "veda-session": validToken } })
    );
    expect(res.status).toBe(200);
    expect(forwarded(res, "x-tenant-id")).toBe("tenant-uuid-001");
    expect(forwarded(res, "x-tenant-slug")).toBe("refinery");
    expect(forwarded(res, "x-user-id")).toBe("u1");
  });

  it("overrides a client-supplied x-tenant-slug header with the session tenant", async () => {
    const res = await middleware(
      makeRequest("/api/compliance/status", {
        headers: { "x-tenant-slug": "victim-corp", "x-tenant-id": "victim-id" },
        cookies: { "veda-session": validToken },
      })
    );
    expect(forwarded(res, "x-tenant-slug")).toBe("refinery");
    expect(forwarded(res, "x-tenant-id")).toBe("tenant-uuid-001");
  });

  it("ignores ?tenant= query parameter", async () => {
    const res = await middleware(
      makeRequest("/dashboard?tenant=hacker-corp", { cookies: { "veda-session": validToken } })
    );
    expect(forwarded(res, "x-tenant-slug")).toBe("refinery");
  });

  it("strips client tenant headers on public routes", async () => {
    const res = await middleware(
      makeRequest("/api/auth/login", { headers: { "x-tenant-id": "victim-id" } })
    );
    expect(forwarded(res, "x-tenant-id")).toBeNull();
  });
});

describe("Middleware — auth guard", () => {
  it("redirects unauthenticated page requests to /login", async () => {
    const res = await middleware(makeRequest("/dashboard"));
    expect(res.status).toBe(307);
    expect(res.headers.get("Location")).toContain("/login");
  });

  it("returns 401 for unauthenticated API requests", async () => {
    const res = await middleware(makeRequest("/api/documents/upload"));
    expect(res.status).toBe(401);
  });

  it("does not trust a tenant header without a session", async () => {
    const res = await middleware(
      makeRequest("/api/compliance/status", { headers: { "x-tenant-slug": "refinery" } })
    );
    expect(res.status).toBe(401);
  });

  it.each(["/", "/login", "/register", "/terms", "/privacy", "/api/auth/login"])(
    "allows unauthenticated access to %s",
    async (path) => {
      const res = await middleware(makeRequest(path));
      expect(res.status).toBe(200);
    }
  );
});

describe("Middleware — forged and malformed cookies", () => {
  it("rejects a forged unsigned JSON session", async () => {
    const forged = JSON.stringify({ ...SESSION_DATA, tenantId: "victim" });
    const res = await middleware(
      makeRequest("/dashboard", { cookies: { "veda-session": forged } })
    );
    expect(res.status).toBe(307);
  });

  it("rejects a token whose payload was tampered with", async () => {
    const [, signature] = validToken.split(".");
    const tamperedBody = Buffer.from(
      JSON.stringify({ ...SESSION_DATA, tenantId: "victim", exp: 9999999999 })
    ).toString("base64url");
    const res = await middleware(
      makeRequest("/api/documents/upload", {
        cookies: { "veda-session": `${tamperedBody}.${signature}` },
      })
    );
    expect(res.status).toBe(401);
  });

  it("rejects an expired token", async () => {
    const expired = await createSessionToken(SESSION_DATA, -10);
    const res = await middleware(
      makeRequest("/dashboard", { cookies: { "veda-session": expired } })
    );
    expect(res.status).toBe(307);
  });

  it.each(["{invalid-json", "", "a.b.c"])(
    "handles malformed cookie %p without error",
    async (v) => {
      const res = await middleware(makeRequest("/dashboard", { cookies: { "veda-session": v } }));
      expect(res.status).toBe(307);
    }
  );
});
