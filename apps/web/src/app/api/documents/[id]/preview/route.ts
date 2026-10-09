import { NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";

/**
 * GET /api/documents/:id/preview
 *
 * The structured preview of a Word, Excel or PowerPoint upload (built by the
 * ingestion worker). 404 when the document has none yet.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const { tenantId } = await getScopedDb();
    if (!UUID.test(id)) {
      return NextResponse.json({ error: "Preview not found" }, { status: 404 });
    }

    const [row] = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT p.preview
        FROM document_previews p
        JOIN documents d ON d.id = p.document_id AND d.tenant_id = p.tenant_id
        WHERE p.document_id = ${id} AND p.tenant_id = ${tenantId}
        LIMIT 1
      `
    );
    if (!row) {
      return NextResponse.json(
        { error: "No preview yet. It is created when the document is processed." },
        { status: 404 }
      );
    }
    return NextResponse.json(row.preview);
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to load preview:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
