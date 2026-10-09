/**
 * VEDA AI — Graph overview route tests
 *
 * - 401 without a session
 * - asks the intelligence service for the session tenant's graph only
 * - 502 when the service errors, 503 when it is unreachable
 */

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());

const mockIntelligence = jest.fn();
jest.mock("@/lib/intelligence", () => ({
  intelligenceFetch: (...args: unknown[]) => mockIntelligence(...args),
}));

import { GET } from "@/app/api/graph/overview/route";
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

const GRAPH = {
  nodes: [
    { id: "n1", label: "HD-K04", type: "EQUIPMENT_TAG", degree: 1 },
    { id: "n2", label: "conductivity alarm", type: "FAILURE_MODE", degree: 1 },
  ],
  edges: [
    {
      source: "n1",
      target: "n2",
      relationship: "FAILED_WITH",
      confidence: 0.9,
      documents: ["log.csv"],
    },
  ],
};

beforeEach(() => {
  mockDbState.reset();
  mockIntelligence.mockReset();
});

describe("GET /api/graph/overview", () => {
  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await GET()).status).toBe(401);
    expect(mockIntelligence).not.toHaveBeenCalled();
  });

  it("returns the session tenant's graph", async () => {
    mockIntelligence.mockResolvedValue(new Response(JSON.stringify(GRAPH), { status: 200 }));
    const res = await GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(GRAPH);
    const [path, tenantId] = mockIntelligence.mock.calls[0];
    expect(path).toBe("/graph/overview");
    expect(tenantId).toBe(TEST_SESSION.tenantId);
  });

  it("returns 502 when the service fails", async () => {
    mockIntelligence.mockResolvedValue(new Response("boom", { status: 500 }));
    expect((await GET()).status).toBe(502);
  });

  it("returns 503 when the service is unreachable", async () => {
    mockIntelligence.mockRejectedValue(new TypeError("fetch failed"));
    expect((await GET()).status).toBe(503);
  });
});
