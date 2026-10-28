"""
Run the whole NLP pipeline step by step on one document and show what each
step produces, like a notebook run top to bottom.

    services/intelligence/.venv/Scripts/python.exe nlp_sts/run_pipeline.py
    services/intelligence/.venv/Scripts/python.exe nlp_sts/run_pipeline.py path/to/file.pdf "Your question?"

Without arguments it uses a short built-in maintenance report and question.
Steps 3, 5 and 8 need sentence-transformers (the intelligence venv has it).
"""

import sys
import tempfile
from pathlib import Path

# Run as a script: make `import nlp_sts` work from the repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlp_sts import step01_text_extraction as s01
from nlp_sts import step02_chunking as s02
from nlp_sts import step03_text_embeddings as s03
from nlp_sts import step04_graph_schema as s04
from nlp_sts import step05_semantic_typing as s05
from nlp_sts import step06_entity_extraction as s06
from nlp_sts import step07_relation_extraction as s07
from nlp_sts import step08_vector_search as s08
from nlp_sts import step09_rank_fusion as s09
from nlp_sts import step10_context_building as s10

SAMPLE_TEXT = """# Machine HD-K04 Service Report

1. Problem
Dialysis machine HD-K04 at the Kothrud centre raised three conductivity alarms
on 12 August 2026. Measured conductivity was 15.2 mS/cm against a limit of 14.5 mS/cm.

2. Repair
Nikhil Joshi replaced the conductivity cell and recalibrated the machine.
The repair followed ISO 23500 and the NABH water management standard.

3. Water plant
The RO-H1 water plant at Hadapsar showed an endotoxin exceedance of 0.31 EU/mL.
Root cause: a missed disinfection cycle. A repeat disinfection was done.
"""
SAMPLE_QUESTION = "How was the conductivity alarm on HD-K04 fixed?"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def show(step: str, title: str) -> None:
    print(f"\n{'═' * 72}\n{step}  {title}\n{'═' * 72}")


