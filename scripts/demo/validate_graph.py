"""
Validate the demo dataset before upload:
- every .json file and every .jsonl line parses strictly
- every file yields text with the real ingestion parsers and names the company
- prints every knowledge-graph edge the real extractor and relationship
  inference produce, per file and as one deduplicated list

    services/ingestion/.venv/Scripts/python.exe scripts/demo/validate_graph.py [--text]
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "demo-data" / "nephrova"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ingestion = load("ingestion_worker", ROOT / "services/ingestion/src/workers/ingestion_worker.py")
# The extractor is a package (it reads graph_schema.json), so import it as one
sys.path.insert(0, str(ROOT / "services/intelligence"))
from src.entity_extraction import extractor as extractor_mod  # noqa: E402
from src.entity_extraction import semantic  # noqa: E402
from src.knowledge_graph import relationships  # noqa: E402

extractor = extractor_mod.IndustrialEntityExtractor()
extractor._spacy_unavailable = True  # matches the local install (no spaCy model)

# Embedding-based typing needs the sentence model. Run with the intelligence
# venv's packages available to reproduce it; without them only pattern and
# term edges are produced (SEMANTIC tells callers which).
try:
    from sentence_transformers import SentenceTransformer

    _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    semantic.set_encoder(
        lambda texts: _model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    )
    SEMANTIC = True
except ImportError:
    SEMANTIC = False


def files() -> list[Path]:
    return sorted(p for p in DATA.rglob("*") if p.is_file())


def edges_for_file(path: Path) -> tuple[str, list]:
    text = ingestion.get_parser(path.suffix.lstrip(".").lower())(str(path))["raw_text"]
    entities = [
        {"entity_type": e.entity_type, "value": e.value, "normalized_value": e.normalized_value,
         "confidence": e.confidence, "start_offset": e.start_offset}
        for e in extractor.extract_entities(text)
    ]
    return text, relationships.infer_relationships(entities, text)


def check_json_files() -> int:
    errors = 0
    for path in sorted(DATA.rglob("*.json*")):
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonl":
                lines = [line for line in text.splitlines() if line.strip()]
                for number, line in enumerate(lines, start=1):
                    if not isinstance(json.loads(line), dict):
                        raise ValueError(f"line {number} is not a JSON object")
                print(f"JSON ok   {path.name} ({len(lines)} records)")
            else:
                print(f"JSON ok   {path.name} ({type(json.loads(text)).__name__})")
        except ValueError as e:
            print(f"JSON BAD  {path.name}: {e}")
            errors += 1
    return errors


def main() -> int:
    show_text = "--text" in sys.argv
    failures = check_json_files()
    all_edges: dict[tuple, set[str]] = {}
    for path in files():
        text, edges = edges_for_file(path)
        rel = path.relative_to(DATA)
        if not text.strip():
            print(f"!! {rel}: NO TEXT")
            failures += 1
            continue
        if "Nephrova" not in text:
            print(f"!! {rel}: does not name the company")
            failures += 1
        print(f"\n=== {rel}  ({len(text.split())} words, {len(edges)} edges)")
        if show_text:
            print(text + "\n---")
        for e in edges:
            key = (e.source["normalized_value"], e.relationship_type, e.target["normalized_value"])
            all_edges.setdefault(key, set()).add(rel.name)
            print(f"   {key[0]} -[{key[1]}]-> {key[2]}")

    print(f"\n#### {len(all_edges)} distinct edges across the dataset")
    for (src, rel_type, tgt), names in sorted(all_edges.items()):
        print(f"#  {src} -[{rel_type}]-> {tgt}   ({', '.join(sorted(names))})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
