# VEDA AI — NLP Techniques Guide

This document explains **which NLP techniques VEDA uses, where each one lives in the code, and how the functions work together**: from an uploaded file, to a knowledge graph, to a cited chatbot answer.

All code paths below are relative to the repository root.

---

## 1. The big picture

```
 Upload (PDF, DOCX, PPTX, CSV, JSON, XLSX, image, text)
   │
   ▼
 [A] Text extraction + OCR            nlp_sts/step01_text_extraction.py
   │   raw text, records as "key: value" blocks
   ▼
 [B] Chunking (section → paragraph → sentence)   nlp_sts/step02_chunking.py
   │
   ├──► [C] Sentence embeddings (MiniLM) ──► vector store      nlp_sts/step03_text_embeddings.py, step08_vector_search.py
   │
   └──► [D] Entity extraction (4 layers)                       nlp_sts/step06_entity_extraction.py
           1. regex patterns   2. term lists   3. spaCy NER   4. embedding typing (step05_semantic_typing.py)
           │
           ▼
        [E] Relationship extraction (segment co-occurrence + typed rules)  nlp_sts/step07_relation_extraction.py
           │
           ▼
        [F] Knowledge graph (nodes, edges, entity resolution)              knowledge_graph/local_graph.py
   ▼
 Question
   │
 [G] Query understanding: small talk / overview / follow-up rewriting      apps/web/src/lib/chatPrompt.ts
   │
 [H] Hybrid retrieval: dense vectors + graph-entity linking + BM25 text + RRF fusion   rag/pipeline.py
   │
 [I] Prompt construction with numbered citations, token budgeting          chatPrompt.ts, nlp_sts/step10_context_building.py
   │
 [J] LLM generation, streamed (Ollama / OpenAI-compatible)                 apps/web/src/lib/llm.ts
```

**All NLP code is in `nlp_sts/`**, one file per pipeline step (`step01_…` to `step10_…`); `python nlp_sts/run_pipeline.py` runs the steps one by one on a sample document. Python paths under `knowledge_graph/` and `rag/` (storage, caching and orchestration) are inside `services/intelligence/src/`.

### Libraries and models

| Library / model | Used for | Where |
|---|---|---|
| **spaCy** (`en_core_web_sm`) | tokenisation, POS tagging, dependency parsing, NER, noun chunks, lemmatisation | `nlp_sts/step06_entity_extraction.py`, `step05_semantic_typing.py` |
| **sentence-transformers** `all-MiniLM-L6-v2` (384-dim) | sentence/phrase embeddings for search, entity typing, entity merging and query linking | `rag/pipeline.py` (registered into `step05_semantic_typing.py`) |
| **NumPy** | cosine similarity as matrix products, top-k selection | `step05_semantic_typing.py`, `rag/local_store.py`, `local_graph.py` |
| **Python `re`** | rule-based extraction, segmentation, chunk splitting | everywhere |
| **PyMuPDF + pdfplumber** | PDF text and table extraction | `step01_text_extraction.py` |
| **EasyOCR** | optical character recognition for images | `step01_text_extraction.py` |
| **OpenSearch** (optional) | BM25 full-text search with fuzzy matching | `rag/pipeline.py` |
| **Ollama / OpenAI-compatible LLM** | answer generation | `apps/web/src/lib/llm.ts` |

---

## 2. File-by-file map

