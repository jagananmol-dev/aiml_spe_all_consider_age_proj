"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Braces,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Hash,
  Presentation,
  RefreshCw,
  Table,
  Upload,
  Eye,
  type LucideIcon,
} from "lucide-react";
import {
  checkUploadFormat,
  findFormatForFile,
  MAX_UPLOAD_BYTES,
  UPLOAD_FORMATS,
  type UploadFormat,
} from "@/lib/formats";
import { DocumentViewer, type ViewerDocument } from "@/components/documents/DocumentViewer";
import styles from "./upload.module.css";

interface UploadedDocument {
  id: string;
  title: string;
  fileName: string;
  fileType: string;
  fileSize: number;
  status: string;
  documentType: string;
  createdAt: string;
  pageCount: number | null;
  wordCount: number | null;
  error: string | null;
  uploadedBy: string | null;
}

interface UploadProgress {
  key: string;
  fileName: string;
  formatName: string;
  percent: number;
  state: "uploading" | "done" | "error";
  message?: string;
}

const FORMAT_ICONS: Record<string, LucideIcon> = {
  pdf: FileText,
  word: FileType,
  excel: FileSpreadsheet,
  powerpoint: Presentation,
  csv: Table,
  json: Braces,
  text: FileText,
  markdown: Hash,
  image: FileImage,
};

const IN_PROGRESS = new Set([
  "uploaded",
  "processing",
  "parsing",
  "parsed",
  "extracting",
  "extracted",
  "embedding",
]);

