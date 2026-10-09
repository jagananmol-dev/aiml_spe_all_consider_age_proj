"""
VEDA AI — Entity Extraction Pipeline

Domain-agnostic entity extraction. What to look for comes from the
knowledge-graph schema (graph_schema.json, extendable per tenant — see
schema.py), never from this file:

1. Schema patterns: structured entities (asset codes, measurements,
   regulations). Shipped with plant and healthcare patterns as defaults.
2. Schema terms: exact, whole-word vocabulary per type.
3. spaCy NER (if a model is installed): people and places, with the
   label → type map from the schema's "nlp" block.
4. Embeddings (semantic.py): key phrases nobody listed are typed by their
   most similar schema example, unknown codes by the words around them, and
   near-duplicates ("anemia" / "anaemia") merge into one entity. Runs when the
   RAG pipeline has registered its embedding model.

spaCy parses a document once; that one parse gives the named entities, the
noun chunks used as candidate phrases, and the lemmas that make "alarms" and
"alarm" one node.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

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
    page_number: int | None = None
    attributes: dict = field(default_factory=dict)


def _normalize(value: str, how: str) -> str:
    if how in ("upper", "upper_dash"):
        return "-".join(value.upper().split())  # any whitespace, line breaks included
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

# Default NER label → entity type map; the schema's nlp.ner_labels overrides it
SPACY_TYPE_MAP = {"PERSON": "PERSON", "GPE": "LOCATION", "LOC": "LOCATION", "FAC": "LOCATION"}


def _clean_name(span, entity_type: str) -> str | None:
    """
    A named entity's display name, or None when it does not look like one.
    Small NER models tag headings and table cells ("Appendix", "Board Note")
    as names, so a name must be 1–4 capitalised, letters-only words that the
    tagger also reads as proper nouns, and a person needs a full name.
    """
    name = " ".join(span.text.replace("’s", "").replace("'s", "").split())
    words = name.split()
    if not 1 <= len(words) <= 4 or len(name) < 3:
        return None
    if entity_type == "PERSON" and len(words) < 2:
        return None
    if any(not w[0].isupper() or not w.replace("-", "").replace(".", "").isalpha() for w in words):
        return None
    if any(t.pos_ not in ("PROPN", "PUNCT") for t in span):
        return None
    return name


CUE_WEIGHT = 3
CONJ_WEIGHT = 2


def _cue_type(text: str, start: int, cues: dict[str, list[str]]) -> str | None:
    """The type whose cue ends the text just before a name on its line ("Owner:", "Reported by")."""
    line_start = text.rfind("\n", 0, start) + 1
    before = text[max(line_start, start - 30) : start].lower().rstrip(" :,-–—\t")
    for entity_type, words in cues.items():
        for cue in words:
            if before == cue or before.endswith((" " + cue, "." + cue, "\t" + cue)):
                return entity_type
    return None


def ner_mentions(doc, schema: GraphSchema) -> list[tuple[Any, str, str]]:
    """
    (span, clean name, type vote) for every usable named entity in a parse.
    A context cue before the name adds CUE_WEIGHT extra votes for its type.
    """
    labels = schema.nlp.get("ner_labels", SPACY_TYPE_MAP)
    cues = schema.nlp.get("type_cues", {})
    ents = [e for e in doc.ents if labels.get(e.label_)]
    # Token index → the type its entity was labelled, for coordination votes
    token_type = {t.i: labels[e.label_] for e in ents for t in e}
    out = []
    for ent in ents:
        mapped_type = labels[ent.label_]
        cued = (
            _cue_type(doc.text, ent.start_char, cues)
            if cues and isinstance(doc.text, str)
            else None
        )
        name = _clean_name(ent, cued or mapped_type)
        if name is None:
            continue
        out.append((ent, name, mapped_type))
        if cued:
            out.extend([(ent, name, cued)] * CUE_WEIGHT)
        # Coordination: names in one list ("Thomas, Kiran Bhosale, Pooja
        # Shinde") are the same kind of thing, so each conjunct votes
        # (spaCy sometimes parses comma lists as appositions)
        root = getattr(ent, "root", None)
        if root is not None and isinstance(getattr(root, "dep_", None), str):
            siblings = [c for c in root.children if c.dep_ in ("conj", "appos")]
            if root.dep_ in ("conj", "appos"):
                siblings.append(root.head)
            for sibling in siblings:
                other = token_type.get(sibling.i)
                if other and not (ent.start <= sibling.i < ent.end):
                    out.extend([(ent, name, other)] * CONJ_WEIGHT)
    return out


def resolve_name_types(
    mentions: list[tuple[Any, str, str]], known: dict[str, str] | None = None
) -> dict[str, str]:
    """
    One type per name, by majority vote over its mentions (a name already in
    the graph keeps its type). Single-word names need two mentions, and a
    multi-word "name" that contains another name of a different type is a
    heading or table row ("Kothrud Hadapsar Pimpri"), not a name.
    """
    known = known or {}
    votes: dict[str, dict[str, int]] = {}
    for _, name, entity_type in mentions:
        tally = votes.setdefault(name, {})
        tally[entity_type] = tally.get(entity_type, 0) + 1
    resolved: dict[str, str] = {}
    for name, tally in votes.items():
        if " " not in name and sum(tally.values()) < 2 and name not in known:
            continue
        resolved[name] = known.get(name) or max(tally, key=lambda t: (tally[t], t))
    # Shared surnames: "Kavita Pawar" was read as a place, "Rahul Pawar" a
    # person. Each other name with the same last word adds one vote for its
    # type (from a snapshot, so the result does not depend on order).
    snapshot = dict(resolved)
    by_surname: dict[str, list[str]] = {}
    for name in snapshot:
        if " " in name:
            by_surname.setdefault(name.split()[-1], []).append(name)
    for name in snapshot:
        if " " not in name or name in known:
            continue
        score = dict(votes[name])
        for other in by_surname[name.split()[-1]]:
            if other != name:
                score[snapshot[other]] = score.get(snapshot[other], 0) + 1
        resolved[name] = max(score, key=lambda t: (score[t], t))

    # A person needs a full name, whatever the votes say ("Outstanding")
    resolved = {n: t for n, t in resolved.items() if t != "PERSON" or " " in n}

    singles = {n: t for n, t in resolved.items() if " " not in n}
    return {
        name: t
        for name, t in resolved.items()
        if " " not in name or all(singles.get(w) in (None, t) for w in name.split())
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
            for model_name in _DEFAULT.nlp.get("models", ["en_core_web_sm"]):
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
        use_nlp: bool = True,
        doc=None,
        name_types: dict[str, str] | None = None,
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
            use_nlp: parse with spaCy (off for short questions, where the
                phrase heuristic is enough and latency matters)
            doc: an existing spaCy parse of `text` (batch callers parse once
                with nlp.pipe and pass it in)
            name_types: decided types of named entities (from votes over a
                whole collection); default: decided from this document
        """
        schema = schema or get_schema()
        entities: list[ExtractedEntity] = []
        typer = semantic.get_typer(schema) if text.strip() else None

        # One spaCy parse, shared by NER, noun chunks and lemmas
        nlp = self.nlp if use_nlp and text.strip() and doc is None else None
        if nlp is not None:
            try:
                doc = nlp(text[: int(schema.nlp.get("max_chars", 200_000))])
            except Exception as e:
                logger.warning(f"spaCy parse skipped: {e}")

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
                        normalized_value=schema.canonical_term(entity_type, match.group(0)),
                        confidence=0.85,
                        start_offset=match.start(),
                        end_offset=match.end(),
                        page_number=page_number,
                    )
                )

        # 3. spaCy NER: people and places (not over a pattern or term match),
        # one type per name (see resolve_name_types)
        if doc is not None:
            taken = [(e.start_offset, e.end_offset) for e in entities]
            mentions = [
                m
                for m in ner_mentions(doc, schema)
                if not any(s < m[0].end_char and m[0].start_char < e for s, e in taken)
            ]
            if name_types is None:
                labels = set(schema.nlp.get("ner_labels", SPACY_TYPE_MAP).values())
                known = {v: t for t in labels for v in (known_nodes or {}).get(t, [])}
                name_types = resolve_name_types(mentions, known)
            seen_spans: set[tuple[int, int]] = set()
            for ent, name, _ in mentions:
                if (ent.start_char, ent.end_char) in seen_spans:
                    continue
                seen_spans.add((ent.start_char, ent.end_char))
                mapped_type = name_types.get(name)
                if mapped_type is None:
                    continue
                entities.append(
                    ExtractedEntity(
                        entity_type=mapped_type,
                        value=ent.text,
                        normalized_value=name,
                        confidence=0.80,
                        start_offset=ent.start_char,
                        end_offset=ent.end_char,
                        page_number=page_number,
                        attributes={"source": "ner", "label": ent.label_},
                    )
                )

        # 4. Embeddings: phrases and codes nobody listed
        if typer is not None:
            try:
                entities.extend(
                    self._semantic_entities(text, page_number, schema, typer, entities, doc)
                )
                entities = self._merge_near_duplicates(entities, schema, typer, known_nodes or {})
            except Exception as e:  # typing is an enrichment: never fail extraction
                logger.warning(f"Semantic entity typing skipped: {e}")

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
        doc=None,
    ) -> list[ExtractedEntity]:
        cfg = schema.semantic
        taken = [(e.start_offset, e.end_offset) for e in found]

        def overlaps(start: int, end: int) -> bool:
            return any(s < end and start < e for s, e in taken)

        out: list[ExtractedEntity] = []
        cap = float(cfg.get("confidence_cap", 0.8))

        # Key phrases → the type of their nearest example
        # Noun chunks from the spaCy parse when there is one (syntactic
        # phrases, lemmatised heads), else content-word runs
        limits = {
            "max_words": int(cfg.get("max_phrase_words", 4)),
            "min_chars": int(cfg.get("min_phrase_chars", 4)),
            "limit": int(cfg.get("max_candidates_per_document", 400)),
        }
        if doc is not None and schema.nlp.get("use_noun_chunks", True):
            mined = semantic.noun_chunk_candidates(doc, **limits)
        else:
            mined = semantic.candidate_phrases(text, **limits)
        candidates = [c for c in mined if any(not overlaps(s, e) for s, e in c.spans)]
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
