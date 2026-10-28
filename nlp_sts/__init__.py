"""
VEDA AI — NLP pipeline, one step per file

Indexing (every uploaded document):
    step01_text_extraction      file → clean text (parsers, OCR, records as "key: value")
    step02_chunking             text → passages (section → paragraph → sentence)
    step03_text_embeddings      passages → normalised MiniLM vectors
    step04_graph_schema         what to extract: types, patterns, terms, rules (graph_schema.json)
    step05_semantic_typing      key phrases typed by embedding similarity
    step06_entity_extraction    4-layer NER: regex → terms → spaCy → embeddings
    step07_relation_extraction  entities → typed knowledge-graph edges

Answering (every question):
    step08_vector_search        cosine ranking + graph boost + cut-off/fallback
    step09_rank_fusion          Reciprocal Rank Fusion of all retrievers
    step10_context_building     cited, token-budgeted LLM prompt

run_pipeline.py runs all ten steps on a sample document and prints each result.
The services import these steps (services/ingestion: step 1;
services/intelligence: steps 2–10), so this folder is the code that runs in production.

Steps are imported one by one (e.g. `from nlp_sts import step02_chunking`):
nothing is imported here, so the ingestion service does not need spaCy and
the intelligence service does not need the OCR libraries.
"""
