"""
NLP pipeline — Step 1: Text extraction and OCR

Every uploaded file becomes clean, linear text before any NLP runs:

- PDF: PyMuPDF text per page (ligatures expanded), pdfplumber tables;
- images: EasyOCR, boxes regrouped into reading-order lines, OCR digit fixes;
- CSV / JSON: each record linearised into "key: value" lines, so column
  names stay next to their values;
- Word / PowerPoint / Excel / text: paragraphs, tables, notes in reading order.

Each parser returns {"raw_text", "page_count", "word_count", "tables", ...}.
Next step: step02_chunking.py splits raw_text into passages.

Used by: services/ingestion/src/workers/ (Kafka and local workers).
"""

import csv
import io
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("veda.ingestion")

# Singleton EasyOCR reader instance (loading it takes seconds)
_easyocr_reader = None


def ocr_languages() -> list[str]:
    """
    OCR languages from VEDA_OCR_LANGUAGES (a JSON list), English by default.

    Adding "hi" made EasyOCR read Latin-script digits as Devanagari
    ("2026" → "२०२६"), so Hindi is opt-in: VEDA_OCR_LANGUAGES='["en","hi"]'.
    """
    raw = os.environ.get("VEDA_OCR_LANGUAGES", "").strip()
    if not raw:
        return ["en"]
    try:
        languages = json.loads(raw)
    except json.JSONDecodeError:
        languages = raw.split(",")
    return [str(lang).strip() for lang in languages if str(lang).strip()] or ["en"]


# ── Document Parsers ─────────────────────────────────
def parse_pdf(file_path: str) -> dict:
    """
    Parse a PDF document using PyMuPDF for text and pdfplumber for tables.

    Returns:
        dict with keys: raw_text, page_count, word_count, tables, pages
    """
    import fitz  # PyMuPDF
    import pdfplumber

    result: dict[str, Any] = {
        "raw_text": "",
        "page_count": 0,
        "word_count": 0,
        "tables": [],
        "pages": [],
    }

    # Extract text with PyMuPDF (faster, better layout preservation)
    doc = fitz.open(file_path)
    result["page_count"] = len(doc)

    full_text_parts = []
    for page_num, page in enumerate(doc):
        # Expand ligatures ("ﬁ" → "fi") so the text matches what people type
        page_text = page.get_text("text", flags=fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_LIGATURES)
        full_text_parts.append(page_text)

        result["pages"].append(
            {
                "page_number": page_num + 1,
                "text": page_text,
                "width": page.rect.width,
                "height": page.rect.height,
            }
        )

    doc.close()
    result["raw_text"] = "\n\n".join(full_text_parts)
    result["word_count"] = len(result["raw_text"].split())

    # Extract tables with pdfplumber (better table detection)
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for table_idx, table in enumerate(tables):
                    if table:
                        result["tables"].append(
                            {
                                "page_number": page_num + 1,
                                "table_index": table_idx,
                                "data": table,
                                "rows": len(table),
                                "columns": len(table[0]) if table else 0,
                            }
                        )
    except Exception as e:
        logger.warning(f"Table extraction failed for {file_path}: {e}")

    return result


# A letter O inside the numeric part of a tag-like token ("P-1O1A") is a zero
_TAG_TOKEN = re.compile(r"\b[A-Z]{1,5}-[0-9O]{2,5}[A-Z]?\b")


def _fix_tag_digits(text: str) -> str:
    def fix(match: re.Match) -> str:
        token = match.group(0)
        prefix, _, rest = token.partition("-")
        return f"{prefix}-{rest.replace('O', '0')}" if any(c.isdigit() for c in rest) else token

    return _TAG_TOKEN.sub(fix, text)


def _group_ocr_lines(results: list) -> list[str]:
    """Join OCR text boxes into reading-order lines (top to bottom, left to right)."""
    boxes = []
    for bbox, text, _ in results:
        ys = [point[1] for point in bbox]
        boxes.append((min(ys), max(ys), min(point[0] for point in bbox), text))
    boxes.sort()

    lines: list[list[tuple]] = []
    for top, bottom, left, text in boxes:
        centre = (top + bottom) / 2
        last = lines[-1] if lines else None
        if last and abs(centre - last[0][4]) < (bottom - top) / 2:
            last.append((top, bottom, left, text, last[0][4]))
        else:
            lines.append([(top, bottom, left, text, centre)])
    return [" ".join(box[3] for box in sorted(line, key=lambda b: b[2])) for line in lines]


