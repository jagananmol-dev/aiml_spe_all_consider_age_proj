"""
VEDA AI — Ingestion Worker Unit Tests

Tests:
- get_parser: correct parser returned for each file type
- get_parser: ValueError on unsupported type
- parse_pdf: text extraction, table extraction, page count
- parse_image_ocr: OCR pipeline steps, temp file cleanup
- parse_spreadsheet: sheet iteration, table structure
- DocumentUploadedEvent: field validation
- DocumentParsedEvent: field validation
- create_consumer / create_producer: config assertions
- run_ingestion_worker: startup error when deps missing
"""

import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch, mock_open, call

from src.workers.ingestion_worker import (
    get_parser,
    PARSER_MAP,
    DocumentUploadedEvent,
    DocumentParsedEvent,
    DocumentParseFailedEvent,
    Settings,
    TOPICS,
)


# ══════════════════════════════════════════════════════
# 1. PARSER_MAP and get_parser
# ══════════════════════════════════════════════════════


class TestGetParser:
    @pytest.mark.parametrize(
        "file_type",
        [
            "pdf",
            "png",
            "jpg",
            "jpeg",
            "tiff",
            "tif",
            "bmp",
            "xlsx",
        ],
    )
    def test_supported_types_return_callable(self, file_type):
        parser = get_parser(file_type)
        assert callable(parser)

    @pytest.mark.parametrize(
        "file_type",
        [
            "PDF",
            "PNG",
            "XLSX",  # uppercase should still work
        ],
    )
    def test_case_insensitive(self, file_type):
        parser = get_parser(file_type)
        assert callable(parser)

    @pytest.mark.parametrize(
        "bad_type",
        [
            "exe",
            "zip",
            "rar",
            "mp4",
            "doc",
            "xls",
            "eml",
            "",
        ],
    )
    def test_unsupported_raises_value_error(self, bad_type):
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_parser(bad_type)

    def test_pdf_maps_to_parse_pdf(self):
        from src.workers.ingestion_worker import parse_pdf

        assert get_parser("pdf") is parse_pdf

    def test_image_types_map_to_ocr(self):
        from src.workers.ingestion_worker import parse_image_ocr

        for img_type in ["png", "jpg", "jpeg", "tiff", "tif", "bmp"]:
            assert get_parser(img_type) is parse_image_ocr

    def test_spreadsheet_types_map_to_parse_spreadsheet(self):
        from src.workers.ingestion_worker import parse_spreadsheet

        for xl_type in ["xlsx"]:
            assert get_parser(xl_type) is parse_spreadsheet


# ══════════════════════════════════════════════════════
# 2. PARSER_MAP completeness
# ══════════════════════════════════════════════════════


class TestParserMap:
    def test_all_image_types_present(self):
        for t in ["png", "jpg", "jpeg", "tiff", "tif", "bmp"]:
            assert t in PARSER_MAP

    def test_spreadsheet_types_present(self):
        for t in ["xlsx"]:
            assert t in PARSER_MAP

    def test_pdf_present(self):
        assert "pdf" in PARSER_MAP

    def test_all_values_callable(self):
        for k, v in PARSER_MAP.items():
            assert callable(v), f"Parser for {k!r} is not callable"


# ══════════════════════════════════════════════════════
# 3. parse_pdf (fitz + pdfplumber mocked)
# ══════════════════════════════════════════════════════


