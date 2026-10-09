"""
VEDA AI — Relationship inference and local graph tests

- Entities only relate inside one sentence or record block
- Keyword extraction is whole-word ("alignment" not inside "misalignment")
- local_graph.walk returns real edges only and never walks through measurements
"""

from src.entity_extraction.extractor import IndustrialEntityExtractor
from src.knowledge_graph.local_graph import walk
from src.knowledge_graph.relationships import infer_relationships, text_segments

extractor = IndustrialEntityExtractor()
extractor._spacy_unavailable = True


def edges_for(text: str) -> set[tuple[str, str, str]]:
    entities = [
        {
            "entity_type": e.entity_type,
            "value": e.value,
            "normalized_value": e.normalized_value,
            "confidence": e.confidence,
            "start_offset": e.start_offset,
        }
        for e in extractor.extract_entities(text)
    ]
    return {
        (e.source["normalized_value"], e.relationship_type, e.target["normalized_value"])
        for e in infer_relationships(entities, text)
    }


class TestSegments:
    def test_sentences_are_separate(self):
        text = "P-101A tripped on bearing failure. P-101B was started and ran normally."
        edges = edges_for(text)
        assert ("P-101A", "FAILED_WITH", "bearing failure") in edges
        assert not any(src == "P-101B" and rel == "FAILED_WITH" for src, rel, _ in edges)

    def test_record_block_is_one_segment(self):
        text = (
            "equipment_tag: E-301\nproblem: fouling\naction: chemical cleaning\n\n"
            "equipment_tag: K-601\nproblem: overheating\naction: oil change"
        )
        edges = edges_for(text)
        assert ("E-301", "FAILED_WITH", "fouling") in edges
        assert ("K-601", "MAINTAINED_BY", "oil change") in edges
        assert ("E-301", "FAILED_WITH", "overheating") not in edges
        assert ("K-601", "FAILED_WITH", "fouling") not in edges

    def test_flattened_json_items_are_separate_records(self):
        text = (
            "site.equipment[0].tag: P-101A\nsite.equipment[0].description: pump, 45 kW\n"
            "site.equipment[1].tag: K-601\nsite.equipment[1].description: compressor, 55 kW"
        )
        edges = edges_for(text)
        assert ("P-101A", "HAS_MEASUREMENT", "45 kW") in edges
        assert ("K-601", "HAS_MEASUREMENT", "55 kW") in edges
        assert ("P-101A", "HAS_MEASUREMENT", "55 kW") not in edges
        assert not any(rel == "CO_OCCURS_WITH" for _, rel, _ in edges)

    def test_co_occurrence_is_stored_once(self):
        edges = edges_for("R-201 is protected by PSV-210.\nPSV-210 protects R-201.")
        assert [e for e in edges if e[1] == "CO_OCCURS_WITH"] == [("PSV-210", "CO_OCCURS_WITH", "R-201")]

    def test_velocity_keeps_its_unit(self):
        assert ("P-101A", "HAS_MEASUREMENT", "7.8 mm/s") in edges_for("P-101A tripped at 7.8 mm/s.")

    def test_decimal_points_do_not_split_sentences(self):
        assert len(text_segments("Vibration on P-101A reached 7.8 mm/s today.")) == 1

    def test_without_text_whole_list_is_one_segment(self):
        entities = [
            {"entity_type": "EQUIPMENT_TAG", "normalized_value": "P-1", "confidence": 1},
            {"entity_type": "FAILURE_MODE", "normalized_value": "leak", "confidence": 1},
        ]
        assert [e.relationship_type for e in infer_relationships(entities)] == ["FAILED_WITH"]

    def test_inspection_detects_rather_than_repairs(self):
        edges = edges_for("Nozzle pitting was found during the inspection.")
        assert ("pitting", "DETECTED_BY", "inspection") in edges
        assert ("pitting", "REPAIRED_BY", "inspection") not in edges

    def test_no_self_co_occurrence(self):
        assert not any(rel == "CO_OCCURS_WITH" for _, rel, _ in edges_for("P-101A and P-101A."))


class TestHealthcareVocabulary:
    def test_dialysis_machine_alarm_and_repair(self):
        edges = edges_for("HD-K04 had a conductivity alarm at 15.6 mS/cm. "
                          "HD-K04 received a conductivity cell replacement.")
        assert ("HD-K04", "FAILED_WITH", "conductivity alarm") in edges
        assert ("HD-K04", "HAS_MEASUREMENT", "15.6 mS/cm") in edges
        assert ("HD-K04", "MAINTAINED_BY", "conductivity cell replacement") in edges

    def test_water_plant_units(self):
        edges = edges_for("RO-H1 product water showed endotoxin exceedance at 0.31 EU/mL.")
        assert ("RO-H1", "FAILED_WITH", "endotoxin exceedance") in edges
        assert ("RO-H1", "HAS_MEASUREMENT", "0.31 EU/mL") in edges

    def test_condition_treated_with_medicine(self):
        edges = edges_for("The catheter-related bloodstream infection was treated with vancomycin.")
        assert ("catheter-related bloodstream infection", "TREATED_WITH", "vancomycin") in edges

    def test_health_regulations(self):
        types = {(e.entity_type, e.normalized_value) for e in extractor.extract_entities(
            "Records are kept as required by NABH and the Bio-Medical Waste Management Rules 2016.")}
        assert ("REGULATION", "NABH") in types
        assert ("REGULATION", "BIO-MEDICAL-WASTE-MANAGEMENT-RULES-2016") in types