| File | NLP techniques inside |
|---|---|
| `nlp_sts/step01_text_extraction.py` | Text extraction, ligature normalisation, OCR, OCR line reconstruction, OCR error correction, structured-data linearisation (CSV/JSON → text) |
| `nlp_sts/graph_schema.json` | The knowledge base the NLP runs on: entity types, regex patterns, gazetteer terms, seed examples, NER label map, context cues, relationship rules, similarity thresholds |
| `nlp_sts/step04_graph_schema.py` | Compiling patterns and term lists, plural handling, canonical term mapping, per-tenant schema merging |
| `nlp_sts/step06_entity_extraction.py` | Regex NER, gazetteer matching, spaCy NER, name cleaning, context-cue voting, coordination voting, majority-vote type resolution, surname propagation, overlap deduplication |
| `nlp_sts/step05_semantic_typing.py` | Stop-word phrase mining, noun-chunk mining, lemmatisation of phrase heads, embedding cache, nearest-example (few-shot) classification, margin + background rejection, context-window typing of codes, greedy similarity clustering (entity resolution) |
| `nlp_sts/step07_relation_extraction.py` | Sentence and record segmentation, co-occurrence relation extraction, typed relation rules, detection-vs-repair disambiguation, document→entity links |
| `nlp_sts/step02_chunking.py`, `nlp_sts/step10_context_building.py` | Structure-aware chunking, overlap windows, sentence splitting, token estimation, entity/graph enrichment of chunks, prompt formatting, token-budget trimming |
| `services/intelligence/src/knowledge_graph/local_graph.py` | Entity linking (question phrase → graph node) by exact and embedding match, constrained breadth-first graph walk |
| `services/intelligence/src/knowledge_graph/rebuild.py` | Batched spaCy parsing (`nlp.pipe`), collection-wide name-type voting, chunk overlap removal |
| `nlp_sts/step03_text_embeddings.py` | Embedding model loading (offline cache first), title-conditioned passage embeddings, query embedding, encoder sharing with step 5 |
| `nlp_sts/step08_vector_search.py` | Dense ranking (cosine via dot product), graph-entity boost, top-k, similarity cut-off, low-confidence fallback |
| `nlp_sts/step09_rank_fusion.py` | Reciprocal Rank Fusion of the vector, graph and BM25 lists |
| `services/intelligence/src/rag/pipeline.py` | Orchestration: document indexing, hybrid retrieval (pgvector / OpenSearch / graph), calls steps 2–10 |
| `services/intelligence/src/rag/local_store.py` | Passage storage in PostgreSQL and the cached in-memory vector index searched by step 8 |
| `apps/web/src/lib/chatPrompt.ts` | Intent detection (small talk, overview), follow-up query rewriting, query expansion, citation numbering, prompt-injection guard, history truncation |
| `apps/web/src/lib/llm.ts` | Streaming generation from Ollama or any OpenAI-compatible server, temperature/context-window settings |

---

## 3. Stage A — Text extraction and OCR

**File:** `nlp_sts/step01_text_extraction.py`

NLP is only as good as the text it gets, so each format is turned into clean, linear text that keeps its structure.

| Function | What it does | NLP point |
|---|---|---|
| `parse_pdf()` | PyMuPDF extracts text per page; pdfplumber extracts tables. | Ligatures are expanded (`ﬁ` → `fi`) so the text matches what people type in a search. |
| `parse_image_ocr()` | EasyOCR reads a scanned image or photo (GPU if available). | Images are read as-is: thresholding/denoising made recognition worse on clean scans. |
| `_group_ocr_lines()` | Sorts OCR boxes top-to-bottom, groups boxes whose vertical centres are close into one line, orders each line left-to-right. | **Reading-order reconstruction**: a printed line stays one line of text. |
| `_fix_tag_digits()` | In tag-like tokens (`P-1O1A`), a letter `O` in the numeric part becomes `0`. | **OCR post-correction** for a common character confusion. |
| `parse_csv()` | Sniffs the delimiter, then writes each row as a block of `column: value` lines. | **Linearisation of tables**: column names stay next to values, so search and extraction see "Machine: HD-K04", not a bare "HD-K04". |
| `_flatten_json()` / `parse_json()` | Nested JSON becomes `path.to.key: value` lines; each record is its own block. | Same idea; the dotted path is later used to split records (see Stage E). |
| `parse_docx()`, `parse_pptx()`, `parse_spreadsheet()`, `parse_text()` | Paragraphs and tables in reading order. | — |

---

## 4. Stage B — Chunking

**File:** `nlp_sts/step02_chunking.py`, class `TextChunker` (prompt building: `nlp_sts/step10_context_building.py`, class `ChunkBuilder`)

Documents are split into passages of at most **1500 characters** with **200 characters of overlap** (`RAGSettings` in `rag/pipeline.py`).

