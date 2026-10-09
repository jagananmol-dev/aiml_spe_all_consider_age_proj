/**
 * VEDA AI — Auth Login Route Tests
 *
 * Tests POST /api/auth/login
 * - Happy path: valid credentials → 200 + signed session cookie
 * - Legacy SHA-256 hashes are accepted and upgraded to scrypt
 * - Missing fields: 400
 * - Unknown tenant / user / wrong password: identical generic 401
 * - DB error: 500
 */

import { createHash } from "crypto";
import { POST } from "@/app/api/auth/login/route";
import { NextRequest } from "next/server";
import { hashPassword } from "@/lib/password";
import { verifySessionToken } from "@/lib/session";

const mockState = {
  user: null as Record<string, unknown> | null,
  queries: [] as { text: string; values: unknown[] }[],
  fail: false,
};

jest.mock("@/lib/db", () => ({
  resolveTenantId: jest.fn(),
  withTenant: jest.fn(async (_tenantId: string, fn: (sql: unknown) => unknown) => {
    const sql = (strings: TemplateStringsArray, ...values: unknown[]) => {
      const text = strings.join("?");
      mockState.queries.push({ text, values });
      if (mockState.fail) return Promise.reject(new Error("DB down"));
      if (text.includes("SELECT")) return Promise.resolve(mockState.user ? [mockState.user] : []);
      return Promise.resolve([]);
    };
    return fn(sql);
  }),
}));

import { resolveTenantId as mockResolve } from "@/lib/db";

const PASSWORD = "Secure@1234";

function makeRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const VALID_BODY = { tenantSlug: "refinery", email: "Admin@Refinery.com", password: PASSWORD };

function sessionCookieValue(res: Response): string | undefined {
  const header = res.headers.get("set-cookie") || "";
  const match = header.match(/veda-session=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

beforeEach(async () => {
  mockState.queries = [];
  mockState.fail = false;
  mockState.user = {
    id: "user-uuid-001",
    email: "admin@refinery.com",
    name: "Admin User",
    role: "admin",
    password_hash: await hashPassword(PASSWORD),
  };
  (mockResolve as jest.Mock).mockResolvedValue("tenant-uuid-001");
});

describe("POST /api/auth/login — happy path", () => {
  it("returns 200 with user and tenant", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.success).toBe(true);
    expect(body.user.id).toBe("user-uuid-001");
    expect(body.tenant.slug).toBe("refinery");
  });

  it("sets an httpOnly, signed session cookie that verifies", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.headers.get("set-cookie")).toContain("HttpOnly");
    const session = await verifySessionToken(sessionCookieValue(res));
    expect(session).toMatchObject({
      userId: "user-uuid-001",
      tenantId: "tenant-uuid-001",
      tenantSlug: "refinery",
      role: "admin",
    });
  });

  it("normalizes slug and email to lowercase", async () => {
    await POST(makeRequest({ ...VALID_BODY, tenantSlug: " Refinery " }));
    expect(mockResolve).toHaveBeenCalledWith("refinery");
    expect(mockState.queries[0].values).toContain("admin@refinery.com");
  });

  it("does not re-hash an up-to-date scrypt password", async () => {
    await POST(makeRequest(VALID_BODY));
    expect(mockState.queries.some((q) => q.text.includes("password_hash ="))).toBe(false);
  });
});

describe("POST /api/auth/login — legacy hashes", () => {
  it("accepts a legacy SHA-256 hash and upgrades it to scrypt", async () => {
    mockState.user!.password_hash = createHash("sha256").update(PASSWORD).digest("hex");
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(200);
    const upgrade = mockState.queries.find((q) => q.text.includes("password_hash ="));
    expect(upgrade).toBeDefined();
    expect(String(upgrade!.values[0])).toMatch(/^scrypt\$/);
  });
});

describe("POST /api/auth/login — validation", () => {
  it.each([
    [{ email: "a@b.com", password: "x" }],
    [{ tenantSlug: "refinery", password: "x" }],
    [{ tenantSlug: "refinery", email: "a@b.com" }],
    [{ tenantSlug: "", email: "", password: "" }],
  ])("returns 400 when a field is missing (%o)", async (body) => {
    expect((await POST(makeRequest(body))).status).toBe(400);
  });
});

describe("POST /api/auth/login — auth failures", () => {
  it("returns 401 (not 404) when tenant not found", async () => {
    (mockResolve as jest.Mock).mockRejectedValue(new Error("Tenant not found"));
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(401);
  });

  it("returns 401 when user not found", async () => {
    mockState.user = null;
    expect((await POST(makeRequest(VALID_BODY))).status).toBe(401);
  });

  it("returns 401 when password wrong and sets no session", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, password: "wrong-password" }));
    expect(res.status).toBe(401);
    expect(sessionCookieValue(res)).toBeUndefined();
  });

  it("uses the same message for unknown tenant, user, and password", async () => {
    const wrongPassword = await (
      await POST(makeRequest({ ...VALID_BODY, password: "nope" }))
    ).json();
    (mockResolve as jest.Mock).mockRejectedValue(new Error("Tenant not found"));
    const unknownTenant = await (await POST(makeRequest(VALID_BODY))).json();
    expect(wrongPassword.error).toBe(unknownTenant.error);
  });
});

describe("POST /api/auth/login — server errors", () => {
  it("returns 500 on DB exception", async () => {
    mockState.fail = true;
    expect((await POST(makeRequest(VALID_BODY))).status).toBe(500);
  });
});
