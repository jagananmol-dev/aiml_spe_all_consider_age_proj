import { NextRequest, NextResponse } from "next/server";
import { getSession } from "@/lib/db";
import { intelligenceFetch } from "@/lib/intelligence";

/**
 * POST /api/graph/search
 *
 * Proxies a knowledge-graph search to the Intelligence Service, scoped to
 * the tenant of the verified session.
 */
export async function POST(request: NextRequest) {
  try {
    const session = await getSession();
    if (!session) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const { entity_value, entity_type, max_hops } = await request.json();
    if (!entity_value || typeof entity_value !== "string") {
      return NextResponse.json({ error: "entity_value is required" }, { status: 400 });
    }

    const response = await intelligenceFetch("/graph/search", session.tenantId, {
      entity_value: entity_value.trim(),
      entity_type: typeof entity_type === "string" ? entity_type : null,
      max_hops: Number.isInteger(max_hops) ? max_hops : 2,
    });

    if (!response.ok) {
      console.error("Graph search failed:", await response.text());
      return NextResponse.json({ error: "Graph search failed" }, { status: 502 });
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    console.error("Graph search failed:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
