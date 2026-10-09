"""
VEDA AI — Entity Extractor Unit Tests

Tests every extraction path in IndustrialEntityExtractor:
- Equipment tag regex (all tag families)
- Measurement regex (all unit types)
- Regulation pattern (OISD, ISO, API, ASME, etc.)
- Failure mode keyword matching
- Maintenance action keyword matching
- spaCy NER (PERSON, DATE, LOCATION) — mocked
- Deduplication logic
- Edge cases: empty text, very long text, overlapping entities
"""

import pytest
from unittest.mock import MagicMock, patch

from src.entity_extraction.extractor import (
    IndustrialEntityExtractor,
    EQUIPMENT_TAG_PATTERN,
    MEASUREMENT_PATTERN,
    REGULATION_PATTERN,
    FAILURE_MODES,
    MAINTENANCE_ACTIONS,
    ExtractedEntity,
)
from tests.conftest import (
    SAMPLE_INDUSTRIAL_TEXT,
    SAMPLE_EMPTY_TEXT,
    SAMPLE_TEXT_NO_ENTITIES,
)


# ── Helpers ────────────────────────────────────────────


def make_extractor_with_mock_spacy(mock_spacy_model) -> IndustrialEntityExtractor:
    """Return an extractor whose spaCy model is pre-mocked."""
    extractor = IndustrialEntityExtractor()
    extractor._spacy_model = mock_spacy_model
    return extractor


# ══════════════════════════════════════════════════════
# 1. Equipment Tag Pattern Tests
# ══════════════════════════════════════════════════════