| Function | Technique |
|---|---|
| `split_into_chunks()` | **Hierarchical, structure-aware splitting**: sections first, then paragraphs, then sentences. |
| `_split_into_sections()` | Splits *before* structural markers (`SECTION_BREAK_PATTERNS`: numbered sections `1. `, ALL-CAPS headers, Markdown `#`, `---`/`===` rules) with a zero-width look-ahead, so a heading stays attached to the section it introduces. Falls back to blank-line paragraphs. |
| `_split_large_section()` | Packs paragraphs into chunks; each new chunk starts with the last 200 characters of the previous one (**sliding-window overlap**) so a fact cut at a boundary is still found. |
| `_split_on_sentences()` | Last resort for one huge paragraph: **regex sentence segmentation** on `(?<=[.!?])\s+`. |
| `merge_small_chunks()` | Joins tiny neighbouring fragments (a lone heading, one CSV row) up to the size limit, so a passage keeps its context. |
| `estimate_tokens()` | **Token estimation** at ~4 characters per token, used for the LLM context budget. |

---

## 5. Stage C — Sentence embeddings (dense representation)

**Files:** `rag/pipeline.py`, `rag/local_store.py`

- **Model:** `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, loaded lazily in `RAGPipeline.embedding_model`. `warm_up()` loads it at start-up so the first question doesn't wait.
- **L2-normalised vectors** (`normalize_embeddings=True`): a dot product is the cosine similarity, so search is a single matrix product.
- `index_document()` embeds each chunk **prefixed with its document title** (`"{title}\n\n{chunk}"`), so a passage keeps its context ("Dialysis SOP" + "check conductivity…").
- **One model for everything.** The same model is registered with `semantic.set_encoder()` and is reused for entity typing, entity merging and question-to-graph linking. No second model is loaded.
- `embed_query()` embeds the user's question the same way.

---

## 6. Stage D — Entity extraction (Named Entity Recognition)

**File:** `nlp_sts/step06_entity_extraction.py`, `EntityExtractor.extract_entities()`

This is the core NLP stage. It is **domain-agnostic**: *what* to look for comes from `graph_schema.json`, not from code. It runs **four layers**, from the most precise to the most general. spaCy parses each document **only once**, and that one parse supplies named entities, noun chunks and lemmas.

### Entity types (default schema)

| Type | Role | Found by |
|---|---|---|
| `EQUIPMENT_TAG` | subject (asset / ID) | regex (`P-101A`, `HD-K04`, `FCV-2001`…) + context typing of unknown codes |
| `FAILURE_MODE` | issue | 47 terms + embedding examples |
| `MAINTENANCE_ACTION` | action | 44 terms + embedding examples |
| `REGULATION` | governance | regex (`ISO 9001`, `OISD-118`, `HIPAA`, `NABH`, `DPDP Act`…) |
| `MEASUREMENT` | value (leaf) | regex with number + unit (`4.5 bar`, `13.8 mS/cm`, `120 mg/dL`) |
| `CONDITION` | issue | terms + examples (medical conditions) |
| `MEDICATION` | treatment | terms + examples |
| `PERSON`, `LOCATION` | person / place | spaCy NER |
| `DOCUMENT` | document | one node per uploaded file |

### Layer 1 — Rule-based (regex) NER

- Patterns are compiled once in `step04_graph_schema.py::_compile()` into `EntityPattern` objects (regex, normalisation, confidence, numeric flag).
- `_normalize()` canonicalises matches: `upper` / `upper_dash` turns `p 101a` into `P-101A`.
- **Numeric attribute extraction:** for `MEASUREMENT`, regex groups give `numeric_value` (float) and `unit`.
- Confidence 0.90–0.95.

### Layer 2 — Gazetteer (dictionary) matching

- `step04_graph_schema.py::term_pattern()` builds one whole-word, case-insensitive regex per type from its term list:
  - **longest match first**, so "bearing failure" wins over "bearing";
  - `\b` word boundaries, so "alignment" isn't found inside "misalignment";
  - optional `(?:e?s)?` suffix, a light **plural normalisation**.
- `GraphSchema.canonical_term()` maps the surface form back to the listed term ("conductivity alarms" → "conductivity alarm").
- Confidence 0.85.

### Layer 3 — Statistical NER with spaCy

- `EntityExtractor.nlp` lazy-loads the models listed in `schema.nlp.models`. If spaCy or the model is missing, this layer is skipped and the others still run.
- spaCy labels are mapped to graph types via `nlp.ner_labels`: `PERSON → PERSON`, `GPE / LOC / FAC → LOCATION`.
- Mentions that overlap a Layer 1/2 match are dropped.

Small NER models make mistakes in forms and tables, so several **post-processing heuristics** correct them:

| Function | Technique |
|---|---|
| `_clean_name()` | **Name validation using POS tags**: 1–4 capitalised, letters-only words that are all `PROPN`; a `PERSON` needs at least two words. Rejects headings like "Appendix" or "Board Note". Strips possessive `'s`. |
| `_cue_type()` | **Contextual cue words**: the text just before a name on its line ("Reported by", "Owner:", "Site:", "at") votes for a type. Cues are in `nlp.type_cues`. |
| `ner_mentions()` | Produces `(span, name, type-vote)` triples. A context cue adds `CUE_WEIGHT = 3` votes. **Dependency-parse coordination**: names joined by `conj`/`appos` ("Thomas, Kiran Bhosale, Pooja Shinde") are the same kind of thing, so each conjunct adds `CONJ_WEIGHT = 2` votes for its siblings' type. |
| `resolve_name_types()` | **Majority vote** gives one type per name. Single-word names need 2 mentions. Names already in the graph keep their type. **Surname propagation**: names sharing a last name vote for each other's type ("Kavita Pawar" is a person because "Rahul Pawar" is). Drops multi-word "names" that contain another name of a different type (table rows like "Kothrud Hadapsar Pimpri"). |

