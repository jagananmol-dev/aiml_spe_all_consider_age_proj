"""
VEDA AI — Relationship inference

Turns the entities extracted from one document into graph edges.

Entities are only related when they appear in the same *segment*:
- a record block ("column: value" lines from CSV/JSON/forms, separated by
  blank lines) is one segment, so a row's equipment, failure, and action
  stay together;
- any other text is split into lines and sentences.

Pairing every entity in a whole document (the previous behaviour) linked
unrelated equipment to each other's failures — e.g. a report about P-101A's
bearing failure that also mentions the standby P-101B made P-101B
"FAILED_WITH bearing failure".
"""

import re
from dataclasses import dataclass

from ..entity_extraction.schema import GraphSchema, get_schema

# The relationship rules live in the graph schema (graph_schema.json); these
# names are the default schema's, kept for callers that read them
_DEFAULT = get_schema()
INFERENCE_RULES = dict(_DEFAULT.rules)
DETECTION_ACTIONS = set(_DEFAULT.detection_actions)
CO_OCCURRENCE_TYPES = set(_DEFAULT.co_occurrence_types)

_RECORD_LINE = re.compile(r"^\s*[^\n:]{1,60}:\s+\S")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True)
class InferredEdge:
    source: dict
    target: dict
    relationship_type: str
    confidence: float


def _record_segments(start: int, body: str) -> list[tuple[int, int]]:
    """
    Split a record block into one segment per record.

    Flattened JSON keys carry their nesting ("site.areas[0].equipment[1].tag"),
    so consecutive lines with the same parent path form one record; plain
    "column: value" lines all share the empty parent and stay together.
    """
    segments: list[tuple[int, int]] = []
    seg_start, parent, offset = start, None, start
    for line in body.split("\n"):
        if _RECORD_LINE.match(line):
            key = line.split(":", 1)[0].strip()
            line_parent = key.rsplit(".", 1)[0] if "." in key else ""
            if parent is not None and line_parent != parent:
                segments.append((seg_start, offset))
                seg_start = offset
            parent = line_parent
        offset += len(line) + 1
    segments.append((seg_start, start + len(body)))
    return segments


def text_segments(text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of the segments entities may relate within."""
    segments: list[tuple[int, int]] = []
    for block in re.finditer(r"(?:[^\n]|\n(?!\s*\n))+", text):
        start, body = block.start(), block.group(0)
        lines = [line for line in body.split("\n") if line.strip()]
        record_lines = sum(1 for line in lines if _RECORD_LINE.match(line))
        if len(lines) > 1 and record_lines / len(lines) >= 0.6:
            segments.extend(_record_segments(start, body))
            continue
        offset = start
        for line in body.split("\n"):
            line_start = offset
            offset += len(line) + 1
            pos = 0
            for end_match in _SENTENCE_END.finditer(line):
                segments.append((line_start + pos, line_start + end_match.start()))
                pos = end_match.end()
            if line[pos:].strip():
                segments.append((line_start + pos, line_start + len(line)))
    return segments


def _segment_groups(entities: list[dict], text: str | None) -> list[list[dict]]:
    if text is None:
        return [entities]
    groups: list[list[dict]] = []
    for start, end in text_segments(text):
        group = [
            e
            for e in entities
            if e.get("start_offset") is not None and start <= e["start_offset"] < end
        ]
        if len(group) > 1:
            groups.append(group)
    return groups


def infer_relationships(
    entities: list[dict], text: str | None = None, schema: GraphSchema | None = None
) -> list[InferredEdge]:
    """
    Infer typed edges between entities that share a segment of `text`, using
    the schema's relationship rules (default: the base schema).

    Without `text`, the whole entity list is treated as one segment.
    Duplicate edges (same source, target, and type) are returned once.
    """
    schema = schema or get_schema()
    rules = schema.rules
    edges: dict[tuple, InferredEdge] = {}
    for group in _segment_groups(entities, text):
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                src, tgt = first, second
                rel_type = rules.get((src["entity_type"], tgt["entity_type"]))
                if not rel_type:
                    rel_type = rules.get((tgt["entity_type"], src["entity_type"]))
                    if rel_type:
                        src, tgt = tgt, src
                if (
                    schema.detection_type
                    and rel_type == schema.detection_replaces
                    and tgt["normalized_value"].lower() in schema.detection_actions
                ):
                    rel_type = schema.detection_type
                if not rel_type:
                    if (
                        src["entity_type"] == tgt["entity_type"]
                        and src["entity_type"] in schema.co_occurrence_types
                        and src["normalized_value"] != tgt["normalized_value"]
                    ):
                        rel_type = "CO_OCCURS_WITH"
                    else:
                        continue
                    # Undirected: store A–B once, whichever order it appears in
                    if src["normalized_value"] > tgt["normalized_value"]:
                        src, tgt = tgt, src
                key = (
                    src["entity_type"],
                    src["normalized_value"],
                    tgt["entity_type"],
                    tgt["normalized_value"],
                    rel_type,
                )
                if key in edges:
                    continue
                confidence = (src.get("confidence", 0.5) + tgt.get("confidence", 0.5)) / 2
                edges[key] = InferredEdge(src, tgt, rel_type, confidence)
    return list(edges.values())
