import { NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";
import { getMinioClient } from "@/lib/minio";
import { deleteLocalFile, LOCAL_BUCKET } from "@/lib/storage";

/**
 * DELETE /api/documents/:id
 *
 * Removes one of the session tenant's documents: the database row (its
 * passages, preview and knowledge-graph edges go with it through ON DELETE
 * CASCADE, so search and chat stop using it at once) and the stored file.
 * Needed when a wrong file was uploaded or a patient asks for erasure.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const { tenantId } = await getScopedDb();
    if (!UUID.test(id)) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    const [doc] = await withTenant(
      tenantId,
      (sql) => sql`
        DELETE FROM documents
        WHERE id = ${id} AND tenant_id = ${tenantId}
        RETURNING storage_bucket, storage_path, title
      `
    );
    if (!doc) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    // The row is gone, so the document is no longer used anywhere; a file
    // that cannot be removed is logged for clean-up rather than failing
    try {
      if (doc.storage_bucket === LOCAL_BUCKET) {
        await deleteLocalFile(doc.storage_path);
      } else {
        await getMinioClient().removeObject(doc.storage_bucket, doc.storage_path);
      }
    } catch (error) {
      console.error(`Stored file of deleted document ${id} was not removed:`, error);
    }

    return NextResponse.json({ success: true, deleted: { id, title: doc.title } });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    if ((error as { code?: string })?.code === "23503") {
      return NextResponse.json(
        { error: "Other records still refer to this document; remove them first." },
        { status: 409 }
      );
    }
    console.error("Failed to delete document:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
