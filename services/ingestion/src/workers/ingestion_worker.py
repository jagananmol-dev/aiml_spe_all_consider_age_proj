"""
VEDA AI — Document Ingestion Workers

Kafka consumers that process uploaded documents through the ingestion pipeline:
1. Parse documents (PDF, images, spreadsheets, emails)
2. Extract text content with layout preservation
3. Handle OCR for scanned documents
4. Extract tables and structured data
5. Publish parsed results for downstream processing
"""

import csv
import io
import json
import os
import re
import tempfile
import logging
from datetime import datetime, timezone

# Singleton EasyOCR reader instance
_easyocr_reader = None

try:
    from confluent_kafka import Consumer, Producer, KafkaError
except ImportError:  # pragma: no cover - optional dependency
    Consumer = Producer = None

    class KafkaError(Exception):
        _PARTITION_EOF = 0


try:
    from minio import Minio
except ImportError:  # pragma: no cover - optional dependency
    Minio = None

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - optional dependency

    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


# ── Configuration ─────────────────────────────────────
class Settings(BaseSettings):
    """Service configuration from environment variables."""

    # Kafka
    kafka_brokers: str = "localhost:9092"
    kafka_group_id: str = "veda-ingestion-workers"
    kafka_auto_offset_reset: str = "earliest"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False

    # PostgreSQL
    database_url: str = "postgresql://veda:changeme@localhost:5432/veda_db"

    # Processing
    max_file_size_mb: int = 100
    # English only by default: adding "hi" made EasyOCR read Latin-script
    # digits as Devanagari ("2026" → "२०२६"). Set VEDA_OCR_LANGUAGES='["en","hi"]'
    # for Hindi documents.
    ocr_languages: list[str] = ["en"]

    class Config:
        env_prefix = "VEDA_"


settings = Settings()
logger = logging.getLogger("veda.ingestion")