def main() -> int:
    if len(sys.argv) > 1:
        path, question = Path(sys.argv[1]), (sys.argv[2] if len(sys.argv) > 2 else SAMPLE_QUESTION)
    else:
        path = Path(tempfile.gettempdir()) / "veda_nlp_sample.md"
        path.write_text(SAMPLE_TEXT, encoding="utf-8")
        question = SAMPLE_QUESTION
    title = path.stem.replace("_", " ")

    # ── Step 1: text extraction ──────────────────────
    show("STEP 1", "Text extraction (step01_text_extraction.py)")
    parsed = s01.get_parser(path.suffix.lstrip("."))(str(path))
    text = parsed["raw_text"]
    print(f"{parsed['word_count']} words, {parsed['page_count']} page(s), {len(parsed['tables'])} table(s)")
    print(text[:400])

    # ── Step 2: chunking ─────────────────────────────
    show("STEP 2", "Chunking (step02_chunking.py)")
    chunker = s02.TextChunker(max_chunk_size=300, chunk_overlap=50)  # small, to show several chunks
    chunks = chunker.merge_small_chunks(chunker.split_into_chunks(text, "doc-1", {"title": title}))
    for chunk in chunks:
        print(f"[chunk {chunk.metadata['chunk_index']}] ~{chunk.token_estimate} tokens: {chunk.text[:70]!r}")

    # ── Step 3: text embeddings ──────────────────────
    show("STEP 3", "Text embeddings (step03_text_embeddings.py)")
    try:
        model = s03.load_embedding_model(MODEL)  # also registers the encoder for step 5
    except ImportError:
        model = None
        print("sentence-transformers is not installed: steps 3, 5 (embedding part) and 8 are skipped")
    if model is not None:
        vectors = s03.embed_passages(model, s03.passage_texts(title, [c.text for c in chunks]))
        print(f"{len(vectors)} vectors of {vectors.shape[1]} dimensions, norm {float((vectors[0] ** 2).sum()) ** 0.5:.2f}")

    # ── Step 4: graph schema ─────────────────────────
    show("STEP 4", "Graph schema (step04_graph_schema.py + graph_schema.json)")
    schema = s04.get_schema()
    for name, entity_type in schema.types.items():
        print(f"{name:<20} role={entity_type.role or '-':<12} {len(entity_type.terms)} terms, {len(entity_type.examples)} examples")
    print(f"{len(schema.patterns)} regex patterns, {len(schema.rules)} relationship rules")

    # ── Step 5: semantic typing ──────────────────────
    show("STEP 5", "Semantic typing (step05_semantic_typing.py)")
    candidates = s05.candidate_phrases(text, limit=12)
    typer = s05.get_typer(schema)
    labels = typer.classify([c.phrase for c in candidates]) if typer else [None] * len(candidates)
    for candidate, label in zip(candidates, labels):
        if label:
            typed = f"{label[0]} ({label[1]:.2f})"
        else:
            typed = "— not typed (closer to the background class)" if typer else "— (no encoder)"
        print(f"{candidate.phrase!r:<34} → {typed}")

    # ── Step 6: entity extraction ────────────────────
    show("STEP 6", "Entity extraction (step06_entity_extraction.py)")
    entities = s06.extractor.extract_entities(text, schema=schema)
    for e in entities:
        print(f"{e.entity_type:<20} {e.normalized_value!r:<36} conf {e.confidence:.2f}")
    entity_dicts = [
        {"entity_type": e.entity_type, "value": e.value, "normalized_value": e.normalized_value,
         "confidence": e.confidence, "start_offset": e.start_offset}
        for e in entities
    ]

    # ── Step 7: relation extraction ──────────────────
    show("STEP 7", "Relation extraction (step07_relation_extraction.py)")
    edges = s07.infer_relationships(entity_dicts, text, schema) + s07.document_edges(entity_dicts, title, schema)
    for edge in edges:
        print(f"{edge.source['normalized_value']} -[{edge.relationship_type}]-> {edge.target['normalized_value']}")

    # ── Step 8: vector search ────────────────────────
    show("STEP 8", f"Vector search (step08_vector_search.py)  question: {question!r}")
    vector_hits: list = []
    if model is not None:
        ranked = s08.rank_passages(vectors, s03.embed_query(model, question), top_k=3, min_score=0.25, fallback_k=2)
        for position, score in zip(ranked.positions, ranked.scores):
            print(f"chunk {position}  cosine {score:.3f}  {chunks[position].text[:60]!r}")
            vector_hits.append(chunks[position])
        if ranked.low_confidence:
            print("low confidence: nothing above the cut-off, closest passages returned")

    # ── Step 9: rank fusion ──────────────────────────
    show("STEP 9", "Reciprocal Rank Fusion (step09_rank_fusion.py)")
    # A simple keyword ranking stands in for BM25 here, to show two lists being fused
    words = {w.lower().strip("?.,") for w in question.split() if len(w) > 3}
    keyword_hits = sorted(chunks, key=lambda c: -sum(w in c.text.lower() for w in words))[:3]

    class Hit:  # the shape the fusion expects
        def __init__(self, chunk):
            self.document_id, self.chunk_text, self.score, self.chunk = "doc-1", chunk.text, 0.0, chunk

    fused = s09.reciprocal_rank_fusion([[Hit(c) for c in vector_hits], [Hit(c) for c in keyword_hits]], top_n=3)
    for hit in fused:
        print(f"RRF {hit.score:.4f}  {hit.chunk_text[:60]!r}")

    # ── Step 10: context building ────────────────────
    show("STEP 10", "Context building (step10_context_building.py)")
    builder = s10.ChunkBuilder(max_total_tokens=4000)
    for hit in fused:
        hit.chunk.relevance_score = hit.score
    context = builder.prepare_context(
        query=question,
        chunks=[hit.chunk for hit in fused],
        graph_context=[
            {"source_value": e.source["normalized_value"], "source_type": e.source["entity_type"],
             "relationship": e.relationship_type,
             "target_value": e.target["normalized_value"], "target_type": e.target["entity_type"]}
            for e in edges
        ],
        entities_found=entity_dicts,
    )
    print(f"~{context.total_token_estimate} tokens → sent to the LLM with the system prompt\n")
    print(context.formatted_prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
