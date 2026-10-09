/**
 * VEDA AI — Document upload route + format rules
 *
 * - checkUploadFormat: extension decides format, MIME must agree, card must match
 * - POST: 401 without session, 400 for bad format / mismatched card / empty file,
 *         201 on success with the format name as document type,
 *         503 when storage or the processing queue is down
 * - GET:  lists only the session tenant's documents
 */

import { NextRequest } from "next/server";
import { checkUploadFormat, UPLOAD_FORMATS } from "@/lib/formats";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());

const mockMinio = {
  bucketExists: jest.fn(),
  makeBucket: jest.fn(),
  putObject: jest.fn(),
};
jest.mock("minio", () => ({ Client: jest.fn(() => mockMinio) }));

const mockPublish = jest.fn();
jest.mock("@/lib/kafka", () => ({
  KAFKA_TOPICS: { DOCUMENT_UPLOADED: "veda.documents.uploaded" },
  publishEvent: (...args: unknown[]) => mockPublish(...args),
}));

import { GET, POST } from "@/app/api/documents/upload/route";
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

function uploadRequest(file: File | null, format?: string): NextRequest {
  const form = new FormData();
  if (file) form.append("file", file);
  if (format) form.append("format", format);
  return new NextRequest("http://localhost/api/documents/upload", { method: "POST", body: form });
}

const pdf = () => new File(["%PDF-1.7 content"], "statement.pdf", { type: "application/pdf" });

beforeEach(() => {
  mockDbState.reset();
  mockMinio.bucketExists.mockReset().mockResolvedValue(true);
  mockMinio.makeBucket.mockReset();
  mockMinio.putObject.mockReset().mockResolvedValue({});
  mockPublish.mockReset().mockResolvedValue(undefined);
});

describe("checkUploadFormat", () => {
  it("lists nine supported formats", () => {
    expect(UPLOAD_FORMATS.map((f) => f.name)).toEqual([
      "PDF",
      "Word",
      "Excel",
      "PowerPoint",
      "CSV",
      "JSON",
      "Plain Text",
      "Markdown",
      "Image (OCR)",
    ]);
  });

  it.each([
    ["data.json", "application/json", "json"],
    ["data.jsonl", "", "json"],
    ["notes.md", "", "markdown"],
    ["scan.JPG", "image/jpeg", "image"],
    ["export.csv", "application/vnd.ms-excel", "csv"],
  ])("accepts %s (%s) as %s", (name, mime, id) => {
    const result = checkUploadFormat(name, mime);
    expect(result.ok && result.format.id).toBe(id);
  });

  it.each([
    ["old.doc", "application/msword"],
    ["sheet.xls", "application/vnd.ms-excel"],
    ["app.exe", "application/octet-stream"],
    ["noextension", ""],
  ])("rejects unsupported %s", (name, mime) => {
    expect(checkUploadFormat(name, mime).ok).toBe(false);
  });

  it("rejects a MIME type that contradicts the extension", () => {
    expect(checkUploadFormat("invoice.pdf", "image/png").ok).toBe(false);
  });

  it("rejects a file uploaded from the wrong format card", () => {
    const result = checkUploadFormat("data.csv", "text/csv", "json");
    expect(result.ok).toBe(false);
  });
});