class TestOverview:
    def test_nodes_and_edges_with_documents_and_degree(self):
        from unittest.mock import MagicMock, patch

        from src.knowledge_graph import local_graph

        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            ("k4", "EQUIPMENT_TAG", "HD-K04", "ca", "FAILURE_MODE", "conductivity alarm",
             "FAILED_WITH", 0.9, ["log.csv", "shift.txt"]),
            ("k4", "EQUIPMENT_TAG", "HD-K04", "cr", "MAINTENANCE_ACTION", "conductivity cell replacement",
             "MAINTAINED_BY", 0.9, ["job.docx"]),
        ]
        with patch.object(local_graph, "_connect", return_value=conn):
            graph = local_graph.overview("db", "tenant-1")

        degree = {n["label"]: n["degree"] for n in graph["nodes"]}
        assert degree == {"HD-K04": 2, "conductivity alarm": 1, "conductivity cell replacement": 1}
        assert graph["edges"][0] == {"source": "k4", "target": "ca", "relationship": "FAILED_WITH",
                                     "confidence": 0.9, "documents": ["log.csv", "shift.txt"]}
        sql, params = conn.execute.call_args_list[-1].args
        assert "e.tenant_id = %s::uuid" in sql and params[0] == "tenant-1"


class TestChunkMerging:
    def test_small_sections_merge_up_to_the_size_limit(self):
        from src.knowledge_graph.chunk_builder import ChunkBuilder

        builder = ChunkBuilder(max_chunk_size=120)
        text = ("Patient: PMP-0412. Centre: Pimpri.\n\n# Diagnosis and treatment\n\n"
                "The infection was treated with vancomycin.\n\n# Note\n\n" + "x" * 100)
        chunks = builder.merge_small_chunks(builder.split_into_chunks(text, "d1", {"title": "case.docx"}))
        assert "Pimpri" in chunks[0].text and "vancomycin" in chunks[0].text
        assert all(len(c.text) <= 120 for c in chunks if "x" * 100 not in c.text)
        assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
        assert all(c.metadata["title"] == "case.docx" for c in chunks)


class TestKeywordBoundaries:
    def test_alignment_not_found_inside_misalignment(self):
        values = {(e.entity_type, e.normalized_value) for e in extractor.extract_entities(
            "Root cause was misalignment of the coupling."
        )}
        assert ("FAILURE_MODE", "misalignment") in values
        assert ("MAINTENANCE_ACTION", "alignment") not in values

    def test_lowercase_is_is_not_a_standard(self):
        types = {e.entity_type for e in extractor.extract_entities("The batch size is 500 litres.")}
        assert "REGULATION" not in types

    def test_in_is_not_a_unit(self):
        values = [e.value for e in extractor.extract_entities("We keep 4 in stock.")]
        assert "4 in" not in values


def row(sid, stype, sval, tid, ttype, tval, rel):
    return (sid, stype, sval, tid, ttype, tval, rel, 0.9, "doc-1")


ROWS = [
    row("p", "EQUIPMENT_TAG", "P-101A", "bf", "FAILURE_MODE", "bearing failure", "FAILED_WITH"),
    row("p", "EQUIPMENT_TAG", "P-101A", "mm", "MEASUREMENT", "0.05 mm", "OPERATES_AT"),
    row("r", "EQUIPMENT_TAG", "R-201", "mm", "MEASUREMENT", "0.05 mm", "OPERATES_AT"),
    row("bf", "FAILURE_MODE", "bearing failure", "br", "MAINTENANCE_ACTION",
        "bearing replacement", "REPAIRED_BY"),
]


class TestWalk:
    def test_walks_real_edges_from_the_start_node(self):
        results = walk(ROWS, "p-101a", None, 2, 50)
        assert results[0]["source_value"] == "P-101A"
        pairs = {(r["source_value"], r["relationship"], r["target_value"]) for r in results}
        assert ("P-101A", "FAILED_WITH", "bearing failure") in pairs
        assert ("bearing failure", "REPAIRED_BY", "bearing replacement") in pairs

    def test_measurements_are_leaves(self):
        targets = {r["target_value"] for r in walk(ROWS, "P-101A", None, 3, 50)}
        assert "R-201" not in targets

    def test_shared_concepts_do_not_link_equipment(self):
        rows = ROWS + [
            row("k", "EQUIPMENT_TAG", "K-601", "bf", "FAILURE_MODE", "bearing failure", "FAILED_WITH"),
        ]
        targets = {r["target_value"] for r in walk(rows, "P-101A", None, 3, 50)}
        assert "bearing replacement" in targets  # concept → concept is fine
        assert "K-601" not in targets
        # ...but starting from the concept shows every machine that had it
        assert {"P-101A", "K-601"} <= {r["target_value"] for r in walk(rows, "bearing failure", None, 1, 50)}

    def test_inverse_names_when_walking_backwards(self):
        results = walk(ROWS, "bearing failure", None, 1, 50)
        assert {"source_value": "bearing failure", "target_value": "P-101A"}.items() <= {
            k: v for r in results if r["target_value"] == "P-101A" for k, v in r.items()
        }.items()
        assert any(r["relationship"] == "FAILURE_OF" for r in results)

    def test_unknown_entity_returns_nothing(self):
        assert walk(ROWS, "NOPE", None, 2, 50) == []

    def test_respects_hop_limit(self):
        assert {r["distance"] for r in walk(ROWS, "P-101A", None, 1, 50)} == {1}


def test_tag_inside_another_hyphenated_code_is_ignored():
    values = {e.normalized_value for e in extractor.extract_entities(
        "See BME_Job_Report_BME-2026-0311_HD-K04.docx. HD-K04 was repaired.")}
    assert "HD-K04" in values
    assert "K04" not in values
