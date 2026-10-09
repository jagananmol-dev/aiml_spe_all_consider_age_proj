/**
 * VEDA AI — db.ts Library Unit Tests
 *
 * - resolveTenantId: found, not found, active-only filter, caching
 * - withTenant: runs in a transaction and sets RLS context first
 * - getScopedDb: tenant comes only from a valid signed session
 */

import { createSessionToken } from "@/lib/session";

// Mock all external deps BEFORE importing db.ts
jest.mock("postgres", () => {
  const mockSql = jest.fn(() => Promise.resolve([]));
  (mockSql as any).begin = jest.fn();
  return jest.fn(() => mockSql);
});

jest.mock("drizzle-orm/postgres-js", () => ({
  drizzle: jest.fn(() => ({})),
}));

let mockCookieValue: string | undefined;
jest.mock("next/headers", () => ({
  cookies: jest.fn(async () => ({
    get: (name: string) =>
      name === "veda-session" && mockCookieValue !== undefined
        ? { value: mockCookieValue }
        : undefined,
  })),
}));

import { resolveTenantId, withTenant, getScopedDb, UnauthorizedError } from "@/lib/db";

const postgres = require("postgres");
const mockSqlInstance = postgres();

beforeEach(() => {
  mockSqlInstance.mockReset();
  mockSqlInstance.mockImplementation(() => Promise.resolve([]));
  mockCookieValue = undefined;
});

describe("resolveTenantId", () => {
  it("returns tenant ID on valid slug", async () => {
    mockSqlInstance.mockImplementationOnce(() => Promise.resolve([{ id: "tenant-uuid-001" }]));
    expect(await resolveTenantId("refinery")).toBe("tenant-uuid-001");
  });

  it("throws when tenant not found", async () => {
    await expect(resolveTenantId("unknown-slug")).rejects.toThrow();
  });

  it("only matches active tenants", async () => {
    mockSqlInstance.mockImplementationOnce(() => Promise.resolve([{ id: "t" }]));
    await resolveTenantId("active-check");
    const [strings] = mockSqlInstance.mock.calls[0];
    expect((strings as string[]).join("")).toContain("is_active = true");
  });

  it("caches the result", async () => {
    mockSqlInstance.mockImplementationOnce(() => Promise.resolve([{ id: "tenant-cached-001" }]));
    const id1 = await resolveTenantId("cached-slug");
    const id2 = await resolveTenantId("cached-slug");
    expect(id1).toBe(id2);
    expect(mockSqlInstance).toHaveBeenCalledTimes(1);
  });
});

describe("withTenant", () => {
  it("sets the RLS tenant inside the transaction before running queries", async () => {
    const txCalls: string[] = [];
    const txSql = jest.fn((strings: TemplateStringsArray, ...values: unknown[]) => {
      txCalls.push(strings.join("?") + " | " + values.join(","));
      return Promise.resolve([{ ok: true }]);
    });
    mockSqlInstance.begin.mockImplementation((fn: (sql: unknown) => unknown) => fn(txSql));

    const result = await withTenant("tenant-uuid-001", (sql) => sql`SELECT 1`);

    expect(result).toEqual([{ ok: true }]);
    expect(txCalls[0]).toContain("set_config('app.current_tenant_id'");
    expect(txCalls[0]).toContain("tenant-uuid-001");
    expect(txCalls[1]).toContain("SELECT 1");
  });
});

describe("getScopedDb", () => {
  it("returns the tenant from a valid signed session", async () => {
    mockCookieValue = await createSessionToken({
      userId: "u1",
      email: "a@b.com",
      name: "A",
      role: "admin",
      tenantId: "tenant-uuid-001",
      tenantSlug: "refinery",
    });
    const { db, tenantId, session } = await getScopedDb();
    expect(db).toBeDefined();
    expect(tenantId).toBe("tenant-uuid-001");
    expect(session.userId).toBe("u1");
  });

  it("throws UnauthorizedError without a session", async () => {
    await expect(getScopedDb()).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("throws UnauthorizedError for a forged unsigned session", async () => {
    mockCookieValue = JSON.stringify({ tenantId: "victim", tenantSlug: "victim", userId: "u" });
    await expect(getScopedDb()).rejects.toBeInstanceOf(UnauthorizedError);
  });
});
