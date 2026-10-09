"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download, Loader, X } from "lucide-react";
import { parseCsv } from "@/lib/csv";
import { viewerKindFor } from "@/lib/formats";
import styles from "./DocumentViewer.module.css";

/**
 * Shows one uploaded document in a way that fits its type:
 * PDF inline, Word as a document, Excel as sheets, PowerPoint as slides,
 * CSV as a table, JSON as an expandable tree, Markdown rendered, text as-is.
 */

export interface ViewerDocument {
  id: string;
  title: string;
  documentType: string;
}

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "table"; rows: string[][]; total_rows: number };
type OfficePreview =
  | { kind: "document"; blocks: Block[] }
  | { kind: "sheets"; sheets: { name: string; rows: string[][]; total_rows: number }[] }
  | {
      kind: "slides";
      slides: { number: number; title: string; bullets: string[]; tables: string[][][]; notes: string }[];
    };

const MAX_CSV_ROWS = 1000;

export function DocumentViewer({ doc, onClose }: { doc: ViewerDocument; onClose: () => void }) {
  const kind = viewerKindFor(doc.title);
  const fileUrl = `/api/documents/${doc.id}/file`;
  const [text, setText] = useState<string | null>(null);
  const [preview, setPreview] = useState<OfficePreview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (kind === "pdf" || kind === "image") return;
    const url = kind === "office" ? `/api/documents/${doc.id}/preview` : fileUrl;
    let cancelled = false;
    fetch(url, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `Could not open file (${res.status})`);
        if (kind === "office") {
          const data = await res.json();
          if (!cancelled) setPreview(data);
        } else {
          const body = await res.text();
          if (!cancelled) setText(body);
        }
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not open file"));
    return () => {
      cancelled = true;
    };
  }, [doc.id, fileUrl, kind]);

  const loading = !error && kind !== "pdf" && kind !== "image" && text === null && preview === null;

  return (
    <div className={styles.backdrop} onClick={onClose} role="dialog" aria-modal="true" aria-label={doc.title}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <div className={styles.titleBlock}>
            <span className={styles.badge}>{doc.documentType}</span>
            <h2 className={styles.title}>{doc.title}</h2>
          </div>
          <a className={styles.action} href={fileUrl} download={doc.title}>
            <Download size={14} /> Download
          </a>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className={styles.body}>
          {error && <div className={styles.error}>{error}</div>}
          {loading && (
            <div className={styles.loading}>
              <Loader size={16} className="animate-spin" /> Opening…
            </div>
          )}
          {kind === "pdf" && <iframe className={styles.pdf} src={fileUrl} title={doc.title} />}
          {kind === "image" && (
            // eslint-disable-next-line @next/next/no-img-element
            <img className={styles.image} src={fileUrl} alt={doc.title} />
          )}
          {text !== null && kind === "csv" && <CsvTable text={text} />}
          {text !== null && kind === "json" && <JsonDocument text={text} />}
          {text !== null && kind === "jsonl" && <JsonLines text={text} />}
          {text !== null && kind === "markdown" && (
            <article className={styles.markdown}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
            </article>
          )}
          {text !== null && kind === "text" && <pre className={styles.text}>{text}</pre>}
          {preview?.kind === "document" && <WordDocument blocks={preview.blocks} />}
          {preview?.kind === "sheets" && <Workbook sheets={preview.sheets} />}
          {preview?.kind === "slides" && <Slides slides={preview.slides} />}
        </div>
      </div>
    </div>
  );
}

