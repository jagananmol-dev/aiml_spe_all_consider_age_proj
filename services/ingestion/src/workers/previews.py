"""
VEDA AI — Document previews for Office files

Browsers can show PDFs, text, CSV, JSON and Markdown from the original file,
but not Word, Excel or PowerPoint. While a document is processed, these
builders keep its structure as JSON so the upload page can show it:

- docx → {"kind": "document", "blocks": [heading | paragraph | table]}
- xlsx → {"kind": "sheets", "sheets": [{"name", "rows", "total_rows"}]}
- pptx → {"kind": "slides", "slides": [{"number", "title", "bullets", "tables", "notes"}]}

Large files are capped (MAX_ROWS rows per table or sheet, MAX_BLOCKS
blocks); the caps are reported so the viewer can say what was cut.
"""

import json
import logging

logger = logging.getLogger("veda.ingestion.previews")

MAX_ROWS = 300
MAX_BLOCKS = 2000
MAX_CELL_CHARS = 500
OFFICE_EXTENSIONS = {"docx", "xlsx", "pptx"}


def _cell(value) -> str:
    text = "" if value is None else str(value).strip()
    return text[:MAX_CELL_CHARS]


def _trim_row(row: list[str]) -> list[str]:
    while row and row[-1] == "":
        row = row[:-1]
    return row


def preview_docx(file_path: str) -> dict:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(file_path)
    blocks: list[dict] = []
    for child in document.element.body.iterchildren():
        if len(blocks) >= MAX_BLOCKS:
            break
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            if style == "Title":
                blocks.append({"type": "heading", "level": 1, "text": text})
            elif style.lower().startswith("heading"):
                level = int(style.split()[-1]) + 1 if style.split()[-1].isdigit() else 2
                blocks.append({"type": "heading", "level": min(level, 4), "text": text})
            else:
                blocks.append({"type": "paragraph", "text": text})
        elif tag == "tbl":
            rows = [[_cell(c.text) for c in row.cells] for row in Table(child, document).rows]
            blocks.append({"type": "table", "rows": rows[:MAX_ROWS], "total_rows": len(rows)})
    return {"kind": "document", "blocks": blocks}


def preview_xlsx(file_path: str) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            rows, total = [], 0
            for row in ws.iter_rows(values_only=True):
                cells = _trim_row([_cell(v) for v in row])
                if not cells:
                    continue
                total += 1
                if len(rows) < MAX_ROWS:
                    rows.append(cells)
            sheets.append({"name": ws.title, "rows": rows, "total_rows": total})
    finally:
        wb.close()
    return {"kind": "sheets", "sheets": sheets}


def preview_pptx(file_path: str) -> dict:
    from pptx import Presentation

    deck = Presentation(file_path)
    slides = []
    for number, slide in enumerate(deck.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        bullets: list[str] = []
        tables: list[list[list[str]]] = []
        title_id = title_shape.shape_id if title_shape is not None else None
        for shape in slide.shapes:
            if shape.shape_id == title_id:  # shapes are new proxy objects each time; compare ids
                continue
            if getattr(shape, "has_text_frame", False):
                bullets += [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
            if getattr(shape, "has_table", False):
                tables.append([[_cell(c.text) for c in row.cells] for row in shape.table.rows][:MAX_ROWS])
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        slides.append({"number": number, "title": title, "bullets": bullets, "tables": tables, "notes": notes})
    return {"kind": "slides", "slides": slides}


BUILDERS = {"docx": preview_docx, "xlsx": preview_xlsx, "pptx": preview_pptx}


def build_preview(file_path: str, extension: str) -> dict | None:
    """Structured preview for an Office file, or None for other formats."""
    builder = BUILDERS.get(extension.lower())
    return builder(file_path) if builder else None


def save_preview(database_url: str, tenant_id: str, document_id: str, preview: dict) -> None:
    """Store (or replace) a document's preview. Needs 004_document_previews.sql."""
    import psycopg

    with psycopg.connect(database_url, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        conn.execute(
            """
            INSERT INTO document_previews (tenant_id, document_id, preview)
            VALUES (%s::uuid, %s::uuid, %s::jsonb)
            ON CONFLICT (document_id) DO UPDATE SET preview = EXCLUDED.preview, created_at = NOW()
            """,
            [tenant_id, document_id, json.dumps(preview, ensure_ascii=False)],
        )


def store_preview_safely(database_url: str, tenant_id: str, document_id: str, file_path: str, extension: str) -> None:
    """Build and save a preview; a failure is logged, never raised (the preview is optional)."""
    try:
        preview = build_preview(file_path, extension)
        if preview is not None:
            save_preview(database_url, tenant_id, document_id, preview)
    except Exception as e:
        logger.warning(f"Could not store preview for document {document_id}: {e}")