# ── Event Schemas ─────────────────────────────────────
class DocumentUploadedEvent(BaseModel):
    """
    Published by the web app (apps/web/src/lib/kafka.ts) in camelCase,
    e.g. {"tenantId": ..., "documentId": ...}. Snake_case is accepted too.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tenant_id: str
    document_id: str
    file_name: str
    file_type: str
    storage_path: str
    storage_bucket: str
    uploaded_by: str
    timestamp: str


class DocumentParsedEvent(BaseModel):
    tenant_id: str
    document_id: str
    raw_text: str
    page_count: int
    word_count: int
    tables: list[dict] = []
    parsed_content: dict = {}
    timestamp: str


class DocumentParseFailedEvent(BaseModel):
    tenant_id: str
    document_id: str
    error: str
    timestamp: str


# ── Kafka Setup ───────────────────────────────────────
TOPICS = {
    "DOCUMENT_UPLOADED": "veda.documents.uploaded",
    "DOCUMENT_PARSED": "veda.documents.parsed",
    "DOCUMENT_PARSE_FAILED": "veda.documents.parse-failed",
}


def create_consumer():
    """Create a Kafka consumer configured for the ingestion group."""
    if Consumer is None:
        raise RuntimeError("confluent-kafka is not installed. Install service dependencies first.")
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_brokers,
            "group.id": settings.kafka_group_id,
            "auto.offset.reset": settings.kafka_auto_offset_reset,
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,  # 5 min for large doc processing
        }
    )


def create_producer():
    """Create a Kafka producer for publishing parsed results."""
    if Producer is None:
        raise RuntimeError("confluent-kafka is not installed. Install service dependencies first.")
    return Producer(
        {
            "bootstrap.servers": settings.kafka_brokers,
            "acks": "all",
            "retries": 3,
            "linger.ms": 10,
        }
    )


# ── MinIO Client ──────────────────────────────────────
def get_minio_client():
    """Create a MinIO client for document storage access."""
    if Minio is None:
        raise RuntimeError("minio is not installed. Install service dependencies first.")
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


# ── Document Parsers ─────────────────────────────────
def parse_pdf(file_path: str) -> dict:
    """
    Parse a PDF document using PyMuPDF for text and pdfplumber for tables.

    Returns:
        dict with keys: raw_text, page_count, word_count, tables, pages
    """
    import fitz  # PyMuPDF
    import pdfplumber

    result = {
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
        page_text = page.get_text(
            "text", flags=fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_LIGATURES
        )
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
        _easyocr_reader = easyocr.Reader(settings.ocr_languages, gpu=use_gpu, verbose=False)

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


def parse_spreadsheet(file_path: str) -> dict:
    """
    Parse Excel/CSV spreadsheets into structured data.
    Commonly used for maintenance work order exports from SAP/Maximo.
    """
    import openpyxl

    wb = openpyxl.load_workbook(file_path, data_only=True)

    all_text_parts = []
    tables = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_data = []

        for row in ws.iter_rows(values_only=True):
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


# ── Temp file handling ────────────────────────────────
def safe_temp_path(document_id: str, file_name: str) -> str:
    """
    Build a temp path for a downloaded document that cannot escape the
    temp directory, whatever the (client-supplied) file name contains.
    """
    base = os.path.basename(file_name.replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".") or "file"
    safe_id = re.sub(r"[^A-Za-z0-9-]", "_", document_id)
    path = os.path.join(tempfile.gettempdir(), f"veda_{safe_id}_{cleaned[:200]}")
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(tempfile.gettempdir()):
        raise ValueError(f"Unsafe temp path for document {document_id}")
    return path


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


# ── Document status in PostgreSQL ─────────────────────
def update_document_status(
    tenant_id: str,
    document_id: str,
    *,
    status: str,
    parsing_status: str | None = None,
    page_count: int | None = None,
    word_count: int | None = None,
    error: str | None = None,
) -> None:
    """
    Record processing progress on the document row so the upload page can
    show it. Uses statuses valid in both schemas (uploaded / processing /
    indexed / failed). Never raises: status reporting must not break parsing.
    """
    if psycopg is None:
        logger.warning("psycopg not installed; cannot update document status")
        return
    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
            conn.execute(
                """
                UPDATE documents
                SET status = %s,
                    parsing_status = COALESCE(%s, parsing_status),
                    page_count = COALESCE(%s, page_count),
                    word_count = COALESCE(%s, word_count),
                    metadata = CASE
                        WHEN %s::text IS NULL THEN COALESCE(metadata, '{}'::jsonb) - 'error'
                        ELSE COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('error', %s::text)
                    END,
                    updated_at = NOW()
                WHERE id = %s::uuid AND tenant_id = %s::uuid
                """,
                [
                    status,
                    parsing_status,
                    page_count,
                    word_count,
                    error,
                    error,
                    document_id,
                    tenant_id,
                ],
            )
    except Exception as e:
        logger.warning(f"Could not update status for document {document_id}: {e}")


def user_facing_error(exc: Exception) -> str:
    """Short, safe error text to show on the upload page."""
    message = str(exc).strip() or exc.__class__.__name__
    return message[:300]


# ── Main Worker Loop ──────────────────────────────────
def run_ingestion_worker():
    """
    Main Kafka consumer loop for the ingestion service.

    Listens for document upload events, downloads files from MinIO,
    parses them, and publishes results.
    """
    try:
        consumer = create_consumer()
        producer = create_producer()
        minio_client = get_minio_client()
    except RuntimeError as exc:
        logger.error(str(exc))
        return

    consumer.subscribe([TOPICS["DOCUMENT_UPLOADED"]])

    logger.info("🚀 VEDA Ingestion Worker started. Listening for documents...")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error(f"Kafka error: {msg.error()}")
                continue

            event_data: dict = {}
            try:
                # Parse the upload event
                event_data = json.loads(msg.value().decode("utf-8"))
                event = DocumentUploadedEvent(**event_data)

                logger.info(
                    f"📄 Processing document: {event.file_name} "
                    f"(tenant: {event.tenant_id}, doc: {event.document_id})"
                )
                update_document_status(
                    event.tenant_id,
                    event.document_id,
                    status="processing",
                    parsing_status="processing",
                )

                # Download file from MinIO
                temp_path = safe_temp_path(event.document_id, event.file_name)
                minio_client.fget_object(
                    event.storage_bucket,
                    event.storage_path,
                    temp_path,
                )

                # Get parser and process (temp file is removed even if parsing fails)
                file_ext = event.file_name.rsplit(".", 1)[-1].lower()
                try:
                    parser = get_parser(file_ext)
                    result = parser(temp_path)
                    from .previews import store_preview_safely

                    store_preview_safely(
                        settings.database_url, event.tenant_id, event.document_id, temp_path, file_ext
                    )
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

                if not result["raw_text"].strip():
                    raise ValueError("No readable text found in this file")

                # Publish parsed result
                parsed_event = DocumentParsedEvent(
                    tenant_id=event.tenant_id,
                    document_id=event.document_id,
                    raw_text=result["raw_text"],
                    page_count=result["page_count"],
                    word_count=result["word_count"],
                    tables=result.get("tables", []),
                    # Everything except the text fields already sent above, to
                    # keep the Kafka message small
                    parsed_content={
                        k: v for k, v in result.items() if k not in ("raw_text", "pages", "tables")
                    },
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

                producer.produce(
                    TOPICS["DOCUMENT_PARSED"],
                    key=event.document_id,
                    value=parsed_event.model_dump_json(),
                )
                producer.flush()

                # Parsed; the graph worker marks it "indexed" once embedded
                update_document_status(
                    event.tenant_id,
                    event.document_id,
                    status="processing",
                    parsing_status="completed",
                    page_count=result["page_count"],
                    word_count=result["word_count"],
                )

                # Commit offset after successful processing
                consumer.commit(asynchronous=False)

                logger.info(
                    f"✅ Document parsed: {event.file_name} "
                    f"({result['page_count']} pages, {result['word_count']} words, "
                    f"{len(result.get('tables', []))} tables)"
                )

            except Exception as e:
                logger.error(f"❌ Failed to process document: {e}", exc_info=True)

                tenant_id = event_data.get("tenantId") or event_data.get("tenant_id")
                document_id = event_data.get("documentId") or event_data.get("document_id")
                if tenant_id and document_id:
                    update_document_status(
                        tenant_id,
                        document_id,
                        status="failed",
                        parsing_status="failed",
                        error=user_facing_error(e),
                    )

                # Publish failure event
                try:
                    fail_event = DocumentParseFailedEvent(
                        tenant_id=tenant_id or "unknown",
                        document_id=document_id or "unknown",
                        error=str(e),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    producer.produce(
                        TOPICS["DOCUMENT_PARSE_FAILED"],
                        value=fail_event.model_dump_json(),
                    )
                    producer.flush()
                except Exception:
                    pass

                consumer.commit(asynchronous=False)

    except KeyboardInterrupt:
        logger.info("🛑 Ingestion worker shutting down...")
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_ingestion_worker()