function describeStatus(status: string): { label: string; className: string } {
  if (status === "indexed") return { label: "Ready", className: styles.statusReady };
  if (status === "failed") return { label: "Failed", className: styles.statusFailed };
  if (status === "uploaded") return { label: "Queued", className: styles.statusQueued };
  if (status === "archived") return { label: "Archived", className: styles.statusQueued };
  return { label: "Processing", className: styles.statusProcessing };
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

/** Upload one file with progress reporting (fetch has no upload progress). */
function uploadFile(
  file: File,
  formatId: string,
  onProgress: (percent: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("format", formatId);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents/upload");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let message = `Upload failed (${xhr.status})`;
      try {
        message = JSON.parse(xhr.responseText).error || message;
      } catch {
        // keep the generic message
      }
      reject(new Error(message));
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}

function FormatCard({
  format,
  onFiles,
}: {
  format: UploadFormat;
  onFiles: (format: UploadFormat, files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const Icon = FORMAT_ICONS[format.id] ?? FileText;
  const accept = format.extensions.map((ext) => `.${ext}`).join(",");

  return (
    <article
      className={`${styles.formatCard} ${dragging ? styles.dragging : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        onFiles(format, Array.from(e.dataTransfer.files));
      }}
    >
      <div className={styles.formatTop}>
        <div className={styles.formatIcon} aria-hidden="true">
          <Icon size={18} />
        </div>
        <h3 className={styles.formatName}>{format.name}</h3>
      </div>
      <div className={styles.extensions}>
        {format.extensions.map((ext) => (
          <span key={ext} className={styles.ext}>
            .{ext}
          </span>
        ))}
      </div>
      <p className={styles.formatDescription}>{format.description}</p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        className={styles.hiddenInput}
        aria-label={`Upload ${format.name} files`}
        onChange={(e) => {
          onFiles(format, Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className={styles.uploadButton}
        onClick={() => inputRef.current?.click()}
      >
        <Upload size={14} /> Upload {format.name}
      </button>
    </article>
  );
}

export default function UploadPage() {
  const router = useRouter();
  const [companySlug, setCompanySlug] = useState<string | null>(null);
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [progress, setProgress] = useState<UploadProgress[]>([]);
  const [formatFilter, setFormatFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [viewing, setViewing] = useState<ViewerDocument | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const res = await fetch("/api/documents/upload", { cache: "no-store" });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load uploads");
      setDocuments(data.documents ?? []);
      setListError("");
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not load uploads");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    fetch("/api/auth/session")
      .then((res) => res.json())
      .then((data) => {
        if (!data.authenticated) router.push("/login");
        else setCompanySlug(data.session.tenantSlug);
      })
      .catch(() => router.push("/login"));
    loadDocuments();
  }, [loadDocuments, router]);

  // Keep statuses fresh while anything is still being processed
  const hasPending = documents.some((doc) => IN_PROGRESS.has(doc.status));
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(loadDocuments, 5000);
    return () => clearInterval(timer);
  }, [hasPending, loadDocuments]);

  const handleFiles = useCallback(
    async (format: UploadFormat, files: File[]) => {
      for (const file of files) {
        const key = `${file.name}-${file.size}-${Date.now()}-${Math.random()}`;
        const update = (patch: Partial<UploadProgress>) =>
          setProgress((items) => items.map((p) => (p.key === key ? { ...p, ...patch } : p)));

        setProgress((items) => [
          { key, fileName: file.name, formatName: format.name, percent: 0, state: "uploading" },
          ...items,
        ]);

        // Same checks as the server, so mistakes show up instantly
        const check = checkUploadFormat(file.name, file.type, format.id);
        if (!check.ok) {
          update({ state: "error", message: check.error });
          continue;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          update({ state: "error", message: "File is larger than 100 MB" });
          continue;
        }

        try {
          await uploadFile(file, format.id, (percent) => update({ percent }));
          update({ state: "done", percent: 100, message: "Uploaded — processing started" });
        } catch (err) {
          update({
            state: "error",
            message: err instanceof Error ? err.message : "Upload failed",
          });
        }
        loadDocuments();
      }
    },
    [loadDocuments]
  );

  const formatOf = (doc: UploadedDocument) =>
    findFormatForFile(doc.fileName)?.name ?? doc.documentType;

  const visibleDocuments = useMemo(() => {
    const query = search.trim().toLowerCase();
    return documents.filter((doc) => {
      const format = findFormatForFile(doc.fileName);
      if (formatFilter !== "all" && format?.id !== formatFilter) return false;
      if (query && !doc.title.toLowerCase().includes(query)) return false;
      return true;
    });
  }, [documents, formatFilter, search]);

  const countsByFormat = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const doc of documents) {
      const id = findFormatForFile(doc.fileName)?.id;
      if (id) counts[id] = (counts[id] ?? 0) + 1;
    }
    return counts;
  }, [documents]);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href="/dashboard" className={styles.backLink}>
          <ArrowLeft size={16} /> Back to dashboard
        </Link>
        {companySlug && (
          <span className={styles.company}>
            Company: <strong>{companySlug}</strong>
          </span>
        )}
      </header>

      <main className={styles.main}>
        <div className={styles.titleBlock}>
          <h1>Data Uploads</h1>
          <p>
            Everything uploaded here becomes knowledge for your company&apos;s chatbot. Only people
            in your company can see these files.
          </p>
        </div>

        <section aria-labelledby="formats-heading">
          <div className={styles.sectionHeader}>
            <h2 id="formats-heading">Supported formats ({UPLOAD_FORMATS.length})</h2>
            <span className={styles.sectionHint}>
              Choose a format, then select or drop files · up to 100 MB each
            </span>
          </div>
          <div className={styles.formatGrid}>
            {UPLOAD_FORMATS.map((format) => (
              <FormatCard key={format.id} format={format} onFiles={handleFiles} />
            ))}
          </div>

          {progress.length > 0 && (
            <div className={styles.progressList} aria-live="polite">
              {progress.slice(0, 8).map((item) => (
                <div key={item.key} className={styles.progressItem}>
                  <span className={styles.progressName}>{item.fileName}</span>
                  <span
                    className={
                      item.state === "done"
                        ? styles.progressDone
                        : item.state === "error"
                          ? styles.statusFailed
                          : styles.muted
                    }
                  >
                    {item.state === "uploading"
                      ? `${item.formatName} · ${item.percent}%`
                      : item.state === "done"
                        ? "Uploaded"
                        : "Failed"}
                  </span>
                  {item.state === "uploading" && (
                    <div className={styles.progressBar}>
                      <div className={styles.progressFill} style={{ width: `${item.percent}%` }} />
                    </div>
                  )}
                  {item.state === "error" && item.message && (
                    <span className={styles.progressError}>{item.message}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section aria-labelledby="history-heading">
          <div className={styles.sectionHeader}>
            <h2 id="history-heading">Uploaded data ({documents.length})</h2>
            <button type="button" className={styles.refreshButton} onClick={loadDocuments}>
              <RefreshCw size={12} /> Refresh
            </button>
          </div>

          <div className={styles.toolbar}>
            <button
              type="button"
              className={`${styles.filterChip} ${formatFilter === "all" ? styles.active : ""}`}
              onClick={() => setFormatFilter("all")}
            >
              All ({documents.length})
            </button>
            {UPLOAD_FORMATS.filter((f) => countsByFormat[f.id]).map((format) => (
              <button
                key={format.id}
                type="button"
                className={`${styles.filterChip} ${formatFilter === format.id ? styles.active : ""}`}
                onClick={() => setFormatFilter(format.id)}
              >
                {format.name} ({countsByFormat[format.id]})
              </button>
            ))}
            <input
              type="search"
              className={styles.search}
              placeholder="Search file names…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search uploads"
            />
          </div>

          {listError && <div className={styles.pageError}>{listError}</div>}

          <div className={styles.tableWrap}>
            {loading ? (
              <div className={styles.empty}>Loading uploads…</div>
            ) : documents.length === 0 ? (
              <div className={styles.empty}>
                No data uploaded yet. Pick a format above to add your first file.
              </div>
            ) : visibleDocuments.length === 0 ? (
              <div className={styles.empty}>No uploads match this filter.</div>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Format</th>
                    <th>Size</th>
                    <th>Uploaded by</th>
                    <th>Uploaded at</th>
                    <th>Status</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visibleDocuments.map((doc) => {
                    const status = describeStatus(doc.status);
                    return (
                      <tr key={doc.id}>
                        <td className={styles.fileCell}>{doc.title}</td>
                        <td>
                          <span className={styles.formatBadge}>{formatOf(doc)}</span>
                        </td>
                        <td className={styles.muted}>{formatBytes(doc.fileSize)}</td>
                        <td className={styles.muted}>{doc.uploadedBy ?? "—"}</td>
                        <td className={styles.muted}>{formatDate(doc.createdAt)}</td>
                        <td>
                          <span className={`${styles.status} ${status.className}`}>
                            <span className={styles.dot} />
                            {status.label}
                          </span>
                          {doc.status === "failed" && doc.error && (
                            <span className={styles.errorText}>{doc.error}</span>
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            className={styles.showButton}
                            onClick={() =>
                              setViewing({ id: doc.id, title: doc.title, documentType: formatOf(doc) })
                            }
                          >
                            <Eye size={13} /> Show
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </main>
      {viewing && <DocumentViewer doc={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