describe("POST /api/documents/upload", () => {
  it("returns 401 without a session and stores nothing", async () => {
    mockDbState.authenticated = false;
    const res = await POST(uploadRequest(pdf(), "pdf"));
    expect(res.status).toBe(401);
    expect(mockMinio.putObject).not.toHaveBeenCalled();
  });

  it("rejects unsupported files with 400", async () => {
    const file = new File(["MZ"], "tool.exe", { type: "application/octet-stream" });
    expect((await POST(uploadRequest(file))).status).toBe(400);
  });

  it("rejects a file that doesn't match its format card", async () => {
    const res = await POST(uploadRequest(pdf(), "excel"));
    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain("PDF");
  });

  it("rejects empty files", async () => {
    const empty = new File([], "empty.txt", { type: "text/plain" });
    expect((await POST(uploadRequest(empty, "text"))).status).toBe(400);
  });

  it("stores, records, and queues a valid upload for the session tenant", async () => {
    const res = await POST(uploadRequest(pdf(), "pdf"));
    expect(res.status).toBe(201);
    expect((await res.json()).document.documentType).toBe("PDF");

    const [bucket] = mockMinio.putObject.mock.calls[0];
    expect(bucket).toBe(`veda-tenant-${TEST_SESSION.tenantSlug}`);

    const insert = mockDbState.queries.find((q) => q.text.includes("INSERT INTO documents"))!;
    expect(insert.values).toContain(TEST_SESSION.tenantId);
    expect(insert.values).toContain("PDF");

    const [, event] = mockPublish.mock.calls[0];
    expect(event).toMatchObject({ tenantId: TEST_SESSION.tenantId, fileType: "pdf" });
  });

  it("sanitizes path segments out of the stored file name", async () => {
    const sneaky = new File(["x"], "../../etc/report.txt", { type: "text/plain" });
    await POST(uploadRequest(sneaky, "text"));
    const [, storagePath] = mockMinio.putObject.mock.calls[0];
    expect(storagePath).not.toContain("..");
    expect(storagePath).toMatch(/_report\.txt$/);
  });

  it("returns 503 when file storage is down", async () => {
    mockMinio.bucketExists.mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await POST(uploadRequest(pdf(), "pdf"));
    expect(res.status).toBe(503);
    expect(mockDbState.queries).toHaveLength(0);
  });

  it("marks the document failed and returns 503 when the queue is down", async () => {
    mockPublish.mockRejectedValue(new Error("broker down"));
    const res = await POST(uploadRequest(pdf(), "pdf"));
    expect(res.status).toBe(503);
    const update = mockDbState.queries.find((q) => q.text.includes("status = 'failed'"));
    expect(update).toBeDefined();
  });
});

describe("GET /api/documents/upload", () => {
  it("lists only the session tenant's documents", async () => {
    mockDbState.result = [
      {
        id: "doc-1",
        title: "statement.pdf",
        file_name: "statement.pdf",
        file_type: "pdf",
        file_size: "2048",
        status: "failed",
        parsing_status: "failed",
        embedding_status: "pending",
        document_type: "PDF",
        created_at: "2026-10-08T10:00:00Z",
        updated_at: "2026-10-08T10:01:00Z",
        page_count: null,
        word_count: null,
        error: "No readable text found in this file",
        uploaded_by_name: "Admin",
      },
    ];
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.documents[0]).toMatchObject({
      fileSize: 2048,
      status: "failed",
      error: "No readable text found in this file",
      uploadedBy: "Admin",
    });
    expect(mockDbState.tenantScopes).toEqual([TEST_SESSION.tenantId]);
    expect(mockDbState.queries[0].values).toEqual([TEST_SESSION.tenantId]);
  });

  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await GET()).status).toBe(401);
  });
});

describe("POST /api/documents/upload — local storage mode", () => {
  const fs = require("fs");
  const os = require("os");
  const path = require("path");
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "veda-upload-"));
    process.env.STORAGE_BACKEND = "local";
    process.env.LOCAL_STORAGE_DIR = dir;
  });

  afterEach(() => {
    delete process.env.STORAGE_BACKEND;
    delete process.env.LOCAL_STORAGE_DIR;
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("writes the file under the tenant folder and skips MinIO and Kafka", async () => {
    const file = new File(["name,amount\nRent,100\n"], "ledger.csv", { type: "text/csv" });
    const res = await POST(uploadRequest(file, "csv"));
    expect(res.status).toBe(201);
    expect(mockMinio.putObject).not.toHaveBeenCalled();
    expect(mockPublish).not.toHaveBeenCalled();

    const insert = mockDbState.queries.find((q) => q.text.includes("INSERT INTO documents"))!;
    expect(insert.values).toContain("local");
    const storagePath = insert.values.find(
      (v) => typeof v === "string" && v.startsWith(`${TEST_SESSION.tenantId}/`)
    ) as string;
    expect(storagePath).toMatch(/_ledger\.csv$/);
    expect(fs.readFileSync(path.join(dir, storagePath), "utf8")).toBe("name,amount\nRent,100\n");
  });
});