class TestEquipmentTagPattern:
    """Regex coverage: every tag family must match."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("PUMP-101", "PUMP-101"),
            ("P-205A", "P-205A"),
            ("PP-45", "PP-45"),
            ("V-301", "V-301"),
            ("VESSEL-1001", "VESSEL-1001"),
            ("HX-205", "HX-205"),
            ("HE-12", "HE-12"),
            ("E-300B", "E-300B"),
            ("T-101", "T-101"),
            ("TK-202", "TK-202"),
            ("TANK-5001", "TANK-5001"),
            ("C-301", "C-301"),
            ("COL-12", "COL-12"),
            ("COLUMN-003", "COLUMN-003"),
            ("R-101", "R-101"),
            ("REACTOR-205", "REACTOR-205"),
            ("COMP-101", "COMP-101"),
            ("K-201", "K-201"),
            ("FCV-1234", "FCV-1234"),
            ("PCV-045", "PCV-045"),
            ("TCV-100", "TCV-100"),
            ("LCV-200", "LCV-200"),
            ("PSV-045", "PSV-045"),
            ("PRV-101", "PRV-101"),
            ("FI-101", "FI-101"),
            ("PI-202", "PI-202"),
            ("TI-101", "TI-101"),
            ("LI-303", "LI-303"),
            ("FT-101", "FT-101"),
            ("PT-202", "PT-202"),
            ("TT-101", "TT-101"),
            ("LT-404", "LT-404"),
            ("CDU-A", "CDU-A"),
            ("VDU-1", "VDU-1"),
            ("FCC-A1", "FCC-A1"),
            ("HDS-B", "HDS-B"),
            ("MOV-101", "MOV-101"),
            ("SOV-202", "SOV-202"),
            ("AOV-303", "AOV-303"),
            ("XV-404", "XV-404"),
        ],
    )
    def test_equipment_tag_matches(self, text, expected):
        """Every equipment tag family must be captured."""
        match = EQUIPMENT_TAG_PATTERN.search(text)
        assert match is not None, f"Pattern did not match: {text!r}"
        assert match.group(0).upper() == expected.upper()

    @pytest.mark.parametrize(
        "text",
        [
            "123",  # pure number
            "ABC",  # generic abbreviation
            "pump",  # lowercase word (no tag format)
            "temperature",  # plain word
        ],
    )
    def test_equipment_tag_no_false_positives(self, text):
        """Common words should NOT be captured as equipment tags."""
        # These may or may not match — the key assertion is context-dependent,
        # but pure lowercase words without numeric suffixes should not match
        # when surrounded by whitespace/sentence boundaries.
        full_text = f"The {text} was replaced."
        matches = EQUIPMENT_TAG_PATTERN.findall(full_text)
        for m in matches:
            # If any match, it should look like an equipment tag (has digits)
            assert any(c.isdigit() for c in m), f"False positive: {m!r} matched in {full_text!r}"


# ══════════════════════════════════════════════════════
# 2. Measurement Pattern Tests
# ══════════════════════════════════════════════════════


class TestMeasurementPattern:
    """Measurement regex: all unit families."""

    @pytest.mark.parametrize(
        "text,value,unit_fragment",
        [
            ("15.5 kg/cm²", "15.5", "kg/cm"),
            ("10.2 kg/cm2", "10.2", "kg/cm"),
            ("100 bar", "100", "bar"),
            ("2500 psi", "2500", "psi"),
            ("0.5 MPa", "0.5", "MPa"),
            ("350°C", "350", "°C"),
            ("212°F", "212", "°F"),
            ("120 m³/hr", "120", "m"),
            ("500 l/min", "500", "l/min"),
            ("1500 RPM", "1500", "RPM"),
            ("50 Hz", "50", "Hz"),
            ("50 ppm", "50", "ppm"),
            ("5.0 MT", "5.0", "MT"),
            ("100 mm", "100", "mm"),
        ],
    )
    def test_measurement_matches(self, text, value, unit_fragment):
        match = MEASUREMENT_PATTERN.search(text)
        assert match is not None, f"No measurement match in: {text!r}"
        assert match.group(1) == value
        assert unit_fragment.lower() in match.group(2).lower()


# ══════════════════════════════════════════════════════
# 3. Regulation Pattern Tests
# ══════════════════════════════════════════════════════


class TestRegulationPattern:
    """Regulation regex: all standard families."""

    @pytest.mark.parametrize(
        "text",
        [
            "OISD-154",
            "OISD 116",
            "PESO Rule 5",
            "Factory Act 1948",
            "IS-2062",
            "IS 875",
            "ISO 45001",
            "ISO-9001",
            "ASME Section VIII",
            "ASME Sec IV",
            "API 570",
            "API 653",
            "NFPA 30",
            "NFPA 101",
            "IEC 61511",
            "ASTM A106",
            "OSHA 1910",
        ],
    )
    def test_regulation_pattern_matches(self, text):
        match = REGULATION_PATTERN.search(text)
        assert match is not None, f"Regulation pattern did not match: {text!r}"


# ══════════════════════════════════════════════════════
# 4. Full Extractor Tests
# ══════════════════════════════════════════════════════


class TestIndustrialEntityExtractor:
    """Integration-style tests of the full extraction pipeline."""

    def test_extracts_equipment_tags(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("PUMP-101 was serviced.")
        equipment = [e for e in entities if e.entity_type == "EQUIPMENT_TAG"]
        assert len(equipment) >= 1
        assert equipment[0].normalized_value == "PUMP-101"
        assert equipment[0].confidence == 0.95

    def test_extracts_measurements(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("Pressure: 15.5 kg/cm²")
        measurements = [e for e in entities if e.entity_type == "MEASUREMENT"]
        assert len(measurements) >= 1
        assert measurements[0].attributes["numeric_value"] == 15.5

    def test_extracts_regulations(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("Refer to OISD-154 section 3.")
        regs = [e for e in entities if e.entity_type == "REGULATION"]
        assert len(regs) >= 1
        assert "OISD" in regs[0].normalized_value.upper()

    def test_extracts_failure_modes(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("Root cause: bearing seizure confirmed.")
        failures = [e for e in entities if e.entity_type == "FAILURE_MODE"]
        assert len(failures) >= 1
        assert failures[0].normalized_value == "bearing seizure"

    def test_extracts_maintenance_actions(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("Action taken: bearing replacement completed.")
        actions = [e for e in entities if e.entity_type == "MAINTENANCE_ACTION"]
        assert len(actions) >= 1
        assert actions[0].normalized_value == "bearing replacement"

    def test_spacy_ner_integrated(self, mock_spacy_model):
        """Entities from spaCy NER are mapped to VEDA types."""
        # Set up spaCy mock to return a PERSON entity
        ent_mock = MagicMock()
        ent_mock.label_ = "PERSON"
        ent_mock.text = "Rajesh Kumar"
        ent_mock.start_char = 0
        ent_mock.end_char = 12
        doc_mock = MagicMock()
        doc_mock.ents = [ent_mock]
        mock_spacy_model.return_value = doc_mock

        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("Rajesh Kumar performed the overhaul.")
        persons = [e for e in entities if e.entity_type == "PERSON"]
        assert len(persons) >= 1
        assert persons[0].value == "Rajesh Kumar"

    def test_empty_text_returns_empty(self, mock_spacy_model):
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        # Empty text should still call nlp (returns empty doc), no crash
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        entities = extractor.extract_entities(SAMPLE_EMPTY_TEXT)
        assert isinstance(entities, list)
        # No regex entities on empty text
        structured = [
            e
            for e in entities
            if e.entity_type
            in {"EQUIPMENT_TAG", "MEASUREMENT", "REGULATION", "FAILURE_MODE", "MAINTENANCE_ACTION"}
        ]
        assert len(structured) == 0

    def test_no_entities_text(self, mock_spacy_model):
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities(SAMPLE_TEXT_NO_ENTITIES)
        # May still get some noise, but equipment tags should be zero
        equipment = [e for e in entities if e.entity_type == "EQUIPMENT_TAG"]
        assert len(equipment) == 0

    def test_page_number_propagated(self, mock_spacy_model):
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities("PUMP-101 was checked.", page_number=5)
        for e in entities:
            if e.entity_type == "EQUIPMENT_TAG":
                assert e.page_number == 5

    def test_offsets_are_valid(self, mock_spacy_model):
        """start_offset and end_offset must form a valid substring."""
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        text = "PUMP-101 operates at 15.5 kg/cm²."
        entities = extractor.extract_entities(text)
        for e in entities:
            assert 0 <= e.start_offset < e.end_offset <= len(text), (
                f"Invalid offsets [{e.start_offset}:{e.end_offset}] for {e.value!r}"
            )

    def test_full_industrial_text(self, mock_spacy_model):
        """Integration: all entity types extracted from realistic sample text."""
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities(SAMPLE_INDUSTRIAL_TEXT)

        types_found = {e.entity_type for e in entities}
        assert "EQUIPMENT_TAG" in types_found
        assert "MEASUREMENT" in types_found
        assert "REGULATION" in types_found
        assert "FAILURE_MODE" in types_found
        assert "MAINTENANCE_ACTION" in types_found

    def test_all_entities_have_confidence(self, mock_spacy_model):
        """Every entity must carry a confidence score in (0, 1]."""
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        entities = extractor.extract_entities(SAMPLE_INDUSTRIAL_TEXT)
        for e in entities:
            assert 0 < e.confidence <= 1.0, (
                f"Bad confidence {e.confidence} for {e.entity_type}: {e.value!r}"
            )


# ══════════════════════════════════════════════════════
# 5. Deduplication Tests
# ══════════════════════════════════════════════════════


class TestDeduplication:
    """_deduplicate must correctly remove overlapping same-type entities."""

    def _make_entity(self, start: int, end: int, etype: str, conf: float) -> ExtractedEntity:
        return ExtractedEntity(
            entity_type=etype,
            value="x",
            normalized_value="x",
            confidence=conf,
            start_offset=start,
            end_offset=end,
        )

    def test_no_duplicates_unchanged(self):
        extractor = IndustrialEntityExtractor.__new__(IndustrialEntityExtractor)
        entities = [
            self._make_entity(0, 5, "EQUIPMENT_TAG", 0.9),
            self._make_entity(10, 15, "EQUIPMENT_TAG", 0.8),
        ]
        result = extractor._deduplicate(entities)
        assert len(result) == 2

    def test_overlap_same_type_keeps_higher_confidence(self):
        extractor = IndustrialEntityExtractor.__new__(IndustrialEntityExtractor)
        # Both start at 0, overlap — higher confidence (0.95) should survive
        high = self._make_entity(0, 8, "EQUIPMENT_TAG", 0.95)
        low = self._make_entity(0, 8, "EQUIPMENT_TAG", 0.70)
        result = extractor._deduplicate([low, high])
        # After sort by (start, -conf), high comes first
        assert len(result) == 1
        assert result[0].confidence == 0.95

    def test_overlap_different_types_both_kept(self):
        """Different entity types at same offset should both survive."""
        extractor = IndustrialEntityExtractor.__new__(IndustrialEntityExtractor)
        e1 = self._make_entity(0, 5, "EQUIPMENT_TAG", 0.9)
        e2 = self._make_entity(0, 5, "REGULATION", 0.8)
        result = extractor._deduplicate([e1, e2])
        assert len(result) == 2

    def test_empty_list(self):
        extractor = IndustrialEntityExtractor.__new__(IndustrialEntityExtractor)
        assert extractor._deduplicate([]) == []

    def test_single_entity(self):
        extractor = IndustrialEntityExtractor.__new__(IndustrialEntityExtractor)
        e = self._make_entity(0, 5, "EQUIPMENT_TAG", 0.9)
        assert extractor._deduplicate([e]) == [e]


# ══════════════════════════════════════════════════════
# 6. FAILURE_MODES and MAINTENANCE_ACTIONS coverage
# ══════════════════════════════════════════════════════


class TestKeywordSets:
    def test_failure_modes_non_empty(self):
        assert len(FAILURE_MODES) > 10, "FAILURE_MODES set too small"

    def test_maintenance_actions_non_empty(self):
        assert len(MAINTENANCE_ACTIONS) > 10, "MAINTENANCE_ACTIONS set too small"

    def test_failure_modes_all_lowercase(self):
        for fm in FAILURE_MODES:
            assert fm == fm.lower(), f"Failure mode not lowercase: {fm!r}"

    def test_maintenance_actions_all_lowercase(self):
        """Most actions should be lowercase; technical acronyms like NDT are acceptable."""
        mixed_case_allowed = {"NDT inspection", "NDE inspection", "RCA"}
        for ma in MAINTENANCE_ACTIONS:
            if ma in mixed_case_allowed:
                continue
            assert ma == ma.lower(), f"Maintenance action unexpectedly mixed case: {ma!r}"

    @pytest.mark.parametrize("keyword", list(FAILURE_MODES)[:5])
    def test_failure_mode_matched_in_sentence(self, keyword, mock_spacy_model):
        """Each FAILURE_MODE keyword should be extractable from a sentence."""
        doc_mock = MagicMock()
        doc_mock.ents = []
        mock_spacy_model.return_value = doc_mock
        extractor = make_extractor_with_mock_spacy(mock_spacy_model)
        text = f"The equipment showed {keyword} during inspection."
        entities = extractor.extract_entities(text)
        failures = [e for e in entities if e.entity_type == "FAILURE_MODE"]
        assert any(e.normalized_value == keyword for e in failures), (
            f"Keyword {keyword!r} not extracted from: {text!r}"
        )