def parse_image_ocr(file_path: str) -> dict:
    """
    Parse a scanned image or photo with EasyOCR.

    The image is read as-is: on clean scans, thresholding and denoising made
    recognition worse. Text boxes are grouped into lines in reading order,
    so each printed line stays a line of text.
    """
    import easyocr
    import torch

    global _easyocr_reader
    if _easyocr_reader is None:
        # Check if CUDA is actually available
        use_gpu = torch.cuda.is_available()
        logger.info(f"Initializing EasyOCR reader (use_gpu={use_gpu})")
        # verbose=False: the first-run model download draws a progress bar
        # with characters a Windows (cp1252) console cannot encode, which
        # crashes the download
        _easyocr_reader = easyocr.Reader(ocr_languages(), gpu=use_gpu, verbose=False)

    results = _easyocr_reader.readtext(file_path, detail=1, paragraph=False)
    lines = [_fix_tag_digits(line) for line in _group_ocr_lines(results)]
    ocr_details = [
        {
            "text": text,
            "confidence": float(confidence),
            "bbox": [[float(c) for c in point] for point in bbox],
        }
        for bbox, text, confidence in results
    ]

    return {
        "raw_text": "\n".join(lines),
        "page_count": 1,
        "word_count": len(" ".join(lines).split()),
        "tables": [],
        "ocr_details": ocr_details,
    }


# Rows read per sheet; beyond this a spreadsheet is a data dump, not a document
MAX_SHEET_ROWS = 20_000


def parse_spreadsheet(file_path: str) -> dict:
    """
    Parse Excel/CSV spreadsheets into structured data.
    Commonly used for maintenance work order exports from SAP/Maximo.
    """
    import openpyxl

    # read_only streams rows instead of building the whole workbook in memory,
    # so a small file that decompresses to a huge sheet cannot exhaust it
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)

    all_text_parts = []
    tables = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_data: list[list[str]] = []

        for row in ws.iter_rows(values_only=True):
            if len(sheet_data) >= MAX_SHEET_ROWS:
                logger.warning(f"Sheet {sheet_name!r} truncated at {MAX_SHEET_ROWS} rows")
                break
            row_data = [str(cell) if cell is not None else "" for cell in row]
            sheet_data.append(row_data)
            all_text_parts.append(" ".join(row_data))

        if sheet_data:
            tables.append(
                {
                    "sheet_name": sheet_name,
                    "data": sheet_data,
                    "rows": len(sheet_data),
                    "columns": len(sheet_data[0]) if sheet_data else 0,
                }
            )

    wb.close()

    raw_text = "\n".join(all_text_parts)
    return {
        "raw_text": raw_text,
        "page_count": len(wb.sheetnames),
        "word_count": len(raw_text.split()),
        "tables": tables,
    }



# ── Text, data and Office parsers ─────────────────────
# Cap table rows carried in events; the full content is always in raw_text
MAX_TABLE_ROWS = 1000


def _text_result(raw_text: str, page_count: int = 1, tables: list | None = None, **extra) -> dict:
    """Build the common parser result dict."""
    return {
        "raw_text": raw_text,
        "page_count": page_count,
        "word_count": len(raw_text.split()),
        "tables": tables or [],
        **extra,
    }


def read_text_file(file_path: str) -> str:
    """
    Read a text file of unknown encoding: UTF-8 (with or without BOM),
    UTF-16 when a BOM says so, otherwise Windows-1252 as a lossless fallback.
    """
    with open(file_path, "rb") as f:
        data = f.read()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_text(file_path: str) -> dict:
    """Parse plain text and Markdown files, normalising any line endings to \\n."""
    return _text_result(read_text_file(file_path).replace("\r\n", "\n").replace("\r", "\n"))


def parse_csv(file_path: str) -> dict:
    """
    Parse a CSV export. Each row becomes a "column: value" block separated by
    blank lines, so the chunker keeps rows intact and retrieval can match on
    both column names and values.
    """
    text = read_text_file(file_path)
    try:
        dialect = csv.Sniffer().sniff(text[:10000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in row)]
    if not rows:
        return _text_result("", page_count=0)

    header = [h.strip() or f"column_{i + 1}" for i, h in enumerate(rows[0])]
    records = []
    for row in rows[1:]:
        lines = [
            f"{header[i] if i < len(header) else f'column_{i + 1}'}: {value.strip()}"
            for i, value in enumerate(row)
            if value.strip()
        ]
        if lines:
            records.append("\n".join(lines))

    table = {
        "sheet_name": os.path.basename(file_path),
        "data": rows[:MAX_TABLE_ROWS],
        "rows": len(rows),
        "columns": len(header),
    }
    return _text_result("\n\n".join(records), page_count=1, tables=[table])


