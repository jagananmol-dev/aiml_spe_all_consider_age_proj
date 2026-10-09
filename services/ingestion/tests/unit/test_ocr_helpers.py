"""
VEDA AI — OCR post-processing tests

- _group_ocr_lines: boxes become reading-order lines
- _fix_tag_digits: "P-1O1A" → "P-101A", ordinary words untouched
- parse_image_ocr: works with EasyOCR's (bbox, text, confidence) results
"""

from unittest.mock import MagicMock, patch

from src.workers import ingestion_worker
from src.workers.ingestion_worker import _fix_tag_digits, _group_ocr_lines


def box(x, y, text, w=100, h=30, conf=0.9):
    return ([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], text, conf)


class TestGroupLines:
    def test_boxes_on_one_row_join_left_to_right(self):
        results = [box(300, 102, "Service: R-201"), box(10, 100, "Valve: PSV-210")]
        assert _group_ocr_lines(results) == ["Valve: PSV-210 Service: R-201"]

    def test_rows_are_ordered_top_to_bottom(self):
        results = [box(10, 200, "second"), box(10, 100, "first"), box(10, 300, "third")]
        assert _group_ocr_lines(results) == ["first", "second", "third"]

    def test_empty(self):
        assert _group_ocr_lines([]) == []


class TestFixTagDigits:
    def test_letter_o_in_tag_number_becomes_zero(self):
        assert _fix_tag_digits("Equipment tag: P-1O1A") == "Equipment tag: P-101A"
        assert _fix_tag_digits("Valve PSV-21O") == "Valve PSV-210"

    def test_tokens_without_digits_are_untouched(self):
        assert _fix_tag_digits("CO-OP and NO-GO") == "CO-OP and NO-GO"

    def test_plain_words_are_untouched(self):
        assert _fix_tag_digits("Owner: Aranya, Dahej 2019") == "Owner: Aranya, Dahej 2019"


def test_parse_image_ocr_builds_lines():
    reader = MagicMock()
    reader.readtext.return_value = [box(10, 10, "NAMEPLATE"), box(10, 60, "Tag: P-1O1A")]
    with (
        patch.object(ingestion_worker, "_easyocr_reader", reader),
        patch.dict("sys.modules", {"easyocr": MagicMock(), "torch": MagicMock()}),
    ):
        result = ingestion_worker.parse_image_ocr("scan.png")
    assert result["raw_text"] == "NAMEPLATE\nTag: P-101A"
    assert result["word_count"] == 3
    assert result["ocr_details"][0]["confidence"] == 0.9
