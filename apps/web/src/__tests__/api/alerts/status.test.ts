/**
 * VEDA AI — Alerts Status Route Tests
 *
 * GET:  200 + alerts (camelCase), empty array, 401 without session, 500 on DB error
 * POST: 201 + alert, defaults for optional fields, 400 without title, 500 on DB error
 * All queries run inside withTenant() scoped to the session's tenant.
 */

import { GET, POST } from "@/app/api/alerts/status/route";
import { NextRequest } from "next/server";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

function makePostRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/alerts/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const MOCK_ALERT = {
  id: "alert-uuid-001",
  title: "High Temperature Alert",
  description: "PUMP-101 temperature exceeded threshold",
  severity: "high",
  category: "equipment",
  equipment_tag: "PUMP-101",
  status: "open",
  created_at: "2026-07-09T10:00:00+00:00",
};

beforeEach(() => mockDbState.reset());

describe("GET /api/alerts/status", () => {
  it("returns 200 with camelCase alerts", async () => {
    mockDbState.result = [MOCK_ALERT];
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.success).toBe(true);
    expect(body.alerts[0]).toMatchObject({
      id: "alert-uuid-001",
      equipmentTag: "PUMP-101",
      createdAt: MOCK_ALERT.created_at,
    });
  });

  it("returns empty array when no alerts", async () => {
    const body = await (await GET()).json();
    expect(body.alerts).toEqual([]);
  });

  it("scopes the query to the session tenant", async () => {
    await GET();
    expect(mockDbState.tenantScopes).toEqual([TEST_SESSION.tenantId]);
    expect(mockDbState.queries[0].values).toContain(TEST_SESSION.tenantId);
  });

  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await GET()).status).toBe(401);
  });

  it("returns 500 on DB error", async () => {
    mockDbState.result = new Error("DB down");
    expect((await GET()).status).toBe(500);
  });
});

describe("POST /api/alerts/status", () => {
  it("returns 201 with the created alert", async () => {
    mockDbState.result = [{ id: "alert-new", title: "Leak", severity: "high", status: "open" }];
    const res = await POST(makePostRequest({ title: "Leak", severity: "high" }));
    expect(res.status).toBe(201);
    expect((await res.json()).alert.id).toBe("alert-new");
  });

  it("uses defaults for optional fields", async () => {
    mockDbState.result = [{ id: "a" }];
    await POST(makePostRequest({ title: "Minimal" }));
    const { values } = mockDbState.queries[0];
    expect(values).toEqual([TEST_SESSION.tenantId, "Minimal", "", "info", "general", ""]);
  });

  it("returns 400 without title", async () => {
    expect((await POST(makePostRequest({}))).status).toBe(400);
  });

  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await POST(makePostRequest({ title: "x" }))).status).toBe(401);
  });

  it("returns 500 on DB error", async () => {
    mockDbState.result = new Error("DB down");
    expect((await POST(makePostRequest({ title: "x" }))).status).toBe(500);
  });
});