def _flatten_json(value, prefix: str = "") -> list[str]:
    """Flatten nested JSON into "path.to.key: value" lines."""
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            lines.extend(_flatten_json(item, f"{prefix}.{key}" if prefix else str(key)))
        return lines
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            joined = ", ".join("" if item is None else str(item) for item in value)
            return [f"{prefix or 'values'}: {joined}"]
        lines = []
        for index, item in enumerate(value):
            lines.extend(_flatten_json(item, f"{prefix}[{index}]"))
        return lines
    return [f"{prefix or 'value'}: {'' if value is None else value}"]


def parse_json(file_path: str) -> dict:
    """
    Parse JSON or JSON Lines. A top-level array (or each JSONL line) is
    treated as a list of records; each record becomes its own block of
    flattened "key: value" lines.
    """
    text = read_text_file(file_path).strip()
    if not text:
        return _text_result("", page_count=0)

    try:
        data = json.loads(text)
        records = data if isinstance(data, list) else None
    except json.JSONDecodeError:
        # JSON Lines: one JSON value per line
        records = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_number}: {e.msg}") from None
        data = records

    if records is not None:
        blocks = [
            "\n".join([f"Record {i + 1}", *_flatten_json(record)])
            for i, record in enumerate(records)
        ]
        page_count = len(records)
    else:
        # Single object: one block per top-level key keeps related fields together
        blocks = ["\n".join(_flatten_json(value, str(key))) for key, value in data.items()]
        page_count = 1

    return _text_result("\n\n".join(b for b in blocks if b.strip()), page_count=page_count)


def parse_docx(file_path: str) -> dict:
    """Parse a Word document, keeping paragraphs and tables in reading order."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(file_path)
    parts: list[str] = []
    tables: list[dict] = []

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            parts.append(f"# {text}" if style.lower().startswith("heading") else text)
        elif tag == "tbl":
            table = Table(child, document)
            data = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if data:
                tables.append(
                    {
                        "table_index": len(tables),
                        "data": data[:MAX_TABLE_ROWS],
                        "rows": len(data),
                        "columns": len(data[0]),
                    }
                )
                parts.append("\n".join(" | ".join(row) for row in data))

    return _text_result("\n\n".join(parts), page_count=1, tables=tables)


def parse_pptx(file_path: str) -> dict:
    """Parse a PowerPoint deck: slide text, tables, and speaker notes."""
    from pptx import Presentation

    deck = Presentation(file_path)
    slides_text: list[str] = []
    tables: list[dict] = []

    for number, slide in enumerate(deck.slides, start=1):
        lines = [f"Slide {number}"]
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                data = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
                if data:
                    tables.append(
                        {
                            "page_number": number,
                            "table_index": len(tables),
                            "data": data[:MAX_TABLE_ROWS],
                            "rows": len(data),
                            "columns": len(data[0]),
                        }
                    )
                    lines.append("\n".join(" | ".join(row) for row in data))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"Notes: {notes}")
        slides_text.append("\n".join(lines))

    return _text_result("\n\n".join(slides_text), page_count=len(deck.slides), tables=tables)


# ── File Type Router ──────────────────────────────────
PARSER_MAP = {
    "pdf": parse_pdf,
    "png": parse_image_ocr,
    "jpg": parse_image_ocr,
    "jpeg": parse_image_ocr,
    "tiff": parse_image_ocr,
    "tif": parse_image_ocr,
    "bmp": parse_image_ocr,
    "xlsx": parse_spreadsheet,
    "docx": parse_docx,
    "pptx": parse_pptx,
    "csv": parse_csv,
    "json": parse_json,
    "jsonl": parse_json,
    "txt": parse_text,
    "md": parse_text,
    "markdown": parse_text,
}
# Keep in sync with apps/web/src/lib/formats.ts (the upload page's format list)


def get_parser(file_type: str):
    """Get the appropriate parser for a file type."""
    parser = PARSER_MAP.get(file_type.lower())
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")
    return parser

