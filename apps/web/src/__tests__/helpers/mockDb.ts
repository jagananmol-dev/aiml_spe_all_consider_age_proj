/**
 * Shared mock for "@/lib/db" used by API route tests.
 *
 * Usage in a test file:
 *   jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
 *   import { mockDbState } from "../../helpers/mockDb";
 */

export class UnauthorizedError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export const TEST_SESSION = {
  userId: "user-uuid-001",
  email: "admin@refinery.com",
  name: "Admin",
  role: "admin",
  tenantId: "tenant-uuid-001",
  tenantSlug: "refinery",
  exp: Math.floor(Date.now() / 1000) + 3600,
};

/** Mutable state the tests configure per case. */
export const mockDbState = {
  /** Rows returned by every tagged-template query, or an Error to reject with */
  result: [] as Record<string, unknown>[] | Error,
  /** When false, getScopedDb throws UnauthorizedError */
  authenticated: true,
  /** Captured queries: { text, values } */
  queries: [] as { text: string; values: unknown[] }[],
  /** Tenant ids passed to withTenant */
  tenantScopes: [] as string[],
  reset() {
    this.result = [];
    this.authenticated = true;
    this.queries = [];
    this.tenantScopes = [];
  },
};

function mockSql(strings: TemplateStringsArray, ...values: unknown[]) {
  mockDbState.queries.push({ text: strings.join("?"), values });
  const { result } = mockDbState;
  return result instanceof Error ? Promise.reject(result) : Promise.resolve(result);
}

export function dbMockModule() {
  return {
    UnauthorizedError,
    getScopedDb: jest.fn(async () => {
      if (!mockDbState.authenticated) throw new UnauthorizedError();
      return { db: {}, tenantId: TEST_SESSION.tenantId, session: TEST_SESSION };
    }),
    getSession: jest.fn(async () => (mockDbState.authenticated ? TEST_SESSION : null)),
    withTenant: jest.fn(async (tenantId: string, fn: (sql: typeof mockSql) => unknown) => {
      mockDbState.tenantScopes.push(tenantId);
      return fn(mockSql);
    }),
  };
}
