"""
VEDA AI — Entity Extraction Pipeline

Domain-agnostic entity extraction. What to look for comes from the
knowledge-graph schema (graph_schema.json, extendable per tenant — see
schema.py), never from this file:

1. Schema patterns: structured entities (asset codes, measurements,
   regulations). Shipped with plant and healthcare patterns as defaults.
2. Schema terms: exact, whole-word vocabulary per type.
3. Embeddings (semantic.py): key phrases nobody listed are typed by their
   most similar schema example, unknown codes by the words around them, and
   near-duplicates ("anemia" / "anaemia") merge into one entity. Runs when the
   RAG pipeline has registered its embedding model.
4. spaCy NER for persons, dates, locations and organisations, if installed.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from . import semantic
from .schema import GraphSchema, get_schema

logger = logging.getLogger("veda.intelligence.entity_extraction")


@dataclass
class ExtractedEntity:
    """A single extracted entity from a document."""

    entity_type: str
    value: str
    normalized_value: str
    confidence: float
    start_offset: int
    end_offset: int
    page_number: Optional[int] = None
    attributes: dict = field(default_factory=dict)


def _normalize(value: str, how: str) -> str:
    if how in ("upper", "upper_dash"):
        return value.upper().replace(" ", "-")
    if how == "lower":
        return value.lower()
    return value.strip()


# Compiled default patterns and vocabularies, kept as module names for callers
# and tests that inspect them directly
_DEFAULT = get_schema()
_PATTERNS_BY_TYPE: dict = {}
for _p in _DEFAULT.patterns:
    _PATTERNS_BY_TYPE.setdefault(_p.entity_type, _p.regex)
EQUIPMENT_TAG_PATTERN = _PATTERNS_BY_TYPE.get("EQUIPMENT_TAG")
MEASUREMENT_PATTERN = _PATTERNS_BY_TYPE.get("MEASUREMENT")
REGULATION_PATTERN = _PATTERNS_BY_TYPE.get("REGULATION")
FAILURE_MODES = (
    set(_DEFAULT.types["FAILURE_MODE"].terms) if "FAILURE_MODE" in _DEFAULT.types else set()
)
MAINTENANCE_ACTIONS = (
    set(_DEFAULT.types["MAINTENANCE_ACTION"].terms)
    if "MAINTENANCE_ACTION" in _DEFAULT.types
    else set()
)

SPACY_TYPE_MAP = {
    "PERSON": "PERSON",
    "DATE": "DATE",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "FAC": "LOCATION",
    "ORG": "ORGANIZATION",
    "QUANTITY": "MEASUREMENT",
}


class EntityExtractor:
    """Schema-driven extraction: patterns, terms, embeddings, then spaCy NER."""

    def __init__(self):
        self._spacy_model = None
        self._spacy_unavailable = False

    @property
    def nlp(self):
        """
        Lazy-load a spaCy model. Returns None when no model is installed, in
        which case the other steps still run and only general NER (persons,
        dates, locations) is skipped.
        """
        if self._spacy_model is None and not self._spacy_unavailable:
            try:
                import spacy
            except ImportError:
                logger.warning("spaCy not installed — skipping general NER")
                self._spacy_unavailable = True
                return None
            for model_name in ("en_core_web_trf", "en_core_web_sm"):
                try:
                    self._spacy_model = spacy.load(model_name)
                    break
                except OSError:
                    continue
            else:
                logger.warning(
                    "No spaCy model installed — skipping general NER. "
                    "Install one with: python -m spacy download en_core_web_sm"
                )
                self._spacy_unavailable = True
        return self._spacy_model

    def extract_entities(
        self,
        text: str,
        page_number: int | None = None,
        schema: GraphSchema | None = None,
        known_nodes: dict[str, list[str]] | None = None,
    ) -> list[ExtractedEntity]:
        """
        Extract all entity types from the given text.

        Args:
            text: The document text to process
            page_number: Optional page number for position tracking
            schema: The tenant's graph schema (default: the base schema)
            known_nodes: The tenant's existing node values by type; a new
                phrase close enough to one of them reuses its name, so the
                same thing becomes one node across documents
        """
        schema = schema or get_schema()
        entities: list[ExtractedEntity] = []

        # 1. Schema patterns
        for p in schema.patterns:
            for match in p.regex.finditer(text):
                attributes = {}
                if p.numeric:
                    try:
                        attributes = {
                            "numeric_value": float(match.group(1)),
                            "unit": match.group(2),
                        }
                    except (IndexError, ValueError, TypeError):
                        attributes = {}
                entities.append(
                    ExtractedEntity(
                        entity_type=p.entity_type,
                        value=match.group(0),
                        normalized_value=_normalize(match.group(0), p.normalize),
                        confidence=p.confidence,
                        start_offset=match.start(),
                        end_offset=match.end(),
                        page_number=page_number,
                        attributes=attributes,
                    )
                )

        # 2. Schema terms (whole-word)
        for entity_type, pattern in schema.term_patterns:
            for match in pattern.finditer(text):
                entities.append(
                    ExtractedEntity(
                        entity_type=entity_type,
                        value=match.group(0),
                        normalized_value=match.group(0).lower(),
                        confidence=0.85,
                        start_offset=match.start(),
                        end_offset=match.end(),
                        page_number=page_number,
                    )
                )

        # 3. Embeddings: phrases and codes nobody listed
        typer = semantic.get_typer(schema)
        if typer is not None and text.strip():
            try:
                entities.extend(self._semantic_entities(text, page_number, schema, typer, entities))
                entities = self._merge_near_duplicates(entities, schema, typer, known_nodes or {})
            except Exception as e:  # typing is an enrichment: never fail extraction
                logger.warning(f"Semantic entity typing skipped: {e}")

        # 4. spaCy NER for general entities (persons, dates, locations, orgs)
        nlp = self.nlp
        doc_ents = nlp(text[:100000]).ents if nlp is not None else ()  # 100k char cap
        for ent in doc_ents:
            mapped_type = SPACY_TYPE_MAP.get(ent.label_)
            if mapped_type:
                entities.append(
                    ExtractedEntity(
                        entity_type=mapped_type,
                        value=ent.text,
                        normalized_value=ent.text.strip(),
                        confidence=0.80,
                        start_offset=ent.start_char,
                        end_offset=ent.end_char,
                        page_number=page_number,
                    )
                )

        entities = self._deduplicate(entities)
        logger.info(f"Extracted {len(entities)} entities from text ({len(text)} chars)")
        return entities

    def _semantic_entities(
        self,
        text: str,
        page_number: int | None,
        schema: GraphSchema,
        typer: semantic.SemanticTyper,
        found: list[ExtractedEntity],
    ) -> list[ExtractedEntity]:
        cfg = schema.semantic
        taken = [(e.start_offset, e.end_offset) for e in found]

        def overlaps(start: int, end: int) -> bool:
            return any(s < end and start < e for s, e in taken)

        out: list[ExtractedEntity] = []
        cap = float(cfg.get("confidence_cap", 0.8))

        # Key phrases → the type of their nearest example
        candidates = [
            c
            for c in semantic.candidate_phrases(
                text,
                max_words=int(cfg.get("max_phrase_words", 4)),
                min_chars=int(cfg.get("min_phrase_chars", 4)),
                limit=int(cfg.get("max_candidates_per_document", 400)),
            )
            if any(not overlaps(s, e) for s, e in c.spans)
        ]
        for cand, typed in zip(candidates, typer.classify([c.phrase for c in candidates])):
            if typed is None:
                continue
            entity_type, score = typed
            for start, end in cand.spans:
                if overlaps(start, end):
                    continue
                out.append(
                    ExtractedEntity(
                        entity_type=entity_type,
                        value=text[start:end],
                        normalized_value=cand.phrase,
                        confidence=round(min(score, cap), 3),
                        start_offset=start,
                        end_offset=end,
                        page_number=page_number,
                        attributes={"source": "embedding", "similarity": round(score, 3)},
                    )
                )

        # Unknown codes → typed by the words around them
        if schema.identifier_regex is not None:
            codes = [
                m
                for m in schema.identifier_regex.finditer(text)
                if any(c.isdigit() for c in m.group(1)) and not overlaps(m.start(1), m.end(1))
            ]
            with_context = [
                (m, ctx)
                for m in codes
                if (ctx := semantic.identifier_context(text, m.start(1), m.end(1)))
            ]
            typed_codes = typer.classify_identifiers([ctx for _, ctx in with_context])
            for (m, _), typed in zip(with_context, typed_codes):
                if typed is None:
                    continue
                entity_type, score = typed
                out.append(
                    ExtractedEntity(
                        entity_type=entity_type,
                        value=m.group(1),
                        normalized_value=m.group(1).upper(),
                        confidence=round(min(score, cap), 3),
                        start_offset=m.start(1),
                        end_offset=m.end(1),
                        page_number=page_number,
                        attributes={"source": "embedding-context", "similarity": round(score, 3)},
                    )
                )
        return out

    def _merge_near_duplicates(
        self,
        entities: list[ExtractedEntity],
        schema: GraphSchema,
        typer: semantic.SemanticTyper,
        known_nodes: dict[str, list[str]],
    ) -> list[ExtractedEntity]:
        """
        Give near-identical names of one type a single normalised value.
        Existing node names come first, then higher-confidence names, so they
        win as the canonical name. Pattern and identifier types are never
        merged (P-101A and P-101B are different machines).
        """
        threshold = float(schema.semantic.get("merge_similarity", 0.9))
        skip = {p.entity_type for p in schema.patterns} | {
            t.name for t in schema.types.values() if t.identifier
        }
        best: dict[tuple[str, str], float] = {}
        curated: set[tuple[str, str]] = set()
        for e in entities:
            if e.entity_type not in skip:
                key = (e.entity_type, e.normalized_value)
                best[key] = max(best.get(key, 0.0), e.confidence)
                if not e.attributes.get("source", "").startswith("embedding"):
                    curated.add(key)

        for entity_type in {t for t, _ in best}:
            ranked = sorted(
                (v for t, v in best if t == entity_type), key=lambda v: -best[(entity_type, v)]
            )
            values = list(dict.fromkeys([*known_nodes.get(entity_type, []), *ranked]))
            if len(values) < 2:
                continue
            protected = {v for t, v in curated if t == entity_type}
            mapping = semantic.merge_similar(
                values, typer.cache.encode(values), threshold, protected
            )
            for e in entities:
                if (
                    e.entity_type == entity_type
                    and (e.entity_type, e.normalized_value) not in curated
                ):
                    canonical = mapping.get(e.normalized_value, e.normalized_value)
                    if canonical != e.normalized_value:
                        e.attributes = {**e.attributes, "merged_from": e.normalized_value}
                        e.normalized_value = canonical
        return entities

    def _deduplicate(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        """Remove duplicate entities at overlapping positions, keeping highest confidence."""
        if not entities:
            return entities

        # Sort by start offset, then by confidence (highest first)
        entities.sort(key=lambda e: (e.start_offset, -e.confidence))

        deduplicated = [entities[0]]
        for entity in entities[1:]:
            last = deduplicated[-1]
            # Skip if overlapping with previous entity of same type
            if entity.start_offset < last.end_offset and entity.entity_type == last.entity_type:
                continue
            deduplicated.append(entity)

        return deduplicated


# Former name, kept for existing imports
IndustrialEntityExtractor = EntityExtractor

# Singleton instance
extractor = EntityExtractor()