During a full rebuild (`knowledge_graph/rebuild.py`), the vote runs over **the whole document collection** (`nlp.pipe` batched parse), so a name gets one type across every document.

### Layer 4 — Embedding-based typing (few-shot / zero-shot NER)

**File:** `nlp_sts/step05_semantic_typing.py`

Patterns and term lists only find what someone listed in advance. This layer finds the rest in any domain.

**a) Candidate phrase mining.** Two methods, chosen by `nlp.use_noun_chunks`:

| Function | Technique |
|---|---|
| `noun_chunk_candidates(doc)` | **spaCy noun chunks**. Strips leading determiners, numbers, stop words and participles (`VBN/VBD/VBG`): "the repeated conductivity alarms" → "conductivity alarms". **Lemmatises the head**, giving "conductivity alarm", so singular and plural become one entity. Skips chunks with digits (left to Layers 1 and 4c). |
| `candidate_phrases(text)` | Fallback without spaCy (also used for short questions): **content-word runs**. A phrase ends at a stop word (`STOPWORDS`), a common verb (`VERB_FORMS`), any `-ed` word, a digit or punctuation (`_is_breaker()`). Long runs keep their last 4 words, since **English noun-phrase heads come last**. |

Both rank candidates by frequency, then by word count, and cap them at 400 per document.

**b) Nearest-example classification**, `SemanticTyper.classify()`:

1. Each schema type's `examples`, `terms` and `description` are embedded once per schema version (`SemanticTyper.__init__`).
2. `_eligible()` is a cheap pre-filter: no single words (too generic), and no phrases headed by a **background noun** ("incident *report*", "disinfection *log*" name a record, not the thing).
3. All candidate phrases are embedded **in one batch**. `type_scores()` computes `phrases × examples` cosine similarity and takes the best example per type.
4. A phrase is accepted only if all of these hold:
   - top score ≥ `min_similarity` (0.70);
   - top minus runner-up ≥ `min_margin` (0.06), which rejects ambiguous phrases;
   - top score > similarity to `background_examples` ("report", "table", "date"…), the **reject / "other" class**;
   - the type is not an identifier type (assets come only from codes).
5. Confidence is capped at `confidence_cap` (0.8), below curated terms.

**c) Typing unknown codes from context**, `classify_identifiers()` + `identifier_context()`:

Codes no pattern knows (`LN-2041`, `AHU3`) are found by `semantic.identifier_regex`. The **up to 3 content words just before the code** on its line ("loan LN-2041", "machine HD-K04") are embedded and compared to the identifier types' examples (threshold 0.55, and it must beat the background). Words *after* a code are ignored because they describe what it's about, not what it is: "RSK-04 Dialysis machine failure" is a risk, not a machine.

**d) Efficiency**, `EmbeddingCache`:
- a thread-safe LRU cache of up to 200,000 phrase vectors, so each phrase is embedded once per process;
- each document's uncached phrases go to the model in a single batch;
- typers are cached per schema fingerprint (`get_typer()`).

