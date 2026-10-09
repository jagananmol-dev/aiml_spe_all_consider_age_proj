/**
 * VEDA AI — Maintenance Orders Route Tests
 *
 * GET:  200 + orders (camelCase), tolerances default, 401 without session, 500 on DB error
 * POST: 201 + order, tolerances serialized to JSON, 400 on missing fields
 */

import { GET, POST } from "@/app/api/maintenance/orders/route";
import { NextRequest } from "next/server";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
import { mockDbState } from "../../helpers/mockDb";

function makePostRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest("http://localhost/api/maintenance/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const MOCK_ORDER = {
  id: "order-001",
  order_number: "WO-2024-1847",
  title: "Coupling replacement",
  description: "Replace coupling on PUMP-101",
  equipment_tag: "PUMP-101",
  status: "open",
  tolerances: null,
  created_at: "2026-07-09T10:00:00+00:00",
};

beforeEach(() => mockDbState.reset());

describe("GET /api/maintenance/orders", () => {
  it("returns 200 with camelCase orders", async () => {
    mockDbState.result = [MOCK_ORDER];
    const body = await (await GET()).json();
    expect(body.orders[0]).toMatchObject({ orderNumber: "WO-2024-1847", equipmentTag: "PUMP-101" });
  });

  it("defaults tolerances to an empty object", async () => {
    mockDbState.result = [MOCK_ORDER];
    expect((await (await GET()).json()).orders[0].tolerances).toEqual({});
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

describe("POST /api/maintenance/orders", () => {
  it("returns 201 with the created order", async () => {
    mockDbState.result = [{ id: "order-new", order_number: "WO-1" }];
    const res = await POST(makePostRequest({ orderNumber: "WO-1", title: "Fix" }));
    expect(res.status).toBe(201);
    expect((await res.json()).order.id).toBe("order-new");
  });

  it("serializes tolerances to JSON and defaults to {}", async () => {
    mockDbState.result = [{ id: "o" }];
    await POST(
      makePostRequest({ orderNumber: "WO-1", title: "Fix", tolerances: { gap: "0.05mm" } })
    );
    await POST(makePostRequest({ orderNumber: "WO-2", title: "Fix" }));
    expect(mockDbState.queries[0].values).toContain(JSON.stringify({ gap: "0.05mm" }));
    expect(mockDbState.queries[1].values).toContain("{}");
  });

  it("returns 400 when fields are missing", async () => {
    expect((await POST(makePostRequest({ title: "Fix" }))).status).toBe(400);
  });

  it("returns 500 on DB error", async () => {
    mockDbState.result = new Error("DB down");
    expect((await POST(makePostRequest({ orderNumber: "WO-1", title: "Fix" }))).status).toBe(500);
  });
});
