import { NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";
import { contentTypeFor } from "@/lib/formats";
import { getMinioClient } from "@/lib/minio";
import { LOCAL_BUCKET, readLocalFile } from "@/lib/storage";

/**
 * GET /api/documents/:id/file
 *
 * Streams the original uploaded file so the upload page can show it
 * (PDFs inline, text formats as text). Only documents of the session's
 * tenant are served.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
async function readStream(stream: NodeJS.ReadableStream): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk as Buffer));
  return Buffer.concat(chunks);
}

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const { tenantId } = await getScopedDb();
    if (!UUID.test(id)) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    const [doc] = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT title, storage_bucket, storage_path
        FROM documents
        WHERE id = ${id} AND tenant_id = ${tenantId}
        LIMIT 1
      `
    );
    if (!doc) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    let data: Buffer;
    try {
      data =
        doc.storage_bucket === LOCAL_BUCKET
          ? await readLocalFile(doc.storage_path)
          : await readStream(await getMinioClient().getObject(doc.storage_bucket, doc.storage_path));
    } catch (error) {
      console.error("Stored file unavailable:", error);
      return NextResponse.json({ error: "The stored file is not available" }, { status: 404 });
    }

    const title = String(doc.title);
    return new Response(new Uint8Array(data), {
      headers: {
        "Content-Type": contentTypeFor(title),
        "Content-Length": String(data.length),
        "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(title)}`,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to serve document:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
