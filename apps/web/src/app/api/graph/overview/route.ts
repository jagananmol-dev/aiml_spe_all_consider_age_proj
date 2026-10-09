import { NextResponse } from "next/server";
import { getSession } from "@/lib/db";
import { intelligenceFetch } from "@/lib/intelligence";

/**
 * GET /api/graph/overview
 *
 * The whole knowledge graph of the session's tenant (nodes and edges with
 * their source documents), for the Knowledge Graph view.
 */
export async function GET() {
  try {
    const session = await getSession();
    if (!session) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const response = await intelligenceFetch("/graph/overview", session.tenantId, {});
    if (!response.ok) {
      console.error("Graph overview failed:", response.status, await response.text());
      return NextResponse.json({ error: "Could not load the knowledge graph" }, { status: 502 });
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    console.error("Graph overview failed:", error);
    return NextResponse.json({ error: "The knowledge graph service is not running" }, { status: 503 });
  }
}