// ── Tables (CSV, Word tables, Excel sheets) ──────────
function Table({ rows, header = true }: { rows: string[][]; header?: boolean }) {
  if (rows.length === 0) return <div className={styles.muted}>Empty</div>;
  const width = Math.max(...rows.map((r) => r.length));
  const [head, ...body] = header ? rows : [[], ...rows];
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        {header && (
          <thead>
            <tr>
              {Array.from({ length: width }, (_, i) => (
                <th key={i}>{head[i] ?? ""}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>
              {Array.from({ length: width }, (_, j) => (
                <td key={j}>{r[j] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function columnName(index: number): string {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  }
  return name;
}

/** An Excel-like grid: column letters and row numbers, no row assumed to be a header. */
function SheetGrid({ rows }: { rows: string[][] }) {
  if (rows.length === 0) return <div className={styles.muted}>Empty sheet</div>;
  const width = Math.max(...rows.map((r) => r.length));
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.rowNumber} />
            {Array.from({ length: width }, (_, i) => (
              <th key={i} className={styles.columnLetter}>
                {columnName(i)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <th className={styles.rowNumber}>{i + 1}</th>
              {Array.from({ length: width }, (_, j) => (
                <td key={j}>{r[j] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CsvTable({ text }: { text: string }) {
  const rows = useMemo(() => parseCsv(text), [text]);
  const records = rows.length - 1;
  return (
    <>
      <div className={styles.meta}>
        {records} row{records === 1 ? "" : "s"} · {rows[0]?.length ?? 0} columns
        {rows.length > MAX_CSV_ROWS + 1 && ` · showing the first ${MAX_CSV_ROWS}`}
      </div>
      <Table rows={rows.slice(0, MAX_CSV_ROWS + 1)} />
    </>
  );
}

// ── JSON ─────────────────────────────────────────────
function JsonValue({ value, name, depth }: { value: unknown; name?: string; depth: number }) {
  const label = name !== undefined ? <span className={styles.jsonKey}>{name}: </span> : null;
  if (value === null || typeof value !== "object") {
    const cls =
      typeof value === "string" ? styles.jsonString : typeof value === "number" ? styles.jsonNumber : styles.jsonOther;
    return (
      <div className={styles.jsonLine}>
        {label}
        <span className={cls}>{typeof value === "string" ? `"${value}"` : String(value)}</span>
      </div>
    );
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>);
  const summary = Array.isArray(value) ? `[ ${entries.length} items ]` : `{ ${entries.length} fields }`;
  return (
    <details className={styles.jsonNode} open={depth < 2}>
      <summary>
        {label}
        <span className={styles.jsonOther}>{summary}</span>
      </summary>
      {entries.map(([k, v]) => (
        <JsonValue key={k} name={k} value={v} depth={depth + 1} />
      ))}
    </details>
  );
}

function JsonDocument({ text }: { text: string }) {
  try {
    return (
      <div className={styles.json}>
        <JsonValue value={JSON.parse(text)} depth={0} />
      </div>
    );
  } catch {
    return <pre className={styles.text}>{text}</pre>;
  }
}

function JsonLines({ text }: { text: string }) {
  const records = text.split(/\r?\n/).filter((line) => line.trim());
  return (
    <>
      <div className={styles.meta}>{records.length} records (one JSON object per line)</div>
      <div className={styles.json}>
        {records.map((line, i) => {
          try {
            return <JsonValue key={i} name={`Record ${i + 1}`} value={JSON.parse(line)} depth={1} />;
          } catch {
            return (
              <div key={i} className={styles.error}>
                Line {i + 1} is not valid JSON
              </div>
            );
          }
        })}
      </div>
    </>
  );
}

// ── Office previews ──────────────────────────────────
function WordDocument({ blocks }: { blocks: Block[] }) {
  return (
    <article className={styles.page}>
      {blocks.map((b, i) => {
        if (b.type === "heading") {
          const Tag = (`h${Math.min(b.level + 1, 4)}`) as "h2" | "h3" | "h4";
          return <Tag key={i}>{b.text}</Tag>;
        }
        if (b.type === "paragraph") return <p key={i}>{b.text}</p>;
        return <Table key={i} rows={b.rows} />;
      })}
    </article>
  );
}

function Workbook({ sheets }: { sheets: { name: string; rows: string[][]; total_rows: number }[] }) {
  const [active, setActive] = useState(0);
  const sheet = sheets[active];
  return (
    <>
      <div className={styles.tabs} role="tablist">
        {sheets.map((s, i) => (
          <button
            key={s.name}
            type="button"
            role="tab"
            aria-selected={i === active}
            className={`${styles.tab} ${i === active ? styles.tabActive : ""}`}
            onClick={() => setActive(i)}
          >
            {s.name}
          </button>
        ))}
      </div>
      {sheet && (
        <>
          <div className={styles.meta}>
            {sheet.total_rows} rows{sheet.rows.length < sheet.total_rows && ` · showing the first ${sheet.rows.length}`}
          </div>
          <SheetGrid rows={sheet.rows} />
        </>
      )}
    </>
  );
}

function Slides({ slides }: { slides: { number: number; title: string; bullets: string[]; tables: string[][][]; notes: string }[] }) {
  return (
    <div className={styles.slides}>
      {slides.map((s) => (
        <section key={s.number} className={styles.slide}>
          <div className={styles.slideNumber}>Slide {s.number}</div>
          <h3 className={styles.slideTitle}>{s.title}</h3>
          {s.bullets.length > 0 && (
            <ul>
              {s.bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          )}
          {s.tables.map((t, i) => (
            <Table key={i} rows={t} />
          ))}
          {s.notes && <div className={styles.notes}>Speaker notes: {s.notes}</div>}
        </section>
      ))}
    </div>
  );
}
