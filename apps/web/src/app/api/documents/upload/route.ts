import { NextRequest, NextResponse } from "next/server";
import { publishEvent, KAFKA_TOPICS } from "@/lib/kafka";
import type { DocumentUploadedEvent } from "@/lib/kafka";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";
import { checkUploadFormat, MAX_UPLOAD_BYTES } from "@/lib/formats";
import { isLocalStorage, LOCAL_BUCKET, saveLocalFile } from "@/lib/storage";
import { getMinioClient } from "@/lib/minio";

/**
 * POST /api/documents/upload
 *
 * Handles document uploads:
 * 1. Validates file format (see lib/formats.ts) and size
 * 2. Uploads to MinIO (tenant-scoped bucket)
 * 3. Creates document record in PostgreSQL
 * 4. Publishes upload event to Kafka → triggers ingestion pipeline
 */

export async function POST(request: NextRequest) {
  try {
    // Authenticate first — nothing is stored before the session is verified
    let session;
    try {
      ({ session } = await getScopedDb());
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        return NextResponse.json({ error: "Authentication required" }, { status: 401 });
      }
      throw error;
    }
    const { tenantId, tenantSlug, userId: uploadedBy } = session;

    // Parse multipart form data
    const formData = await request.formData();
    const file = formData.get("file") as File | null;

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    // Validate format — extension decides the format, MIME must agree,
    // and it must match the format card it was uploaded from (if given)
    const requestedFormat = formData.get("format");
    const check = checkUploadFormat(
      file.name,
      file.type,
      typeof requestedFormat === "string" ? requestedFormat : null
    );
    if (!check.ok) {
      return NextResponse.json({ error: check.error }, { status: 400 });
    }
    const { format, extension: fileExtension } = check;
    const mimeType = file.type || "application/octet-stream";

    // Validate file size
    if (file.size > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: `File too large. Maximum size: ${MAX_UPLOAD_BYTES / 1024 / 1024}MB` },
        { status: 400 }
      );
    }
    if (file.size === 0) {
      return NextResponse.json({ error: "File is empty" }, { status: 400 });
    }

    // Generate document ID and storage path (sanitized name — no path segments)
    const documentId = crypto.randomUUID();
    const safeName = sanitizeFileName(file.name);
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const local = isLocalStorage();
    const storageBucket = local ? LOCAL_BUCKET : `veda-tenant-${tenantSlug}`;
    const storagePath = local
      ? `${tenantId}/${timestamp}_${documentId}_${safeName}`
      : `documents/${timestamp}_${documentId}_${safeName}`;

    // Store the file: local disk (single-machine mode) or the tenant's MinIO bucket
    try {
      const fileBuffer = Buffer.from(await file.arrayBuffer());
      if (local) {
        await saveLocalFile(storagePath, fileBuffer);
      } else {
        const minio = getMinioClient();
        if (!(await minio.bucketExists(storageBucket))) {
          await minio.makeBucket(storageBucket);
        }
        await minio.putObject(storageBucket, storagePath, fileBuffer, file.size, {
          "Content-Type": mimeType,
          "x-amz-meta-tenant-id": tenantId,
          "x-amz-meta-document-id": documentId,
          "x-amz-meta-original-name": encodeURIComponent(file.name),
        });
      }
    } catch (error) {
      console.error("File storage failed:", error);
      return NextResponse.json(
        { error: "File storage is unavailable. Please try again later." },
        { status: 503 }
      );
    }

    // The document type shown to users is the upload format's name
    const documentType = format.name;

    // Create document record in PostgreSQL
    await withTenant(tenantId, async (sql) => {
      await sql`
        INSERT INTO documents (
          id, tenant_id, uploaded_by, title, file_name, file_type,
          file_size, mime_type, storage_path, storage_bucket, status,
          parsing_status, extraction_status, embedding_status, document_type
        ) VALUES (
          ${documentId}, ${tenantId}, ${uploadedBy}, ${file.name}, ${safeName},
          ${fileExtension}, ${file.size}, ${mimeType}, ${storagePath}, ${storageBucket},
          'uploaded', 'pending', 'pending', 'pending', ${documentType}
        )
      `;
    });

    // Local mode: the local worker polls for status = 'uploaded'; no queue needed.
    // Otherwise publish to Kafka → triggers the ingestion pipeline.
    if (!local) {
      // Publish upload event to Kafka → triggers ingestion pipeline
      const uploadEvent: DocumentUploadedEvent = {
        tenantId,
        documentId,
        fileName: safeName,
        fileType: fileExtension,
        storagePath,
        storageBucket,
        uploadedBy,
        timestamp: new Date().toISOString(),
      };

      try {
        await publishEvent(
          KAFKA_TOPICS.DOCUMENT_UPLOADED,
          uploadEvent as unknown as Record<string, unknown>,
          documentId
        );
      } catch (error) {
        // The file is stored but processing can't start — record that instead
        // of leaving the document stuck in "uploaded"
        console.error("Failed to queue document for processing:", error);
        const reason = "Processing queue unavailable; the file was stored but not processed.";
        await withTenant(tenantId, async (sql) => {
          await sql`
            UPDATE documents
            SET status = 'failed',
                metadata = COALESCE(metadata, '{}'::jsonb) || ${JSON.stringify({ error: reason })}::jsonb,
                updated_at = NOW()
            WHERE id = ${documentId} AND tenant_id = ${tenantId}
          `;
        });
        return NextResponse.json({ error: reason }, { status: 503 });
      }
    }

    return NextResponse.json(
      {
        success: true,
        document: {
          id: documentId,
          fileName: file.name,
          fileType: fileExtension,
          fileSize: file.size,
          documentType,
          status: "uploaded",
          message: "Document uploaded successfully. Processing will begin shortly.",
        },
      },
      { status: 201 }
    );
  } catch (error) {
    console.error("Document upload failed:", error);
    return NextResponse.json({ error: "Internal server error during upload" }, { status: 500 });
  }
}

/**
 * Reduce a client-supplied file name to a safe single path segment.
 */
function sanitizeFileName(name: string): string {
  const base = name.split(/[\\/]/).pop() || "file";
  const cleaned = base.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "");
  return (cleaned || "file").slice(0, 200);
}

/**
 * GET /api/documents/upload
 *
 * Lists the current company's uploads, newest first. Only documents of the
 * session's tenant are returned.
 */
export async function GET() {
  try {
    const { tenantId } = await getScopedDb();

    const documents = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT d.id, d.title, d.file_name, d.file_type, d.file_size, d.status,
               d.parsing_status, d.embedding_status, d.document_type, d.created_at,
               d.updated_at, d.page_count, d.word_count,
               d.metadata->>'error' AS error,
               u.name AS uploaded_by_name
        FROM documents d
        LEFT JOIN users u ON u.id = d.uploaded_by AND u.tenant_id = d.tenant_id
        WHERE d.tenant_id = ${tenantId}
        ORDER BY d.created_at DESC
        LIMIT 500
      `
    );

    return NextResponse.json({
      documents: documents.map((doc) => ({
        id: doc.id,
        title: doc.title,
        fileName: doc.file_name,
        fileType: doc.file_type,
        fileSize: Number(doc.file_size),
        status: doc.status,
        parsingStatus: doc.parsing_status,
        embeddingStatus: doc.embedding_status,
        documentType: doc.document_type || "Document",
        createdAt: doc.created_at,
        updatedAt: doc.updated_at,
        pageCount: doc.page_count,
        wordCount: doc.word_count,
        error: doc.error,
        uploadedBy: doc.uploaded_by_name,
      })),
      total: documents.length,
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to list documents:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