### Entity resolution (merging near-duplicates)

`EntityExtractor._merge_near_duplicates()` → `semantic.merge_into_known()`

- Within one type, names with cosine ≥ `merge_similarity` (0.9) become one entity: "anemia" / "anaemia".
- **Existing graph node names are fixed cluster centres**, so a new document's "anaemia" joins the existing "anemia" node. This is **cross-document coreference** at the node level.
- Greedy clustering in confidence order; the original name is kept as `attributes.merged_from`.
- Curated terms are protected, and identifier/pattern types are never merged (`P-101A` ≠ `P-101B`).
- The cost is one `(values × known)` product, not quadratic in the graph size.
- `merge_similar()` is the general (no known nodes) greedy version.

### Final clean-up

`_deduplicate()` sorts by offset and confidence and drops overlapping spans of the same type, keeping the highest-confidence one.

---

## 7. Stage E — Relationship extraction

**File:** `nlp_sts/step07_relation_extraction.py`

Relations are extracted with **segment-level co-occurrence plus typed rules**.

| Function | Technique |
|---|---|
| `text_segments()` | **Discourse segmentation.** A block where ≥60% of lines are `key: value` lines is a *record*. Other text is split into lines, then **sentences** (`(?<=[.!?])\s+(?=[A-Z0-9])`). |
| `_record_segments()` | Splits record blocks by the **parent path** of flattened JSON keys (`site.areas[0].equipment[1].tag`), so each nested record is its own segment. |
| `infer_relationships()` | For each pair of entities **in the same segment**, looks up `(source_type, target_type)` in the schema's `relationships` rules (e.g. `EQUIPMENT_TAG → FAILURE_MODE = FAILED_WITH`, `CONDITION → MEDICATION = TREATED_WITH`). The direction is fixed automatically. Edge confidence is the mean of the two entities' confidences. |
| (inside `infer_relationships`) | **Relation disambiguation**: an issue paired with an inspection-type action (`detection_actions`) becomes `DETECTED_BY` instead of `REPAIRED_BY`. |
| (inside `infer_relationships`) | **Undirected co-occurrence**: same-type entities listed in `co_occurrence_types` (two assets, two regulations) get `CO_OCCURS_WITH`. |
| `document_edges()` | Links the document node to the 25 entities it mentions most (`MENTIONS`), excluding measurement values. |

**Why segments?** Pairing every entity in a whole document linked unrelated assets to each other's failures. Example: a P-101A bearing-failure report that also mentions standby pump P-101B would make P-101B "FAILED_WITH bearing failure".

Every rule has an **inverse name** (`FAILED_WITH` ↔ `FAILURE_OF`), so the graph reads correctly in both directions.

---

## 8. Stage F — Knowledge graph and entity linking

**File:** `services/intelligence/src/knowledge_graph/local_graph.py` (plain PostgreSQL). `graph_manager.py` is the Apache AGE equivalent.

| Function | Technique |
|---|---|
| `replace_document_graph()` | Stores a document's edges, tagged with the document id, so re-indexing replaces exactly that document's facts. |
| `known_node_values()` | Existing node names by type, fed back into extraction for cross-document merging (Stage D). |
| `link_phrases()` | **Entity linking**: maps question phrases to graph nodes by exact match (score 1.0) or by embedding nearest neighbour with cosine ≥ `query_link_similarity` (0.78). The node matrix is embedded once and cached per graph version. |
| `walk()` / `search_many()` | **Constrained breadth-first traversal** (2 hops). Leaf types (measurements) aren't expanded. A shared concept ("inspection") never bridges two assets, so they don't look falsely related. |
| `findings()` | Aggregates issues, actions and facts per asset, with source documents, for the Findings view. |

`rebuild.py` re-runs extraction over stored chunks after a schema change. `join_chunks()` removes the chunk overlap first. There's no re-parsing and no re-embedding.

---

## 9. Stage G — Query understanding

**File:** `apps/web/src/lib/chatPrompt.ts`

