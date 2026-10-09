"""
VEDA AI — Knowledge-graph schema

Entity types, the patterns and terms that find them, and the rules that
relate them are data (graph_schema.json), not code, so a tenant in any
domain gets a graph without code changes:

- VEDA_GRAPH_SCHEMA_FILE replaces the bundled schema file;
- tenants.settings.graph_schema extends it for one tenant (new types,
  extra terms/examples, extra relationship rules), see merge_schema().

GraphSchema compiles the patterns once and is cached per source.
"""

import copy
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("veda.intelligence.schema")

DEFAULT_SCHEMA_FILE = Path(__file__).with_name("graph_schema.json")


@dataclass(frozen=True)
class EntityPattern:
    entity_type: str
    regex: re.Pattern
    normalize: str
    confidence: float
    numeric: bool


@dataclass
class EntityType:
    name: str
    label: str
    color: str | None
    role: str | None
    description: str
    terms: list[str]
    examples: list[str]
    leaf: bool
    identifier: bool


@dataclass
class GraphSchema:
    raw: dict
    types: dict[str, EntityType]
    patterns: list[EntityPattern]
    term_patterns: list[tuple[str, re.Pattern]]
    rules: dict[tuple[str, str], str]
    inverse_names: dict[str, str]
    detection_actions: set[str]
    detection_type: str | None
    detection_replaces: str | None
    co_occurrence_types: set[str]
    semantic: dict
    identifier_regex: re.Pattern | None
    term_sets: dict[str, set[str]] = field(default_factory=dict)
    nlp: dict = field(default_factory=dict)
    document_links: dict = field(default_factory=dict)
    fingerprint: str = ""
    _role_cache: dict = field(default_factory=dict)

    def types_with_role(self, role: str) -> set[str]:
        if role not in self._role_cache:
            self._role_cache[role] = {t.name for t in self.types.values() if t.role == role}
        return self._role_cache[role]

    @property
    def subject_types(self) -> set[str]:
        return self.types_with_role("subject")

    @property
    def leaf_types(self) -> set[str]:
        return {t.name for t in self.types.values() if t.leaf}

    def canonical_term(self, entity_type: str, text: str) -> str:
        """The listed term a match stands for: "conductivity alarms" → "conductivity alarm"."""
        value = text.lower()
        terms = self.term_sets.get(entity_type, set())
        if value in terms:
            return value
        for suffix in ("es", "s"):
            if value.endswith(suffix) and value[: -len(suffix)] in terms:
                return value[: -len(suffix)]
        return value

    def public_types(self) -> dict[str, dict]:
        """Labels, colours and roles for the UI."""
        return {
            t.name: {"label": t.label, "color": t.color, "role": t.role}
            for t in self.types.values()
        }


def term_pattern(terms: list[str]) -> re.Pattern | None:
    """
    Whole-word, case-insensitive matcher for a term list, plurals included
    ("leaks", "conductivity alarms"). Longer phrases are tried first, so
    "bearing failure" wins over shorter prefixes and "alignment" is not
    found inside "misalignment".
    """
    ordered = sorted({t for t in terms if t.strip()}, key=len, reverse=True)
    if not ordered:
        return None
    alternatives = "|".join(re.escape(t) for t in ordered)
    return re.compile(r"\b(?:" + alternatives + r")(?:e?s)?\b", re.IGNORECASE)


def merge_schema(base: dict, extension: dict | None) -> dict:
    """
    Extend a schema with a tenant's additions. Types are merged field by
    field (lists appended, scalars replaced); relationships and other lists
    are appended; the semantic settings are merged key by key.
    """
    if not extension:
        return base
    merged = copy.deepcopy(base)
    for name, spec in (extension.get("types") or {}).items():
        target = merged.setdefault("types", {}).setdefault(name, {})
        for key, value in spec.items():
            if isinstance(value, list):
                target[key] = list(target.get(key, [])) + value
            else:
                target[key] = value
    for key in ("relationships", "detection_actions", "co_occurrence_types"):
        if extension.get(key):
            merged[key] = list(merged.get(key, [])) + list(extension[key])
    for key in ("semantic", "extra_inverse_names", "nlp", "document_links"):
        if extension.get(key):
            merged[key] = {**merged.get(key, {}), **extension[key]}
    return merged


