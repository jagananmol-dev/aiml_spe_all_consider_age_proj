/**
 * VEDA AI — Supported Upload Formats
 *
 * Single source of truth for which file formats a company can upload.
 * Used by the upload page (one card per format) and the upload API
 * (server-side validation). Every format listed here has a parser in the
 * ingestion service (services/ingestion/src/workers/ingestion_worker.py);
 * keep the two in sync.
 */

export interface UploadFormat {
  /** Stable id sent with the upload */
  id: string;
  /** Display name */
  name: string;
  /** Short description shown on the card */
  description: string;
  /** Accepted file extensions, lowercase, without the dot */
  extensions: string[];
  /** MIME types browsers report for these files ("" = unknown, allowed) */
  mimeTypes: string[];
}

export const UPLOAD_FORMATS: UploadFormat[] = [
  {
    id: "pdf",
    name: "PDF",
    description: "Reports, manuals, statements, scanned or digital PDFs",
    extensions: ["pdf"],
    mimeTypes: ["application/pdf"],
  },
  {
    id: "word",
    name: "Word",
    description: "Word documents (.docx) including tables",
    extensions: ["docx"],
    mimeTypes: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  },
  {
    id: "excel",
    name: "Excel",
    description: "Spreadsheets (.xlsx), every sheet is indexed",
    extensions: ["xlsx"],
    mimeTypes: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
  },
  {
    id: "powerpoint",
    name: "PowerPoint",
    description: "Presentations (.pptx), slide text and notes",
    extensions: ["pptx"],
    mimeTypes: ["application/vnd.openxmlformats-officedocument.presentationml.presentation"],
  },
  {
    id: "csv",
    name: "CSV",
    description: "Tabular data exports, one row per record",
    extensions: ["csv"],
    mimeTypes: ["text/csv", "application/vnd.ms-excel", "text/plain"],
  },
  {
    id: "json",
    name: "JSON",
    description: "Structured data (.json) or JSON Lines (.jsonl)",
    extensions: ["json", "jsonl"],
    mimeTypes: ["application/json", "application/x-ndjson", "text/plain"],
  },
  {
    id: "text",
    name: "Plain Text",
    description: "Notes, logs, and other .txt files",
    extensions: ["txt"],
    mimeTypes: ["text/plain"],
  },
  {
    id: "markdown",
    name: "Markdown",
    description: "Markdown documents (.md)",
    extensions: ["md", "markdown"],
    mimeTypes: ["text/markdown", "text/x-markdown", "text/plain"],
  },
  {
    id: "image",
    name: "Image (OCR)",
    description: "Scans and photos; text is read with OCR",
    extensions: ["png", "jpg", "jpeg", "tif", "tiff", "bmp"],
    mimeTypes: ["image/png", "image/jpeg", "image/tiff", "image/bmp"],
  },
];

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100 MB

export function getFileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot === -1 ? "" : fileName.slice(dot + 1).toLowerCase();
}

/** Find the format a file belongs to by its extension. */
export function findFormatForFile(fileName: string): UploadFormat | undefined {
  const ext = getFileExtension(fileName);
  return UPLOAD_FORMATS.find((f) => f.extensions.includes(ext));
}

export type FormatCheck =
  { ok: true; format: UploadFormat; extension: string } | { ok: false; error: string };

/**
 * Validate a file against the supported formats. The extension decides the
 * format; the MIME type must be consistent with it (or unknown, since some
 * browsers report "" or a generic type for .md/.jsonl files).
 * When `expectedFormatId` is given, the file must belong to that format.
 */
export function checkUploadFormat(
  fileName: string,
  mimeType: string,
  expectedFormatId?: string | null
): FormatCheck {
  const extension = getFileExtension(fileName);
  const format = findFormatForFile(fileName);

  if (!format) {
    return {
      ok: false,
      error: `Unsupported file type ".${extension || "?"}". Supported: ${UPLOAD_FORMATS.flatMap(
        (f) => f.extensions
      )
        .map((e) => `.${e}`)
        .join(", ")}`,
    };
  }

  if (expectedFormatId && format.id !== expectedFormatId) {
    const expected = UPLOAD_FORMATS.find((f) => f.id === expectedFormatId);
    return {
      ok: false,
      error: `This file is ${format.name}, but it was uploaded as ${expected?.name ?? expectedFormatId}`,
    };
  }

  const genericMime = mimeType === "" || mimeType === "application/octet-stream";
  if (!genericMime && !format.mimeTypes.includes(mimeType)) {
    return {
      ok: false,
      error: `File content type "${mimeType}" does not match a ${format.name} file`,
    };
  }

  return { ok: true, format, extension };
}

const TEXT_CONTENT_TYPES: Record<string, string> = {
  csv: "text/csv",
  json: "application/json",
  jsonl: "application/x-ndjson",
  txt: "text/plain",
  md: "text/markdown",
  markdown: "text/markdown",
};

/** Content-Type to serve a stored file with (text formats as UTF-8). */
export function contentTypeFor(fileName: string): string {
  const ext = getFileExtension(fileName);
  if (TEXT_CONTENT_TYPES[ext]) return `${TEXT_CONTENT_TYPES[ext]}; charset=utf-8`;
  return findFormatForFile(fileName)?.mimeTypes[0] || "application/octet-stream";
}

/** How the document viewer shows a file of this name. */
export type ViewerKind = "pdf" | "image" | "csv" | "json" | "jsonl" | "markdown" | "text" | "office";

export function viewerKindFor(fileName: string): ViewerKind {
  const ext = getFileExtension(fileName);
  if (ext === "pdf") return "pdf";
  if (ext === "csv") return "csv";
  if (ext === "json") return "json";
  if (ext === "jsonl") return "jsonl";
  if (ext === "md" || ext === "markdown") return "markdown";
  if (ext === "txt") return "text";
  if (["docx", "xlsx", "pptx"].includes(ext)) return "office";
  return findFormatForFile(fileName)?.id === "image" ? "image" : "text";
}