| Function | Technique |
|---|---|
| `isSmallTalk()` | **Rule-based intent detection** (regex) for greetings and thanks. They skip retrieval and get a short reply. |
| `isOverviewQuestion()` | Detects collection-level questions ("summary", "what documents…"). The regex tolerates typos (`summanry`). |
| `retrievalQuery()` | **Conversational query rewriting**: a follow-up of ≤6 words ("and Pimpri?") is searched together with the previous question. **Query expansion**: overview questions get descriptive text appended so the search finds summary-style passages. |
| `buildCatalogChunk()` | For overview or weak-match questions, a synthetic passage lists the company's documents. |

On the Python side, `RAGPipeline.prepare()` also runs `extract_entities(query, use_nlp=False)` on the question. That's the fast path without spaCy, since latency matters for questions.

---

## 10. Stage H — Hybrid retrieval and rank fusion

**Files:** `rag/pipeline.py` (`RAGPipeline.prepare()`), `rag/local_store.py`

1. **Dense retrieval.** `local_store.search_chunks_with_stats()` computes `matrix @ query` (cosine) over the tenant's cached chunk matrix, top-k by `argpartition`.
   - **Similarity cut-off:** `min_similarity = 0.25` (MiniLM: relevant ≈ 0.35+, unrelated ≈ 0.2).
   - **Low-confidence fallback:** if nothing clears the cut-off, the 3 nearest passages are returned, flagged `low_confidence`. The prompt then tells the model they're only near matches.
2. **Graph-guided retrieval.** `retrieve_graph_local()` links question phrases (entities + `candidate_phrases(query)`) to graph nodes, walks the graph, and returns `{document_id: entity names}`. Passages from those documents that name a linked entity get **+0.05 similarity** (`graph_retrieval_boost`). The graph steers the ranking but every passage is still a real, citable one.
3. **Lexical retrieval** (when OpenSearch is enabled). `retrieve_text()` runs a BM25 `multi_match` with **fuzzy matching** (`fuzziness: AUTO`) and field boosts (`title^3`, `entities.value^2`, `equipment_tags^2`). This catches exact codes that embeddings blur.
4. **Reciprocal Rank Fusion.** `reciprocal_rank_fusion()` scores each passage as `Σ 1 / (k + rank)` with `k = 60` across all result lists, and keeps the top 8. Passages found by several methods rise to the top.

---

## 11. Stage I — Prompt construction (context engineering)

**Python:** `nlp_sts/step10_context_building.py`

| Function | Purpose |
|---|---|
| `enrich_chunks_with_entities()` | Tags each passage with the question entities it contains. |
| `enrich_chunks_with_graph()` | Attaches the graph relations touching those entities (`A --[REL]--> B`). |
| `_trim_to_token_budget()` | Keeps the highest-ranked passages within 12,000 estimated tokens. |
| `build_formatted_prompt()` / `prepare_context()` | Assembles the provider-agnostic `PreparedContext`. |

**Web app:** `chatPrompt.ts`

| Function | Purpose |
|---|---|
| `numberSources()` | Deduplicates passages and numbers them `[1]…[n]` for **citations**. |
| `buildSystemPrompt()` | **Grounding rules**: use only the context, cite, copy figures exactly, flag conflicts, reply in the question's language. It includes a **prompt-injection guard**: passages are data, not instructions. |
| `buildMessages()` | Puts the **most relevant passage last**, right before the question, because small models weigh nearby text most. Keeps the last 6 history turns, each truncated to 2,000 characters. |

---

## 12. Stage J — Generation

**File:** `apps/web/src/lib/llm.ts`, `streamChat()`

- One streaming interface over **Ollama** (`/api/chat`, which lets VEDA set `num_ctx`) and any **OpenAI-compatible** server (vLLM, LiteLLM, LM Studio, hosted APIs).
- `temperature = 0.2` by default, for factual answers.
- `apps/web/src/app/api/chat/route.ts` streams newline-delimited JSON events: first the `sources` (shown in the UI), then answer `token`s.

---

## 13. Tuning knobs (no code changes)

Everything domain-specific lives in `nlp_sts/graph_schema.json`. It can be replaced with `VEDA_GRAPH_SCHEMA_FILE` or extended per tenant via `tenants.settings.graph_schema`, which is merged by `step04_graph_schema.py::merge_schema()`.

