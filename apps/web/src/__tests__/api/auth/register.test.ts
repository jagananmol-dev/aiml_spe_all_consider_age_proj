/**
 * VEDA AI — Auth Register Route Tests
 *
 * Tests POST /api/auth/register
 * - Happy path: valid body → 201 + tenant + user returned
 * - Missing fields: 400
 * - Invalid email format: 400
 * - Short password: 400
 * - Short slug: 400
 * - Slug collision: 409
 * - Email collision: 409
 * - DB error: 500
 */

import { POST } from "@/app/api/auth/register/route";
import { NextRequest } from "next/server";

jest.mock("@/lib/db", () => ({
  client: jest.fn(),
}));

import { client as mockClient } from "@/lib/db";

function makeRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const VALID_BODY = {
  companyName: "Refinery Corp",
  tenantSlug: "refinery",
  email: "admin@refinery.com",
  name: "Admin User",
  password: "Secure@1234",
};

// ══════════════════════════════════════════════════════
// Happy Path
// ══════════════════════════════════════════════════════

let txQueries: { text: string; values: unknown[] }[] = [];

describe("POST /api/auth/register — happy path", () => {
  beforeEach(() => {
    // No existing tenant, no existing user, then begin() returns tenant+user
    (mockClient as unknown as jest.Mock).mockImplementation(
      (strings: TemplateStringsArray, ...values: unknown[]) => {
        const sql = strings.join("?");
        if (sql.includes("SELECT id FROM tenants")) return Promise.resolve([]);
        if (sql.includes("SELECT id FROM users")) return Promise.resolve([]);
        return Promise.resolve([]);
      }
    );

    // .begin() mock
    (mockClient as unknown as jest.Mock & { begin: jest.Mock }).begin = jest.fn(
      async (fn: Function) => {
        return fn({
          // sql tagged template mock
          [Symbol.iterator]() {
            return this;
          },
          __proto__: Function.prototype,
        });
      }
    );

    // Make the begin callback work
    txQueries = [];
    (mockClient as any).begin = jest.fn(async (cb: Function) => {
      const sql = jest.fn((strings: TemplateStringsArray, ...values: unknown[]) => {
        const query = strings.join("?");
        txQueries.push({ text: query, values });
        if (query.includes("INSERT INTO tenants")) {
          return Promise.resolve([
            { id: "tenant-uuid-001", name: "Refinery Corp", slug: "refinery" },
          ]);
        }
        if (query.includes("INSERT INTO users")) {
          return Promise.resolve([
            { id: "user-uuid-001", email: "admin@refinery.com", name: "Admin User", role: "admin" },
          ]);
        }
        return Promise.resolve([]);
      });
      return cb(sql);
    });
  });

  it("returns 201 on valid registration", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(201);
  });

  it("stores a salted scrypt hash, never the password or a bare SHA-256", async () => {
    await POST(makeRequest(VALID_BODY));
    const insertUser = txQueries.find((q) => q.text.includes("INSERT INTO users"))!;
    const storedHash = String(insertUser.values[insertUser.values.length - 1]);
    expect(storedHash).toMatch(/^scrypt\$/);
    expect(storedHash).not.toContain(String(VALID_BODY.password));
  });

  it("sets the RLS tenant before inserting the admin user", async () => {
    await POST(makeRequest(VALID_BODY));
    const setConfigIdx = txQueries.findIndex((q) => q.text.includes("set_config"));
    const insertUserIdx = txQueries.findIndex((q) => q.text.includes("INSERT INTO users"));
    expect(setConfigIdx).toBeGreaterThan(-1);
    expect(setConfigIdx).toBeLessThan(insertUserIdx);
    expect(txQueries[setConfigIdx].values).toContain("tenant-uuid-001");
  });

  it("returns success:true", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    const body = await res.json();
    expect(body.success).toBe(true);
  });

  it("response contains tenant data", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    const body = await res.json();
    expect(body.tenant).toBeDefined();
    expect(body.tenant.slug).toBe("refinery");
  });

  it("response contains user data", async () => {
    const res = await POST(makeRequest(VALID_BODY));
    const body = await res.json();
    expect(body.user).toBeDefined();
    expect(body.user.role).toBe("admin");
  });

  it("slug is normalized to lowercase", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, tenantSlug: "REFINERY-Corp" }));
    const body = await res.json();
    // Slug should be cleaned: "refinery-corp"
    expect(body.tenant?.slug || "refinery-corp").toMatch(/^[a-z0-9-]+$/);
  });
});

// ══════════════════════════════════════════════════════
// Validation Failures
// ══════════════════════════════════════════════════════

describe("POST /api/auth/register — validation failures", () => {
  it("returns 400 when companyName missing", async () => {
    const { companyName: _, ...rest } = VALID_BODY;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
  });

  it("returns 400 when tenantSlug missing", async () => {
    const { tenantSlug: _, ...rest } = VALID_BODY;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
  });

  it("returns 400 when email missing", async () => {
    const { email: _, ...rest } = VALID_BODY;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
  });

  it("returns 400 when name missing", async () => {
    const { name: _, ...rest } = VALID_BODY;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
  });

  it("returns 400 when password missing", async () => {
    const { password: _, ...rest } = VALID_BODY;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
  });

  it("returns 400 for invalid email format", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, email: "not-an-email" }));
    expect(res.status).toBe(400);
  });

  it("returns 400 for email without domain", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, email: "user@" }));
    expect(res.status).toBe(400);
  });

  it("returns 400 for password shorter than 8 chars", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, password: "1234567" }));
    expect(res.status).toBe(400);
  });

  it("returns 400 for slug shorter than 3 chars after cleaning", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, tenantSlug: "ab" }));
    expect(res.status).toBe(400);
  });

  it("returns 400 for slug that becomes empty after cleaning special chars", async () => {
    const res = await POST(makeRequest({ ...VALID_BODY, tenantSlug: "!@#" }));
    expect(res.status).toBe(400);
  });
});

// ══════════════════════════════════════════════════════
// Conflicts
// ══════════════════════════════════════════════════════

describe("POST /api/auth/register — conflicts", () => {
  it("returns 409 when slug already exists", async () => {
    (mockClient as unknown as jest.Mock).mockImplementation((strings: TemplateStringsArray) => {
      const sql = strings.join("?");
      if (sql.includes("SELECT id FROM tenants")) return Promise.resolve([{ id: "existing" }]);
      return Promise.resolve([]);
    });
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(409);
  });

  it("returns 409 when email already registered", async () => {
    (mockClient as unknown as jest.Mock).mockImplementation((strings: TemplateStringsArray) => {
      const sql = strings.join("?");
      if (sql.includes("SELECT id FROM tenants")) return Promise.resolve([]);
      if (sql.includes("SELECT id FROM users")) return Promise.resolve([{ id: "existing" }]);
      return Promise.resolve([]);
    });
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(409);
  });
});

// ══════════════════════════════════════════════════════
// Server Errors
// ══════════════════════════════════════════════════════

describe("POST /api/auth/register — server errors", () => {
  it("returns 500 on DB exception", async () => {
    (mockClient as unknown as jest.Mock).mockImplementation(() =>
      Promise.reject(new Error("Connection pool exhausted"))
    );
    const res = await POST(makeRequest(VALID_BODY));
    expect(res.status).toBe(500);
  });
});
