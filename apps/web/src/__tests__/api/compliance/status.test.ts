/**
 * VEDA AI — Compliance Status Route Tests
 *
 * GET:  200 + rules (camelCase), empty array, 401 without session, 500 on DB error
 * POST: 200 on update, 404 when rule missing / other tenant, 400 on missing fields
 */

import { GET, POST } from "@/app/api/compliance/status/route";
import { NextRequest } from "next/server";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

function makePostRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/compliance/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const MOCK_RULE = {
  id: "rule-001",
  regulation_name: "OISD-154",
  regulation_version: "2024",
  section_reference: "4.2",
  requirement_text: "Inspect relief valves annually",
  requirement_type: "mandatory",
  compliance_status: "compliant",
  notes: null,
};

beforeEach(() => mockDbState.reset());

describe("GET /api/compliance/status", () => {
  it("returns 200 with camelCase rules", async () => {
    mockDbState.result = [MOCK_RULE];
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.rules[0]).toMatchObject({
      regulationName: "OISD-154",
      sectionReference: "4.2",
      complianceStatus: "compliant",
    });
  });

  it("returns empty rules array when none exist", async () => {
    expect((await (await GET()).json()).rules).toEqual([]);
  });

  it("filters by the session tenant", async () => {
    await GET();
    expect(mockDbState.queries[0].values).toEqual([TEST_SESSION.tenantId]);
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

describe("POST /api/compliance/status", () => {
  it("returns 200 on successful update", async () => {
    mockDbState.result = [{ id: "rule-001", compliance_status: "gaps", notes: "" }];
    const res = await POST(
      makePostRequest({ ruleId: "11111111-1111-4111-8111-111111111111", complianceStatus: "gaps" })
    );
    expect(res.status).toBe(200);
    expect(mockDbState.queries[0].values).toContain(TEST_SESSION.tenantId);
  });

  it("returns 404 when rule not found (or different tenant)", async () => {
    mockDbState.result = [];
    const res = await POST(
      makePostRequest({ ruleId: "22222222-2222-4222-8222-222222222222", complianceStatus: "gaps" })
    );
    expect(res.status).toBe(404);
  });

  it("returns 400 when fields are missing", async () => {
    expect(
      (await POST(makePostRequest({ ruleId: "11111111-1111-4111-8111-111111111111" }))).status
    ).toBe(400);
  });

  it("returns 500 on DB error", async () => {
    mockDbState.result = new Error("DB down");
    const res = await POST(
      makePostRequest({ ruleId: "11111111-1111-4111-8111-111111111111", complianceStatus: "gaps" })
    );
    expect(res.status).toBe(500);
  });
});

describe("POST /api/compliance/status — validation", () => {
  it("returns 400 (not a database error) for an id that is not a UUID", async () => {
    const res = await POST(makePostRequest({ ruleId: "rule-001", complianceStatus: "gaps" }));
    expect(res.status).toBe(400);
  });
});