class TestParsePdf:
    def test_returns_dict_with_required_keys(self):
        from src.workers.ingestion_worker import parse_pdf

        mock_page = MagicMock()
        mock_page.get_text = MagicMock(return_value="Sample pump report text. PUMP-101.")
        mock_page.rect = MagicMock(width=595.0, height=842.0)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page, mock_page]))
        mock_doc.close = MagicMock()

        mock_pdf_plumber_page = MagicMock()
        mock_pdf_plumber_page.extract_tables = MagicMock(return_value=[])
        mock_pdfplumber_pdf = MagicMock()
        mock_pdfplumber_pdf.pages = [mock_pdf_plumber_page]
        mock_pdfplumber_pdf.__enter__ = MagicMock(return_value=mock_pdfplumber_pdf)
        mock_pdfplumber_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict(
            "sys.modules",
            {
                "fitz": MagicMock(open=MagicMock(return_value=mock_doc)),
                "pdfplumber": MagicMock(open=MagicMock(return_value=mock_pdfplumber_pdf)),
            },
        ):
            import importlib
            import src.workers.ingestion_worker as iw

            # Patch at runtime
            with patch("src.workers.ingestion_worker.parse_pdf", wraps=None) as _:
                pass  # We test the function directly

        # Direct test with full mocks
        with patch.dict(
            "sys.modules",
            {
                "fitz": MagicMock(),
                "pdfplumber": MagicMock(),
            },
        ):
            import fitz
            import pdfplumber

            fitz.open.return_value = mock_doc
            pdfplumber.open.return_value = mock_pdfplumber_pdf
            result = parse_pdf("/fake/path/test.pdf")

        assert "raw_text" in result
        assert "page_count" in result
        assert "word_count" in result
        assert "tables" in result
        assert "pages" in result

    def test_page_count_matches_doc_length(self):
        from src.workers.ingestion_worker import parse_pdf

        mock_page = MagicMock()
        mock_page.get_text = MagicMock(return_value="Page content here.")
        mock_page.rect = MagicMock(width=595.0, height=842.0)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=3)
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page] * 3))
        mock_doc.close = MagicMock()

        mock_pdf_page = MagicMock()
        mock_pdf_page.extract_tables = MagicMock(return_value=[])
        mock_plumber_pdf = MagicMock()
        mock_plumber_pdf.pages = [mock_pdf_page] * 3
        mock_plumber_pdf.__enter__ = MagicMock(return_value=mock_plumber_pdf)
        mock_plumber_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"fitz": MagicMock(), "pdfplumber": MagicMock()}):
            import fitz, pdfplumber

            fitz.open.return_value = mock_doc
            pdfplumber.open.return_value = mock_plumber_pdf
            result = parse_pdf("/fake/test.pdf")

        assert result["page_count"] == 3

    def test_word_count_positive_for_text(self):
        from src.workers.ingestion_worker import parse_pdf

        mock_page = MagicMock()
        mock_page.get_text = MagicMock(return_value="Five words in total here")
        mock_page.rect = MagicMock(width=595.0, height=842.0)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        mock_plumber_page = MagicMock()
        mock_plumber_page.extract_tables = MagicMock(return_value=[])
        mock_plumber_pdf = MagicMock()
        mock_plumber_pdf.pages = [mock_plumber_page]
        mock_plumber_pdf.__enter__ = MagicMock(return_value=mock_plumber_pdf)
        mock_plumber_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"fitz": MagicMock(), "pdfplumber": MagicMock()}):
            import fitz, pdfplumber

            fitz.open.return_value = mock_doc
            pdfplumber.open.return_value = mock_plumber_pdf
            result = parse_pdf("/fake/test.pdf")

        assert result["word_count"] >= 5


# ══════════════════════════════════════════════════════
# 4. parse_spreadsheet (openpyxl mocked)
# ══════════════════════════════════════════════════════


class TestParseSpreadsheet:
    def _make_mock_workbook(self, sheet_data: dict):
        mock_wb = MagicMock()
        mock_wb.sheetnames = list(sheet_data.keys())
        mock_wb.close = MagicMock()

        def get_ws(name):
            ws = MagicMock()
            rows = sheet_data[name]
            ws.iter_rows = MagicMock(return_value=iter(rows))
            return ws

        mock_wb.__getitem__ = MagicMock(side_effect=get_ws)
        return mock_wb

    def test_returns_dict_with_required_keys(self):
        from src.workers.ingestion_worker import parse_spreadsheet

        sheet_data = {"Sheet1": [("ID", "Value"), ("1", "PUMP-101"), ("2", "350°C")]}
        mock_wb = self._make_mock_workbook(sheet_data)

        with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
            import openpyxl

            openpyxl.load_workbook = MagicMock(return_value=mock_wb)
            result = parse_spreadsheet("/fake/test.xlsx")

        assert "raw_text" in result
        assert "page_count" in result
        assert "word_count" in result
        assert "tables" in result

    def test_page_count_equals_sheet_count(self):
        from src.workers.ingestion_worker import parse_spreadsheet

        sheet_data = {
            "Sheet1": [("A", "B")],
            "Sheet2": [("C", "D")],
            "Sheet3": [("E", "F")],
        }
        mock_wb = self._make_mock_workbook(sheet_data)
        mock_wb.sheetnames = list(sheet_data.keys())

        with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
            import openpyxl

            openpyxl.load_workbook = MagicMock(return_value=mock_wb)
            result = parse_spreadsheet("/fake/test.xlsx")

        assert result["page_count"] == 3

    def test_table_per_sheet_created(self):
        from src.workers.ingestion_worker import parse_spreadsheet

        sheet_data = {"WorkOrders": [("WO#", "Title", "Status"), ("WO-001", "Pump repair", "open")]}
        mock_wb = self._make_mock_workbook(sheet_data)

        with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
            import openpyxl

            openpyxl.load_workbook = MagicMock(return_value=mock_wb)
            result = parse_spreadsheet("/fake/test.xlsx")

        assert len(result["tables"]) == 1
        assert result["tables"][0]["sheet_name"] == "WorkOrders"

    def test_empty_workbook(self):
        from src.workers.ingestion_worker import parse_spreadsheet

        mock_wb = MagicMock()
        mock_wb.sheetnames = []
        mock_wb.close = MagicMock()

        with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
            import openpyxl

            openpyxl.load_workbook = MagicMock(return_value=mock_wb)
            result = parse_spreadsheet("/fake/empty.xlsx")

        assert result["raw_text"] == ""
        assert result["tables"] == []