def _compile(raw: dict) -> GraphSchema:
    types: dict[str, EntityType] = {}
    patterns: list[EntityPattern] = []
    term_patterns: list[tuple[str, re.Pattern]] = []

    for name, spec in (raw.get("types") or {}).items():
        types[name] = EntityType(
            name=name,
            label=spec.get("label", name.replace("_", " ").title()),
            color=spec.get("color"),
            role=spec.get("role"),
            description=spec.get("description", ""),
            terms=list(spec.get("terms", [])),
            examples=list(spec.get("examples", [])),
            leaf=bool(spec.get("leaf", False)),
            identifier=bool(spec.get("identifier", False)),
        )
        for p in spec.get("patterns", []):
            try:
                regex = re.compile(p["regex"], re.IGNORECASE if p.get("ignore_case") else 0)
            except re.error as e:
                logger.warning(f"Skipping invalid pattern for {name}: {e}")
                continue
            patterns.append(
                EntityPattern(
                    entity_type=name,
                    regex=regex,
                    normalize=p.get("normalize", "strip"),
                    confidence=float(p.get("confidence", 0.9)),
                    numeric=bool(p.get("numeric", False)),
                )
            )
        compiled_terms = term_pattern(types[name].terms)
        if compiled_terms is not None:
            term_patterns.append((name, compiled_terms))

    rules: dict[tuple[str, str], str] = {}
    inverse: dict[str, str] = dict(raw.get("extra_inverse_names") or {})
    for rule in raw.get("relationships", []):
        rules[(rule["source"], rule["target"])] = rule["type"]
        if rule.get("inverse"):
            inverse[rule["type"]] = rule["inverse"]

    detection = raw.get("detection_relationship") or {}
    if detection.get("type") and detection.get("inverse"):
        inverse[detection["type"]] = detection["inverse"]

    links = dict(raw.get("document_links") or {})
    if links.get("relationship") and links.get("inverse"):
        inverse[links["relationship"]] = links["inverse"]

    semantic = dict(raw.get("semantic") or {})
    identifier_regex = None
    if semantic.get("identifier_regex"):
        try:
            identifier_regex = re.compile(semantic["identifier_regex"])
        except re.error as e:
            logger.warning(f"Invalid identifier_regex: {e}")

    return GraphSchema(
        raw=raw,
        types=types,
        patterns=patterns,
        term_patterns=term_patterns,
        rules=rules,
        inverse_names=inverse,
        detection_actions={a.lower() for a in raw.get("detection_actions", [])},
        detection_type=detection.get("type"),
        detection_replaces=detection.get("replaces"),
        co_occurrence_types=set(raw.get("co_occurrence_types", [])),
        semantic=semantic,
        identifier_regex=identifier_regex,
        term_sets={name: {x.lower() for x in t.terms} for name, t in types.items()},
        nlp=dict(raw.get("nlp") or {}),
        document_links=links,
        fingerprint=hashlib.sha1(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:12],
    )


def _schema_path() -> Path:
    return Path(os.environ.get("VEDA_GRAPH_SCHEMA_FILE") or DEFAULT_SCHEMA_FILE)


@lru_cache(maxsize=4)
def _load_file(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def base_schema_dict() -> dict:
    path = _schema_path()
    return _load_file(str(path), path.stat().st_mtime)


@lru_cache(maxsize=64)
def _compiled(raw_json: str) -> GraphSchema:
    return _compile(json.loads(raw_json))


def get_schema(tenant_extension: dict | None = None) -> GraphSchema:
    """The schema for a tenant (the base schema when it has no extension)."""
    raw = merge_schema(base_schema_dict(), tenant_extension)
    return _compiled(json.dumps(raw, sort_keys=True))
