"""
Schema-driven graph and embedding-based entity typing.

A deterministic bag-of-words encoder stands in for the sentence model:
phrases sharing words are similar, so the tests check the logic (typing,
thresholds, merging, linking), not the model.
"""

import hashlib

import numpy as np
import pytest

from src.entity_extraction import semantic
from src.entity_extraction.extractor import EntityExtractor
from src.entity_extraction.schema import get_schema, merge_schema
from src.knowledge_graph.relationships import infer_relationships


def fake_encode(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for i, text in enumerate(texts):
        for word in text.lower().replace("-", " ").split():
            out[i, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
        norm = np.linalg.norm(out[i])
        if norm:
            out[i] /= norm
    return out


@pytest.fixture
def encoder():
    calls: list[int] = []

    def counting(texts):
        calls.append(len(texts))
        return fake_encode(texts)

    semantic.set_encoder(counting)
    yield calls
    semantic.set_encoder(None)


class TestSchema:
    def test_tenant_extension_adds_types_terms_and_rules(self):
        schema = get_schema(
            {
                "types": {
                    "LOAN": {"label": "Loan", "role": "subject", "terms": ["term loan"]},
                    "FAILURE_MODE": {"terms": ["npa classification"]},
                },
                "relationships": [
                    {"source": "LOAN", "target": "FAILURE_MODE", "type": "HAS_ISSUE"}
                ],
            }
        )
        assert "LOAN" in schema.subject_types and "EQUIPMENT_TAG" in schema.subject_types
        assert "npa classification" in schema.types["FAILURE_MODE"].terms
        assert "bearing seizure" in schema.types["FAILURE_MODE"].terms  # base terms kept
        assert schema.rules[("LOAN", "FAILURE_MODE")] == "HAS_ISSUE"

        text = "The term loan moved to NPA classification in June."
        entities = [e.__dict__ for e in EntityExtractor().extract_entities(text, schema=schema)]
        edges = infer_relationships(entities, text, schema)
        assert [
            (e.source["normalized_value"], e.relationship_type, e.target["normalized_value"])
            for e in edges
        ] == [("term loan", "HAS_ISSUE", "npa classification")]

    def test_merge_leaves_base_untouched(self):
        base = {"types": {"A": {"terms": ["x"]}}, "relationships": []}
        merged = merge_schema(base, {"types": {"A": {"terms": ["y"]}}})
        assert merged["types"]["A"]["terms"] == ["x", "y"] and base["types"]["A"]["terms"] == ["x"]

    def test_public_types_carry_labels_and_roles(self):
        types = get_schema().public_types()
        assert types["EQUIPMENT_TAG"]["role"] == "subject" and types["FAILURE_MODE"]["label"]


class TestCandidatePhrases:
    def test_runs_break_on_stop_words_verbs_codes_and_underscores(self):
        text = "Vancomycin given after a payment default on LN-2041; endotoxin_eu_ml rose."
        phrases = {c.phrase for c in semantic.candidate_phrases(text)}
        assert "payment default" in phrases
        assert not any("given" in p or "ln-2041" in p or "_" in p for p in phrases)

    def test_repeated_phrases_rank_first_and_keep_every_span(self):
        text = "data breach. data breach again. vendor portal."
        first = semantic.candidate_phrases(text)[0]
        assert first.phrase == "data breach" and len(first.spans) == 2


class TestSemanticTyping:
    def test_unlisted_multiword_phrases_are_typed_by_nearest_example(self, encoder):
        text = "Kestrel saw a payment default and a data breach; a vendor audit followed."
        found = {
            (e.entity_type, e.normalized_value)
            for e in EntityExtractor().extract_entities(text)
            if e.attributes.get("source") == "embedding"
        }
        assert ("FAILURE_MODE", "payment default") in found
        assert ("FAILURE_MODE", "data breach") in found
        assert ("MAINTENANCE_ACTION", "vendor audit") in found

    def test_single_words_and_record_nouns_are_not_typed(self, encoder):
        text = "An alarm was raised. See the incident report."
        typed = [
            e
            for e in EntityExtractor().extract_entities(text)
            if e.attributes.get("source") == "embedding"
        ]
        assert typed == []

    def test_codes_are_typed_by_the_words_before_them(self, encoder):
        text = "Loan account LN-2041 shows a payment default.\nRisk RSK-02 was rated 12."
        entities = EntityExtractor().extract_entities(text)
        codes = {
            e.normalized_value: e.entity_type
            for e in entities
            if e.attributes.get("source") == "embedding-context"
        }
        assert codes == {"LN-2041": "EQUIPMENT_TAG"}
        edges = infer_relationships([e.__dict__ for e in entities], text)
        assert ("LN-2041", "FAILED_WITH", "payment default") in {
            (e.source["normalized_value"], e.relationship_type, e.target["normalized_value"])
            for e in edges
        }

    def test_curated_terms_are_never_merged_into_each_other(self, encoder):
        text = "RO-H1 had heat disinfection, then chemical disinfection, then disinfection."
        actions = {
            e.normalized_value
            for e in EntityExtractor().extract_entities(text)
            if e.entity_type == "MAINTENANCE_ACTION"
        }
        assert {"heat disinfection", "chemical disinfection", "disinfection"} <= actions

    def test_new_phrase_joins_an_existing_node(self, encoder):
        text = "A repeated payment default was logged."
        entities = EntityExtractor().extract_entities(
            text, known_nodes={"FAILURE_MODE": ["payment default"]}
        )
        assert any(
            e.normalized_value == "payment default"
            for e in entities
            if e.entity_type == "FAILURE_MODE"
        )

    def test_phrases_are_embedded_once(self, encoder):
        text = "A payment default and a data breach."
        EntityExtractor().extract_entities(text)
        before = sum(encoder)
        EntityExtractor().extract_entities(text)
        assert sum(encoder) == before  # second run is served from the cache

    def test_without_an_encoder_only_patterns_and_terms_run(self):
        semantic.set_encoder(None)
        entities = EntityExtractor().extract_entities("A payment default hit PUMP-101.")
        assert {e.entity_type for e in entities} == {"EQUIPMENT_TAG"}


class TestSearchBoost:
    def test_boost_lifts_chunks_that_name_a_linked_entity(self):
        from unittest.mock import patch

        from src.rag import local_store

        index = local_store._TenantIndex(
            fingerprint=(),
            rows=[
                ("d1", "General notes about water.", {}, "a"),
                ("d2", "HD-K04 conductivity alarm.", {}, "b"),
            ],
            matrices={
                2: (np.asarray([0, 1]), np.asarray([[1.0, 0.0], [0.96, 0.28]], dtype=np.float32))
            },
            documents=2,
        )
        with (
            patch.object(local_store, "_reused_connection"),
            patch.object(local_store, "_tenant_index", return_value=index),
        ):
            plain, _ = local_store.search_chunks_with_stats("db", "t", [1.0, 0.0], 1)
            boosted, stats = local_store.search_chunks_with_stats(
                "db", "t", [1.0, 0.0], 1, boost={"d2": {"hd-k04"}}, boost_amount=0.05
            )
        assert plain[0]["document_id"] == "d1"
        assert boosted[0]["document_id"] == "d2" and stats["graph_boosted_chunks"] == 1