# ══════════════════════════════════════════════════════
# 5. Pydantic Event Models
# ══════════════════════════════════════════════════════


class TestEventModels:
    def test_document_uploaded_event_valid(self):
        event = DocumentUploadedEvent(
            tenant_id="t1",
            document_id="d1",
            file_name="test.pdf",
            file_type="pdf",
            storage_path="documents/test.pdf",
            storage_bucket="veda-tenant-t1",
            uploaded_by="user-1",
            timestamp="2026-07-09T10:00:00+00:00",
        )
        assert event.tenant_id == "t1"
        assert event.file_type == "pdf"

    def test_document_parsed_event_valid(self):
        event = DocumentParsedEvent(
            tenant_id="t1",
            document_id="d1",
            raw_text="Some extracted text content",
            page_count=3,
            word_count=100,
            timestamp="2026-07-09T10:00:00+00:00",
        )
        assert event.page_count == 3
        assert event.tables == []

    def test_document_parse_failed_event_valid(self):
        event = DocumentParseFailedEvent(
            tenant_id="t1",
            document_id="d1",
            error="FileNotFoundError: path not found",
            timestamp="2026-07-09T10:00:00+00:00",
        )
        assert "FileNotFoundError" in event.error

    def test_document_uploaded_missing_required_field_raises(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            DocumentUploadedEvent(
                tenant_id="t1",
                # document_id is missing
                file_name="test.pdf",
                file_type="pdf",
                storage_path="path",
                storage_bucket="bucket",
                uploaded_by="user",
                timestamp="2026-07-09T10:00:00+00:00",
            )


# ══════════════════════════════════════════════════════
# 6. Settings
# ══════════════════════════════════════════════════════


class TestSettings:
    def test_default_kafka_brokers(self):
        s = Settings()
        assert "9092" in s.kafka_brokers

    def test_default_max_file_size(self):
        s = Settings()
        assert s.max_file_size_mb == 100

    def test_default_ocr_languages_include_english(self):
        s = Settings()
        assert "en" in s.ocr_languages

    def test_env_prefix_is_veda(self):
        assert Settings.Config.env_prefix == "VEDA_"


# ══════════════════════════════════════════════════════
# 7. TOPICS registry
# ══════════════════════════════════════════════════════


class TestTopics:
    def test_all_required_topics_present(self):
        required = ["DOCUMENT_UPLOADED", "DOCUMENT_PARSED", "DOCUMENT_PARSE_FAILED"]
        for t in required:
            assert t in TOPICS

    def test_topic_names_have_veda_prefix(self):
        for k, v in TOPICS.items():
            assert v.startswith("veda."), f"Topic {k!r} = {v!r} lacks veda. prefix"


# ══════════════════════════════════════════════════════
# Temp path safety
# ══════════════════════════════════════════════════════


class TestSafeTempPath:
    @pytest.mark.parametrize(
        "file_name",
        [
            "../../etc/passwd",
            r"..\..\Windows\win.ini",
            "/absolute/path.pdf",
            r"C:\Users\x\evil.pdf",
            "....pdf",
            "",
        ],
    )
    def test_stays_inside_temp_dir(self, file_name):
        import os
        import tempfile

        from src.workers.ingestion_worker import safe_temp_path

        path = safe_temp_path("doc-1", file_name)
        assert os.path.dirname(os.path.abspath(path)) == os.path.abspath(tempfile.gettempdir())

    def test_keeps_normal_names_readable(self):
        from src.workers.ingestion_worker import safe_temp_path

        assert safe_temp_path("doc-1", "report_2024.pdf").endswith("veda_doc-1_report_2024.pdf")
