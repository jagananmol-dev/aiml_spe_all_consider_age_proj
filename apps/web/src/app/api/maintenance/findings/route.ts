import { NextResponse } from "next/server";
import { getSession } from "@/lib/db";
import { intelligenceFetch } from "@/lib/intelligence";

/**
 * GET /api/maintenance/findings
 *
 * What the session tenant's uploaded documents say about each asset (issues,
 * actions, values, with source documents), read from the knowledge graph.
 * Nothing is seeded: a new upload shows up here once it is indexed.
 */
export async function GET() {
  try {
    const session = await getSession();
    if (!session) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }

    const response = await intelligenceFetch("/graph/findings", session.tenantId, {});
    if (!response.ok) {
      console.error("Maintenance findings failed:", response.status, await response.text());
      return NextResponse.json(
        { error: "Could not load findings from your documents" },
        { status: 502 }
      );
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    console.error("Maintenance findings failed:", error);
    return NextResponse.json(
      { error: "The knowledge graph service is not running" },
      { status: 503 }
    );
  }
}
