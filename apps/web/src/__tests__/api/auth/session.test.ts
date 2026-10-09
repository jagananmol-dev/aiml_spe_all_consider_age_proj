/**
 * VEDA AI — Auth Session Route Tests
 *
 * Tests GET /api/auth/session
 * - No cookie → authenticated:false
 * - Valid signed cookie → authenticated:true with session data (no exp)
 * - Forged unsigned JSON cookie → authenticated:false
 */

import { createSessionToken } from "@/lib/session";

let mockCookieValue: string | undefined;

jest.mock("next/headers", () => ({
  cookies: jest.fn(async () => ({
    get: (name: string) =>
      name === "veda-session" && mockCookieValue !== undefined
        ? { value: mockCookieValue }
        : undefined,
  })),
}));
jest.mock("postgres", () => jest.fn(() => jest.fn()));
jest.mock("drizzle-orm/postgres-js", () => ({ drizzle: jest.fn(() => ({})) }));

import { GET } from "@/app/api/auth/session/route";

const SESSION_DATA = {
  userId: "user-uuid-001",
  email: "admin@refinery.com",
  name: "Admin User",
  role: "admin",
  tenantId: "tenant-uuid-001",
  tenantSlug: "refinery",
};

beforeEach(() => {
  mockCookieValue = undefined;
});

describe("GET /api/auth/session", () => {
  it("returns authenticated:false without a cookie", async () => {
    const res = await GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ authenticated: false, session: null });
  });

  it("returns the session for a valid signed cookie", async () => {
    mockCookieValue = await createSessionToken(SESSION_DATA);
    const body = await (await GET()).json();
    expect(body.authenticated).toBe(true);
    expect(body.session).toEqual(SESSION_DATA);
  });

  it("rejects a forged unsigned JSON cookie", async () => {
    mockCookieValue = JSON.stringify({ ...SESSION_DATA, role: "admin", tenantId: "victim" });
    const body = await (await GET()).json();
    expect(body.authenticated).toBe(false);
  });
});