| Setting | Default | Effect |
|---|---|---|
| `types.*.patterns / terms / examples` | — | What each entity type is (regex, gazetteer, few-shot examples) |
| `nlp.models` | `en_core_web_sm` | spaCy model(s) to try |
| `nlp.ner_labels` | PERSON, GPE/LOC/FAC | spaCy label → graph type |
| `nlp.type_cues` | "reported by", "site"… | Context words that vote for a type |
| `semantic.min_similarity` | 0.70 | Embedding-typing acceptance threshold |
| `semantic.min_margin` | 0.06 | Required lead over the second-best type |
| `semantic.merge_similarity` | 0.90 | Near-duplicate merge threshold |
| `semantic.query_link_similarity` | 0.78 | Question phrase → graph node threshold |
| `semantic.identifier_context_similarity` | 0.55 | Unknown-code typing threshold |
| `semantic.background_examples` | report, table, date… | Reject class |
| `relationships`, `detection_actions`, `co_occurrence_types` | — | Relation rules |

Retrieval settings use `VEDA_*` environment variables (`RAGSettings` in `rag/pipeline.py`): `VEDA_EMBEDDING_MODEL`, `VEDA_MIN_SIMILARITY`, `VEDA_FINAL_TOP_K`, `VEDA_RRF_K`, `VEDA_GRAPH_RETRIEVAL_BOOST`, `VEDA_MAX_CHUNK_SIZE`, `VEDA_CHUNK_OVERLAP`.

After changing the schema, rebuild the graph:

```bash
cd services/intelligence
python -m src.knowledge_graph.rebuild --tenant <slug>    # or --all
```

---

## 14. Worked example

Input line in a maintenance log:

> *Reported by Kiran Bhosale: repeated conductivity alarms on HD-K04 at Kothrud centre; conductivity cell replaced. Reading 13.8 mS/cm.*

Actual output of `extractor.extract_entities()` + `infer_relationships()` (spaCy `en_core_web_sm`, run without the embedding model, so Layer 4 is off):

| Step | Result |
|---|---|
| Layer 1 regex | `HD-K04` → EQUIPMENT_TAG (0.95); `13.8 mS/cm` → MEASUREMENT (0.90) with `{numeric_value: 13.8, unit: "mS/cm"}` |
| Layer 2 terms | "conductivity alarms" → FAILURE_MODE (0.85), normalised to "conductivity alarm" |
| Layer 3 spaCy | "Kiran Bhosale" → PERSON (label `PERSON`); "Kothrud" → LOCATION (label `GPE`), both 0.80 |
| Segmentation | the two sentences are separate segments, so the measurement in sentence 2 isn't wrongly paired with anything in sentence 1 |
| Relations | `HD-K04 FAILED_WITH conductivity alarm` · `HD-K04 LOCATED_IN Kothrud` · `HD-K04 ASSIGNED_TO Kiran Bhosale` · `Kiran Bhosale REPORTED_BY conductivity alarm` · `Kiran Bhosale WORKS_AT Kothrud` · `conductivity alarm OCCURRED_AT Kothrud` |
| Document node (when indexed) | `<file title> MENTIONS HD-K04`, `… MENTIONS conductivity alarm`, … |
| Question "what went wrong with HD-K04?" | `HD-K04` linked to its node → graph walk → passages naming HD-K04 boosted → RRF → cited answer |

Note that "conductivity cell replaced" produces no MAINTENANCE_ACTION here. The schema lists the noun form "conductivity cell replacement", and the term matcher handles plurals but not verb forms like "replaced". Writing "conductivity cell replacement" in the log, or adding the verb form as a term, would produce `HD-K04 MAINTAINED_BY conductivity cell replacement`.

---

## 15. Tests

The NLP behaviour is covered by unit tests in `services/intelligence/tests/unit/`:

- `test_entity_extractor.py`: patterns, terms, NER clean-up, voting
- `test_semantic_graph.py`: phrase mining, embedding typing, merging, identifier context
- `test_relationships.py`: segmentation and relation rules
- `test_chunk_builder.py`: chunking and prompt building
- `test_rag_pipeline.py`, `test_local_mode.py`: retrieval, RRF, local vector/graph search

Web-side prompt logic is tested under `apps/web/src/__tests__/`.

```bash
cd services/intelligence && python -m pytest tests/unit -q
```
