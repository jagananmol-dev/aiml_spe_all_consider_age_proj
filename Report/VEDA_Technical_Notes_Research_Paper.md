# VEDA: Technical Notes for the Research Paper

Oct 13, 2026 · @Dhruv\_Gangurde

## 1. Abstract and contributions

VEDA is a multi-tenant, domain-agnostic retrieval-augmented generation (RAG) platform. Any organisation uploads its own files and gets a grounded chat agent plus a knowledge graph built from those files, with no domain logic in code. These notes describe every technique as implemented in the repository, with the equations it computes, so each paragraph can be lifted into the paper.

**Problem.** Enterprise RAG systems are usually built for one domain. Their entity types, extraction rules and prompts are hard-coded. A healthcare company and a finance company cannot share them without re-engineering. Small local LLMs also hallucinate when retrieval is weak, and graph-augmented RAG often injects synthetic "graph facts" that cannot be cited.

**Proposed contributions (candidates for the paper's contribution list):**

1. **Schema-as-data knowledge graph.** Entity types, regex patterns, term lists, semantic examples and relation rules live in one JSON schema. Each tenant can extend it at runtime. A new industry needs no code change.
2. **Four-layer hybrid entity extraction.** Layers are regex patterns, lemma-aware term lists, spaCy NER with vote-based typing, and embedding-based zero-shot typing of noun phrases. The last layer uses a similarity threshold, a margin test and a background-class rejection.
3. **Context-typed identifiers.** Unknown codes such as "LN-2041" are typed by the words around them, not by the code itself.
4. **Collection-level type voting for names.** Each name gets one type across the whole collection, decided by weighted votes from NER labels, cue words and surname sharing.
5. **Graph-steered dense retrieval.** The graph never adds passages. It adds a small additive boost δ to real passages that mention entities linked to the question. Every citation stays traceable to source text.
6. **Single-encoder economy.** One MiniLM-L6-v2 encoder (384 dimensions) serves passage search, entity typing, node merging and query-to-graph linking, with an LRU phrase cache and one batched encode per document.
7. **Title-conditioned chunk embeddings and fragment merging.** Each chunk is embedded with its document title, and small structural fragments are merged up to 1,500 characters.
8. **Confidence-aware answering.** When no passage clears the similarity cut-off, the system returns the nearest k passages flagged as low-confidence and adds a document catalog. The model then says what the documents do not cover instead of guessing.
9. **Query-type routing.** Small talk skips retrieval, overview questions get a catalog passage, and short follow-ups are expanded with the previous question.
10. **Recency-aware prompt layout.** Passages are numbered by relevance but placed in reverse order, so the most relevant passage sits next to the question. The prompt also bounds the valid citation range and marks passages as data, not instructions.

**Evaluation setting.** A synthetic but realistic tenant (Nephrova Renal Care, a fictional dialysis company with 72 documents in 8 formats) with 22 known-answer chat questions. Results so far: 22/22 context recall, 6–26 ms search latency, about 12 ms per document for graph extraction, and a 1.7 s median time to first token on a laptop GPU.

## 2. System architecture

VEDA has two paths that share one tenant-scoped PostgreSQL store and one sentence encoder. The indexing path runs once per upload. The answering path runs once per question. The highlighted steps are the graph-steered retrieval contribution.

![VEDA architecture: indexing path, tenant store, answering path](veda_architecture.png)

The graph and the chunk store feed the answering path from above. Only chunk text ever reaches the LLM: the graph changes the ranking, not the context.

| Component | Technology | Role |
| --- | --- | --- |
| Web app and API | Next.js (TypeScript) | Upload, chat (NDJSON streaming), graph view, signed HMAC sessions, rate limits |
| Ingestion service | Python: PyMuPDF, pdfplumber, EasyOCR, python-docx, python-pptx, openpyxl | Parse 16 extensions to text, previews, status tracking |
| Intelligence service | Python, FastAPI, sentence-transformers, spaCy, NumPy | Chunking, embedding, extraction, graph, retrieval |
| Store | PostgreSQL (+ pgvector and Apache AGE in full mode) | Documents, chunks, vectors, graph; every query filtered by tenant id |
| Search (full mode) | OpenSearch | BM25 keyword retrieval for fusion |
| Queue (full mode) | Kafka + MinIO | Event-driven ingestion, object storage |
| LLM | Ollama (llama3 8B) or any OpenAI-compatible API | Answer generation |

**Two deployment modes.** Local mode needs only PostgreSQL and Python: the worker polls PostgreSQL, vectors are `REAL[]` columns searched in memory, and the graph uses two plain tables. Full mode adds Kafka, MinIO, pgvector (HNSW), Apache AGE and OpenSearch. The retrieval logic is the same in both.

**Tenant isolation.** A tenant is its agent: retrieval covers everything that tenant uploaded and nothing else. Every SQL query filters on `tenant_id`, the internal API requires a key and a UUID tenant id, and Cypher queries are parameterised and tenant-keyed.

## 3. Document ingestion and preprocessing

Every format is turned into plain text that keeps its structure (headings, records, slides), because the chunker splits on that structure. Sixteen file extensions across nine formats go to a parser chosen by extension (`PARSER_MAP`).

### 3.1 Format-specific parsers

| Format | Library | What is kept | Notable choice |
| --- | --- | --- | --- |
| PDF | PyMuPDF (text), pdfplumber (tables) | Per-page text, tables with page numbers | Ligatures expanded ("ﬁ" → "fi") so text matches typed queries |
| Images (png, jpg, tiff, bmp) | EasyOCR, GPU when available | Lines in reading order, per-box confidence and bounding box | No thresholding or denoising: it lowered accuracy on clean scans |
| Word (.docx) | python-docx | Paragraphs and tables in body order | Heading styles become `# Heading` so the chunker sees them |
| PowerPoint (.pptx) | python-pptx | Slide text, tables, speaker notes | Each slide starts with `Slide n` |
| Excel (.xlsx) | openpyxl, read-only streaming | Every sheet, row by row | Capped at 20,000 rows per sheet (zip-bomb guard) |
| CSV | csv.Sniffer | One `column: value` block per row | Delimiter detected from `, ; \t \|` |
| JSON / JSONL | json | One block per record, nested keys flattened to paths | JSONL fallback when whole-file parse fails |
| Text / Markdown | built-in | Text with normalised line endings | — |

### 3.2 OCR line reconstruction

EasyOCR returns unordered text boxes. Each box i has a top edge tᵢ, a bottom edge bᵢ and a left edge lᵢ. Boxes are sorted by (t, l), and each box joins the current line L when its vertical centre is within half its own height of the line's centre:

```latex
c_i = \frac{t_i + b_i}{2}, \qquad i \in L \iff \left| c_i - c_L \right| < \frac{b_i - t_i}{2}
```

Boxes inside a line are then ordered by lᵢ. A post-OCR rule repairs a common confusion: inside a tag-like token matching `[A-Z]{1,5}-[0-9O]{2,5}[A-Z]?`, a letter O in the numeric part becomes a zero ("P-1O1A" → "P-101A").

### 3.3 Record linearisation for structured data

Tabular and JSON data are turned into self-describing text, so each record can be retrieved alone and still say what its values mean. For a CSV with header (h₁ … hₙ), row r becomes the block

```latex
\mathrm{lin}(r) = \big\Vert_{j\,:\,v_{rj} \neq \varnothing} \; h_j \,\texttt{": "}\, v_{rj}
```

where ‖ joins lines and empty cells are dropped. Blocks are separated by blank lines, which the chunker treats as paragraph breaks. JSON is flattened recursively into `path.to.key: value` lines, with list indices as `[i]`. A list of scalars stays on one line.

### 3.4 Hierarchical structure-aware chunking

Chunking runs in three levels with a maximum chunk size M = 1,500 characters and overlap o = 200 characters (`chunk_builder.py`).

1. **Sections.** The text is split *before* each structural marker using a zero-width lookahead, so a heading stays with the section it introduces. Markers: numbered sections (`1.`, `2.1`), ALL-CAPS labels ending in a colon, Markdown headings `#`–`###`, and horizontal rules (`---`, `===`). With no markers, paragraphs (blank lines) are used.
2. **Paragraph packing.** A section longer than M is packed paragraph by paragraph. When the next paragraph would overflow, the chunk is closed and the next one starts with the last o characters of the previous chunk.
3. **Sentence fallback.** A packed chunk still longer than 1.5 M is split on sentence boundaries `(?<=[.!?])\s+`.

Structural splitting leaves fragments: a bare heading, or one CSV row. These lose their context and crowd out better passages at retrieval time. A greedy left-to-right merge joins neighbours while the result fits:

```latex
|c_{\text{last}}| + 2 + |c_i| \le M \;\Rightarrow\; c_{\text{last}} \leftarrow c_{\text{last}} \,\Vert\, \texttt{"\textbackslash n\textbackslash n"} \,\Vert\, c_i
```

This fixed retrieval misses on the demo tenant (see section 8).

### 3.5 Title-conditioned chunk embeddings

Each chunk cᵢ of document d is embedded together with the document title t\_d, and the vector is L2-normalised:

```latex
\mathbf{e}_i = \frac{f_\theta\!\left(t_d \,\Vert\, \texttt{"\textbackslash n\textbackslash n"} \,\Vert\, c_i\right)}{\left\lVert f_\theta\!\left(t_d \,\Vert\, \texttt{"\textbackslash n\textbackslash n"} \,\Vert\, c_i\right) \right\rVert_2} \in \mathbb{R}^{384}
```

f\_θ is all-MiniLM-L6-v2. Only the chunk text cᵢ is stored and shown, but its vector carries the title. A row such as "Alarm: conductivity, Machine: HD-K04" is then still found by a question about "the Kothrud alarm log". This is a cheap form of contextual chunk embedding that needs no LLM call per chunk.

### 3.6 Token budgeting

Token counts are estimated, not computed with a tokenizer:

```latex
\hat{\tau}(x) = \max\!\left(1, \left\lfloor |x| / 4 \right\rfloor\right)
```

The prepared context keeps the highest-ranked chunks while the running sum stays within B = 12,000 − τ̂(system prompt) − 500 tokens.

### 3.7 Queueing and fault tolerance

In local mode the worker claims jobs from PostgreSQL with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers never take the same document. Each claim increments `metadata.attempts`, and a file that crashes the worker three times is marked failed instead of looping. In full mode the same parsers run behind Kafka, with files in MinIO.

## 4. NLP techniques

Entity extraction is a four-layer cascade, ordered from most precise to most general. Each layer only claims text spans that earlier layers left free. All four are driven by the schema (section 5), so the code has no domain vocabulary. spaCy `en_core_web_sm` parses each document once, and that one parse supplies named entities, noun chunks, POS tags, dependency arcs and lemmas.

### 4.1 Layer 1: schema regular expressions

Each pattern p in the schema has a type, a regex, a normalisation rule and a fixed confidence c\_p. Shipped patterns cover asset codes (`HD-K04`, `RO-H1`, `P-101A`; c = 0.95), regulations and standards (`ISO 23500`, `NABH`, `DPDP Act 2023`, any capitalised "… Act/Rules/Regulations, YYYY"; c = 0.92 / 0.85) and measurements (number + one of 60 units, `mS/cm`, `EU/mL`, `mmHg`…; c = 0.90). A measurement match also stores its parsed value and unit as attributes. Normalisation `upper_dash` maps any whitespace to one dash and upper-cases, so "iso 23500" and "ISO-23500" become one node.

### 4.2 Layer 2: lemma-aware term lists

For a type with term list T, all terms are compiled into one case-insensitive alternation, sorted longest first so "bearing failure" wins over "bearing". Word boundaries stop "alignment" from matching inside "misalignment", and an optional plural suffix is allowed:

```latex
\texttt{\textbackslash b(?:} t_1 \,|\, t_2 \,|\, \dots \,|\, t_n \texttt{)(?:e?s)?\textbackslash b}, \qquad |t_1| \ge |t_2| \ge \dots \ge |t_n|
```

A match is mapped back to its listed term by stripping "es" or "s" only when the stripped form is in T:

```latex
\mathrm{canon}(w) = \begin{cases} w & w \in T \\ w_{[:-k]} & w_{[:-k]} \in T,\; k \in \{2, 1\} \text{ (suffix es, s)} \\ w & \text{otherwise} \end{cases}
```

Term matches have confidence 0.85.

### 4.3 Layer 3: spaCy NER with vote-based type resolution

spaCy labels are mapped through the schema (`PERSON → PERSON`; `GPE`, `LOC`, `FAC → LOCATION`). Small NER models make two systematic errors on business documents: they tag headings and table cells as names, and they read names in forms as places. Three mechanisms correct this.

**(a) Proper-name filter.** A span is kept only if it has 1–4 words, at least 3 characters, every word capitalised and alphabetic, every token tagged `PROPN`, and (for a person) at least two words.

**(b) Weighted mention votes.** Each mention m of name n casts votes for types. The NER label gives one vote. A cue word just before the name on its line ("Owner:", "Reported by", "Centre:", within 30 characters) gives w\_cue = 3 votes for the cue's type. Each coordinated or appositive sibling in the dependency tree ("Thomas, Kiran Bhosale, Pooja Shinde") that NER typed gives w\_conj = 2 votes for that sibling's type:

```latex
V(n, \tau) = \sum_{m \in M(n)} \Big( \mathbb{1}[\ell(m) = \tau] + w_{\text{cue}}\, \mathbb{1}[\mathrm{cue}(m) = \tau] + w_{\text{conj}} \sum_{s \in \mathrm{conj}(m)} \mathbb{1}[\ell(s) = \tau] \Big)
```

**(c) Collection-level resolution.** Votes are pooled across every document of the tenant (one batched `nlp.pipe` pass during a rebuild), so a name has one type across the whole graph:

```latex
\tau^{*}(n) = \begin{cases} \tau_{\text{known}}(n) & n \text{ already a graph node} \\ \arg\max_{\tau} V(n, \tau) & \text{otherwise} \end{cases}
```

A single-word name needs at least two mentions. Multi-word names then get one extra vote from each other name sharing their surname, computed from a snapshot so the result does not depend on order ("Kavita Pawar" read as a place is corrected by "Rahul Pawar" the person):

```latex
V'(n, \tau) = V(n, \tau) + \sum_{n' \neq n,\; \mathrm{last}(n') = \mathrm{last}(n)} \mathbb{1}[\tau^{*}(n') = \tau]
```

Two final filters apply. A PERSON must be multi-word. A multi-word "name" that contains a single-word name of a different type is dropped: it is a heading such as "Kothrud Hadapsar Pimpri".

### 4.4 Layer 4: zero-shot embedding typing of noun phrases

Patterns and lists only find what someone wrote down. This layer types everything else by nearest-example classification in embedding space.

**Candidate mining.** Candidates come from spaCy noun chunks. Leading determiners, numbers, stop words and participles are stripped ("the repeated conductivity alarms" → "conductivity alarms"), the head is lemmatised (→ "conductivity alarm"), and at most the last 4 words are kept, since English heads come last. Chunks with digits are left to layers 1 and 4b. Without spaCy, the fallback is runs of content words broken by stop words, verb forms, "-ed" words, digits and punctuation. Candidates are ranked by frequency, then word count, then first position, and the top 400 per document are kept.

**Eligibility.** A phrase must have at least 2 words, and its head must not be a background noun. "Incident report" or "disinfection log" names a record, not the thing itself.

**Type scores.** Each type k has an example set E\_k: its examples, its listed terms and its one-line description from the schema. With normalised vectors v, a phrase p scores against each type by its best example:

```latex
s_k(p) = \max_{x \in E_k} \; \mathbf{v}_p^{\top} \mathbf{v}_x, \qquad k^{*} = \arg\max_k s_k(p), \qquad s_{(2)}(p) = \max_{k \neq k^{*}} s_k(p)
```

A background class B (about 80 generic words such as "report", "table", "patient", "meeting", "invoice") gives b(p) = max over x in B of v\_pᵀv\_x.

**Decision rule with three tests.** The phrase takes type k\* only when it is similar enough, unambiguous and closer to a real type than to generic language:

```latex
\mathrm{type}(p) = \begin{cases} k^{*} & s_{k^{*}} \ge \theta \;\wedge\; s_{k^{*}} - s_{(2)} \ge \mu \;\wedge\; s_{k^{*}} > b(p) \;\wedge\; k^{*} \notin \mathcal{K}_{\text{id}} \\ \varnothing & \text{otherwise} \end{cases}
```

with θ = 0.70 and μ = 0.06. Identifier types (assets) are excluded because assets must come from codes. Confidence is capped below curated layers:

```latex
c(p) = \min\big(s_{k^{*}}(p),\; 0.8\big)
```

This is how "payment default" becomes an issue and "data breach" a failure in a finance tenant with no finance terms in the schema.

### 4.5 Layer 4b: context-typed identifiers

Codes no pattern knows (`LN-2041`, `AHU3`) match a generic identifier regex. A code is typed by its left context only: up to 3 content words before it on the same line, within 40 characters. Words after a code describe what it is about, not what it is ("RSK-04 Dialysis machine failure" is a risk, not a machine).

```latex
\mathrm{type}(\text{code}) = \arg\max_{x \in E_{\text{id}}} \mathbf{v}_{\mathrm{ctx}}^{\top} \mathbf{v}_x \quad \text{if} \quad \max_x \mathbf{v}_{\mathrm{ctx}}^{\top}\mathbf{v}_x \ge 0.55 \;\wedge\; > b(\mathrm{ctx})
```

So "loan LN-2041" becomes an asset or ID, while "policy HR-03" is rejected because "policy" is a background word.

### 4.6 Near-duplicate entity merging

Within each non-pattern type, values are clustered greedily (leader clustering). Existing graph node names come first, then new values by descending confidence, so established names win. Each value joins the first centre it is close enough to, otherwise it becomes a new centre:

```latex
\mathrm{canon}(v_i) = \begin{cases} \mathrm{canon}(v_{j^{*}}) & \max_{j \in C} \mathbf{v}_j^{\top}\mathbf{v}_i \ge \theta_m,\;\; v_i \notin P \\ v_i & \text{otherwise (} v_i \text{ added to } C\text{)} \end{cases}
```

with θ\_m = 0.90. P is the set of curated terms, which are never merged into each other ("disinfection" and "chemical disinfection" both stay). Pattern and identifier types are never merged, because P-101A and P-101B are different machines. This merges spelling variants such as "anaemia" / "anemia" into one node across documents.

### 4.7 Span de-duplication

Entities are sorted by (start offset, −confidence). An entity overlapping the previous kept entity of the same type is dropped, so the most confident reading of a span survives.

### 4.8 Relation extraction

Relations are inferred by typed co-occurrence within a segment, not across a whole document. Pairing across a document had linked a standby pump to its neighbour's bearing failure.

**Segmentation.** A block of lines in which at least 60% are `key: value` lines is a record block. It is split into records where the flattened JSON parent path changes (`site.areas[0].equipment[1].tag`). Other text is split into lines and then sentences with `(?<=[.!?])\s+(?=[A-Z0-9])`.

**Typed rules.** The schema lists 15 directed rules R : (τ\_s, τ\_t) → r, such as (asset, issue) → FAILED\_WITH, (issue, action) → REPAIRED\_BY and (condition, medication) → TREATED\_WITH. For each pair in a segment the rule is looked up in both directions. An issue paired with a detection action (inspection, hydrotest…) becomes DETECTED\_BY instead of REPAIRED\_BY. Two different entities of a co-occurrence type (asset, chemical, regulation) with no rule get an undirected CO\_OCCURS\_WITH edge, stored once in lexical order. Edge confidence is the mean of the two entities' confidences:

```latex
\mathrm{conf}(a \xrightarrow{r} b) = \tfrac{1}{2}\big(c(a) + c(b)\big), \qquad r = R(\tau_a, \tau_b) \;\text{or}\; R(\tau_b, \tau_a)
```

### 4.9 Efficiency of the NLP stage

One encoder serves all embedding steps. Each phrase is encoded once per process (an LRU cache of 50,000 vectors), all uncached phrases of a document go to the model in one batch, and the example matrix is encoded once per schema version (keyed by a schema fingerprint). Typing a document is therefore one matrix product of size (candidates × examples). On the demo tenant this takes about 12 ms per document.

## 5. Knowledge graph construction

The graph is derived data: a typed property graph G = (V, E) per tenant, built from the entities and relations of section 4, and rebuilt from stored chunks whenever the schema changes. Its role in question answering is to steer retrieval (section 6.4), not to supply text.

### 5.1 Schema as data

One JSON file (`graph_schema.json`) defines everything domain-specific:

| Schema block | Contents | Used by |
| --- | --- | --- |
| `types` (10) | Label, colour, role (subject, issue, action, governance, value, treatment, person, place, document), regex patterns, term lists, example phrases, description, `identifier` and `leaf` flags | Layers 1, 2, 4 and the walk |
| `relationships` (15) | Directed rules (source type, target type) → relation, plus inverse name | Relation extraction, walk |
| `document_links` | Document node type, MENTIONS relation, excluded roles, cap of 25 | Document nodes |
| `nlp` | spaCy model list, NER label map, cue words per type, noun-chunk switch, 200,000-character limit | Layer 3 |
| `semantic` | θ = 0.70, μ = 0.06, θ\_m = 0.90, query-link threshold 0.78, confidence cap 0.8, phrase limits, identifier regex and threshold 0.55, \~80 background words | Layer 4, merging, query linking |
| `detection_actions`, `co_occurrence_types` | Actions that detect rather than repair; types that co-occur | Relation extraction |

**Per-tenant extension.** A tenant stores a partial schema of the same shape in `tenants.settings.graph_schema`. It is merged with the base schema as S\_t = merge(S\_base, Δ\_t): type fields are merged field by field (lists appended, scalars replaced), relationship lists are appended, and setting blocks are merged key by key. Each compiled schema has a fingerprint, which keys the typer cache, so tenants with different schemas never share example matrices.

### 5.2 Storage model

In local mode the graph lives in two PostgreSQL tables. A node is unique on (tenant, type, normalised value), so the same entity in many documents is one node:

```latex
V_t = \{ (\tau, \tilde{v}) \}, \qquad E_t = \{ (d, u, w, r, c) : u, w \in V_t,\; d \in D_t \}
```

Each edge keeps the document d that produced it. Replacing a document's graph deletes only that document's edges, then upserts nodes and inserts edges, all in one transaction. Deleting a document cascades to its edges, and nodes with no remaining edge are pruned. When edges are read, duplicates across documents are grouped and their confidence is the maximum. In full mode the same model runs on Apache AGE (openCypher on PostgreSQL) with parameterised, tenant-keyed queries.

### 5.3 Document nodes

Every indexed document becomes a DOCUMENT node linked by MENTIONS to the entities it names most often:

```latex
E_{\text{doc}}(d) = \mathrm{top}_{25}\Big\{ (d \xrightarrow{\text{MENTIONS}} e) : e \in \mathcal{E}(d),\; \mathrm{role}(\tau_e) \notin \{\text{value}, \text{document}\} \Big\} \text{ ranked by } \mathrm{count}_d(e)
```

Measurements are left out because a value belongs to the asset it was read on. Document nodes make every upload visible in the graph and give a path between two documents that discuss the same asset, issue or regulation.

### 5.4 Two-pass collection rebuild

1. **Parse and vote.** All documents of a tenant are parsed once with `nlp.pipe` (batch 8). Name types are resolved by the collection-level vote of section 4.3.
2. **Extract.** The graph is cleared, and each document's entities and edges are extracted from its stored parse with the decided name types. Orphan nodes are deleted.

Text is rebuilt from stored chunks by removing the overlap between consecutive chunks: the longest suffix of the text so far that equals a prefix of the next chunk (21 to 600 characters) is dropped. Nothing is re-parsed from files or re-embedded.

### 5.5 Bridge-blocked graph walk

Retrieval walks the graph breadth-first from linked nodes, up to h = 2 hops and 30 edges. Edges are traversed in both directions, reverse edges taking their inverse name (FAILED\_WITH ↔ FAILURE\_OF). Two rules keep the walk meaningful:

- **Leaf stop.** The walk never expands from a leaf type (measurement, document) other than the start node.
- **Bridge blocking.** From a non-subject node (such as the issue "bearing failure" or the action "inspection"), the walk may not step to a subject (asset) node. A shared generic concept therefore cannot make two unrelated assets look connected.

```latex
\mathrm{expand}(u \to w) \iff \big(u = s \;\vee\; \tau_u \notin \mathcal{T}_{\text{leaf}}\big) \;\wedge\; \neg\big(u \neq s \;\wedge\; \tau_u \notin \mathcal{T}_{\text{subj}} \;\wedge\; \tau_w \in \mathcal{T}_{\text{subj}}\big)
```

where s is the start node. When the same text matches several node types, a subject node is preferred as the start.

### 5.6 Graph-derived findings

The Maintenance Intel view is computed from the graph, not from a separate table. For each subject node it lists the issues, actions, measurements and regulations reachable from it, with the documents that state them.

### 5.7 Deterministic graph layout (UI)

The Knowledge Graph screen uses a custom force-directed layout with no randomness, so the same graph always renders the same picture. Nodes in each connected component start on a circle of radius 30 + 14√n. For 300 iterations (150 when n > 300), each node i receives a force from three sources:

```latex
\mathbf{F}_i = \underbrace{\sum_{j \neq i} 0.05\, \frac{\rho^2}{\lVert \mathbf{x}_i - \mathbf{x}_j \rVert^2} (\mathbf{x}_i - \mathbf{x}_j)}_{\text{repulsion},\; \rho = 90} \;+\; \underbrace{\sum_{(i,j) \in E} 0.1\, \frac{d_{ij} - L_{ij}}{d_{ij}} (\mathbf{x}_j - \mathbf{x}_i)}_{\text{label-aware springs}} \;-\; \underbrace{0.01\, \mathbf{x}_i}_{\text{gravity}}
```

The spring rest length depends on how wide the two labels are: L\_ij = 50 + (w\_i + w\_j)/4. Each step is clipped by a linear cooling schedule:

```latex
\mathbf{x}_i \leftarrow \mathbf{x}_i + \mathbf{F}_i \cdot \min\!\left(1, \frac{14\,(1 - t/T) + 0.5}{\lVert \mathbf{F}_i \rVert}\right)
```

A collision pass then treats each node as a box (circle plus label, w × h) and, for up to 80 passes, separates any overlapping pair along the axis of smaller overlap by half the overlap each (6-unit padding). Finally, components are shelf-packed largest first into rows of width √(1.6 · Σ area), which gives a 16:10 canvas, and the view zooms to fit. Node radius grows with degree: r = min(16, r₀ + 0.8 · deg), with r₀ = 8 for subjects and 5 otherwise.

**Demo graph.** After a rebuild the Nephrova tenant has 166 nodes and 342 edges, and keeps all 31 manually reviewed edges.

## 6. RAG pipeline

A question passes through seven stages: routing, query rewriting, embedding, graph linking, graph-steered dense search with a confidence fallback, fusion, and prompt assembly with streamed generation. Every stage is scoped to one tenant, and every passage the model sees is real, citable document text.

### 6.1 Query-type routing

The web layer (`chatPrompt.ts`) classifies the message before any search:

| Class | Detector | Action |
| --- | --- | --- |
| Small talk | Anchored regex: greetings, thanks, "ok", "bye" | Skip retrieval; answer in 1–2 sentences (about 2–3 s) |
| Overview | 8 regexes: "summary" (typo-tolerant `summ?\w*r\w*`), "overview", "what topics / documents", "list our files"… | Add a catalog passage of all documents; keep top 4 passages; at most 8 bullets |
| Short follow-up | ≤ 6 words and a previous user turn exists | Search with the previous question prepended |
| Regular | Everything else | Standard pipeline |

### 6.2 Query rewriting

Let q be the message and q₋ the previous user question. The retrieval query is

```latex
q' = \begin{cases} q_{-} \,\Vert\, \texttt{"\textbackslash n"} \,\Vert\, q & |q|_{\text{words}} \le 6 \;\wedge\; q_{-} \text{ exists} \\ q & \text{otherwise} \end{cases} \qquad q'' = \begin{cases} q' \,\Vert\, x_{\text{ov}} & \mathrm{overview}(q) \\ q' & \text{otherwise} \end{cases}
```

where x\_ov is a fixed expansion ("Overview and summary of the organisation, its services, and its recent key events and results"). "Summary" alone matches nothing; the expansion pulls the passages that summarise the organisation, such as board notes and manual introductions. The answer still responds to the original q.

### 6.3 Dense retrieval

The query is embedded with the same encoder as the chunks, v\_q = f\_θ(q'') / ‖f\_θ(q'')‖. Because all vectors are L2-normalised, cosine similarity is a dot product, and all chunk scores of a tenant are one matrix-vector product:

```latex
\mathbf{s} = \mathbf{E}_t\, \mathbf{v}_q, \qquad \mathbf{E}_t \in \mathbb{R}^{N_t \times 384}, \qquad s_i = \cos(\mathbf{e}_i, \mathbf{v}_q)
```

The top k = 15 are selected in linear time with `argpartition`, then sorted. In local mode E\_t is held in memory per tenant. In full mode the same query runs in pgvector, ordered by the `<=>` cosine distance operator over an HNSW index.

**Fingerprint-invalidated index cache.** Decoding all stored vectors per query cost 0.3–1.4 s. Each tenant's matrix is therefore cached and reloaded only when a cheap fingerprint changes. PostgreSQL's `xmin` is the id of the transaction that last wrote a row, so any insert, update or delete changes the fingerprint:

```latex
\phi_t = \Big( |C_t|,\; \max_{c \in C_t} \mathrm{xmin}(c),\; |D_t^{\text{indexed}}|,\; \max_{d \in D_t} \mathrm{xmin}(d) \Big)
```

This cut search to 6–26 ms. Connections are reused per worker thread, since a new connection costs about 100 ms on Windows.

### 6.4 Graph-steered retrieval (graph as a re-ranking prior)

The graph changes the ranking of real passages instead of adding synthetic "graph fact" passages that the model could cite but the user could not verify.

**Step 1: question phrases.** P\_q is the union of entities found in the question by layers 1–2 (spaCy is skipped for latency) and up to 12 candidate phrases from the content-word miner.

**Step 2: entity linking.** Each phrase links to a node by exact name (score 1) or to its nearest node by cosine similarity if it clears θ\_link = 0.78. The 5 best nodes are kept:

```latex
\mathcal{N}_q = \mathrm{top}_5 \Big( \{ n : \tilde{v}_n = p \} \;\cup\; \{ \arg\max_n \mathbf{v}_p^{\top}\mathbf{v}_n : \max_n \mathbf{v}_p^{\top}\mathbf{v}_n \ge 0.78 \} \Big)_{p \in P_q}
```

Node vectors are encoded once per graph version, with the same cache and encoder.

**Step 3: walk and boost map.** The bridge-blocked walk (section 5.5) runs from each linked node. For each walked edge produced by document d, any endpoint that is a linked node is recorded: B(d) is the set of linked entity names that document d's graph ties to.

**Step 4: boosted score.** A chunk of document d gets an additive bonus δ = 0.05 if its text names one of those entities:

```latex
s'_i = s_i + \delta \cdot \mathbb{1}\big[\exists\, n \in B(d_i) : n \sqsubseteq \mathrm{lower}(c_i)\big]
```

where ⊑ means "occurs as a substring of". The bonus is small compared with the gap between relevant (≈ 0.37+) and unrelated (≈ 0.20) passages, so it reorders near-ties without lifting irrelevant text. Both conditions are needed: the document must be linked to the entity in the graph, and the specific chunk must name it.

### 6.5 Similarity cut-off and confidence-aware fallback

Passages below τ\_min = 0.25 are dropped (calibrated on MiniLM: relevant ≈ 0.37+, unrelated ≈ 0.20). If none clears it, the search does not return nothing. It returns the k\_fb = 3 nearest passages and raises a low-confidence flag:

```latex
R(q) = \begin{cases} \{ c_i \in \mathrm{top}_{15}(\mathbf{s}') : s'_i \ge \tau_{\min} \} & \max_i s'_i \ge \tau_{\min} \\ \mathrm{top}_{3}(\mathbf{s}'), \;\; \texttt{low\_confidence} = 1 & \text{otherwise} \end{cases}
```

With the flag set, the web layer adds the document catalog and an instruction: use any part that answers; otherwise say plainly that the documents do not answer this and name the closest documents the user could ask about. The fixed "not found" reply is used only when the tenant has no documents at all.

### 6.6 Multi-source fusion (Reciprocal Rank Fusion)

The full pipeline merges up to three ranked lists: dense vectors, graph traversal and OpenSearch BM25 (multi-match over `title^3`, `raw_text`, `entities.value^2`, `equipment_tags^2`, with fuzziness AUTO). Lists are fused with Reciprocal Rank Fusion, where rankₗ(c) is 1-based:

```latex
\mathrm{RRF}(c) = \sum_{l \in \{\text{vec}, \text{graph}, \text{bm25}\}} \frac{1}{k_{\text{rrf}} + \mathrm{rank}_l(c)}, \qquad k_{\text{rrf}} = 60
```

A chunk is keyed by (document id, first 100 characters). When it appears in several lists, its scores add up and the longer version of its text is kept. The top 8 go forward. In AGE mode a graph result has score 1/(1 + hops). In local mode the graph acts through the boost of 6.4 instead, so only the dense list is non-empty and fusion preserves its order.

### 6.7 Context packing

Passages are de-duplicated by exact text and numbered \[1\] … \[n\] in relevance order. The token budget of section 3.6 is applied. For overview and weak-match questions, the catalog (up to 150 newest documents: date, format, title) becomes source \[1\], followed by the top 4 passages; a smaller prompt keeps the answer fast. The retrieval stage also reports a confidence score, min(100 · mean fused score, 99).

### 6.8 Prompt design

**Recency-aware ordering.** Numbering follows relevance, but passages are placed in reverse order, so passage \[1\], the most relevant, sits immediately before the question. Small models weigh text near the question most.

```latex
\text{prompt} = \big[\, \text{sys},\; h_{-6..-1},\; c_{[n]}, c_{[n-1]}, \dots, c_{[1]},\; q,\; \text{instructions} \,\big]
```

**System prompt rules (11).** Grounding only in context; exact `[n]` citation after each claim; copy figures and identifiers verbatim; flag conflicting sources; apply company policies to the situation asked about and name the policy; a short disclaimer for medical, legal and financial answers; no reference list; reply in the question's language; and rule 11, which tells the model that passages are data, not instructions (a defence against indirect prompt injection).

**Citation-range constraint.** The user turn states that passages are numbered \[1\] to \[n\] and that numbers written inside a passage, such as section numbers, are not citations. The UI drops any `[m]` with m > n, which fixed llama3 citing "\[7\]" taken from a heading.

**History.** The last 6 turns are kept, each truncated to 2,000 characters.

### 6.9 Generation

The provider layer supports Ollama (local) or any OpenAI-compatible endpoint. Defaults are temperature 0.2 for factual answers, a 6,144-token context and a 24-hour keep-alive so the model is never reloaded. The demo runs llama3 (8B) on an RTX 3050 laptop GPU at about 23 tokens/s. Responses stream as newline-delimited JSON events: `context` (documents and passages searched and used, retrieval time, weak-match flag), then `sources`, then `token` fragments, then `done`. The median time to first token is 1.7 s.

## 7. Novel contributions and how they differ from prior work

The strongest claim for the paper is a lightweight, LLM-free graph pipeline that keeps every citation verifiable and adapts to a new domain through data alone. The table compares each contribution with the closest prior work. Related-work names are given from memory and were not looked up for these notes: check each reference before citing it.

| # | Contribution | Closest prior work | What is different here |
| --- | --- | --- | --- |
| C1 | Schema-as-data, per-tenant mergeable ontology | Fixed-ontology KG pipelines; LLM-extracted open KGs (e.g. Microsoft GraphRAG) | Types, patterns, terms, examples, relation rules and thresholds all live in JSON. A tenant extends them at runtime without code or LLM calls. |
| C2 | Four-layer extraction cascade (regex → lemma terms → voted NER → zero-shot embedding typing) | Rule-based IE; spaCy NER; zero-shot NER models (e.g. GLiNER) | Precision-ordered layers that only fill free spans. Zero-shot typing reuses the retrieval encoder, so it adds no second model. |
| C3 | Three-test zero-shot decision rule (threshold θ, margin μ, background class) | Nearest-centroid / prototype classifiers | The explicit background class and the head-noun filter reject generic phrases ("incident report") that plain thresholds accept. |
| C4 | Context-typed identifiers (left-context only) | Pattern-based ID recognition | An unknown code is typed by the 3 words before it. Ignoring words after the code avoids typing "RSK-04 Dialysis machine failure" as a machine. |
| C5 | Collection-level weighted name-type voting (NER + cues ×3 + coordination ×2 + surname sharing) | Document-level NER; entity-linking consistency constraints | Corrects small-model NER errors on forms and tables with no training, and gives one type per name across a tenant. |
| C6 | Bridge-blocked, leaf-stopping graph walk | k-hop expansion; personalised PageRank (e.g. HippoRAG) | A generic shared concept cannot connect two unrelated assets, which removes a common source of spurious multi-hop context. |
| C7 | Graph as a re-ranking prior, never a passage source | GraphRAG community summaries; KG-to-text triples in the prompt | The graph only adds δ = 0.05 to real passages. Every citation points at verbatim document text. |
| C8 | Title-conditioned chunk embeddings plus fragment merging | Contextual chunk embeddings that call an LLM per chunk (e.g. Anthropic's Contextual Retrieval) | The document title is a free, deterministic context string. No LLM calls are needed at index time. |
| C9 | Confidence-aware fallback with a catalog | Corrective / self-reflective RAG (e.g. CRAG, Self-RAG) | No extra LLM call or evaluator model. A calibrated cosine threshold flags weak retrieval, and the prompt switches to "say what is missing and point to related documents". |
| C10 | Reverse-order passage placement with relevance numbering | "Lost in the middle" findings (Liu et al.) | Puts the top passage next to the question for small local models, while keeping \[1\] = most relevant for the user. |
| C11 | Citation-range constraint and passage-as-data rule | Citation-generation prompting; prompt-injection defences | Combines a bounded citation set in the prompt with UI-side removal of invalid citations. |
| C12 | xmin-fingerprint cache for an in-memory per-tenant index | Vector databases with background index refresh | Exact consistency with the database at the cost of one aggregate query, with no triggers or change feed. |

### 7.1 Suggested framing

1. **Main thesis.** Graph-augmented RAG does not need an LLM to build the graph or text from the graph to help. A schema-driven, embedding-typed graph used as a re-ranking prior gives the structural benefit while every citation stays verifiable.
2. **Secondary thesis.** One small sentence encoder (22M parameters, 384 dimensions) can serve retrieval, zero-shot entity typing, entity resolution and query linking at once, which makes the system run on a laptop.
3. **Practical thesis.** Domain transfer becomes a data task: a healthcare tenant was added by editing the schema JSON (new tags, CONDITION and MEDICATION types, TREATED\_WITH, clinical units), with no code change.

### 7.2 Claims that need evidence before submission

- C7: an ablation with δ ∈ {0, 0.02, 0.05, 0.1} and the graph off.
- C8: title-conditioned versus plain chunk embeddings on the same question set.
- C3: precision and recall of zero-shot typing against a hand-labelled sample, with and without the background class and the margin.
- C5: name-type accuracy of raw spaCy versus the voting scheme.
- C10: answer accuracy with forward versus reverse passage order.

## 8. Evaluation methodology and metrics

Current evidence is one synthetic tenant with 22 known-answer questions, which passes 22/22. That is enough for a system paper's case study, but a research paper also needs the ablations listed in 7.2 and at least one public benchmark.

### 8.1 Dataset: the Nephrova tenant

Nephrova Renal Care is a fictional outpatient haemodialysis company with three centres in Pune. It has 72 documents in 8 formats (PDF, Word, PowerPoint, Excel, CSV, JSON/JSONL, Markdown, text), uploaded one per day from 2026-07-30 to 2026-10-09. The set includes 6 HR and 5 finance policies, three long cross-referencing documents (operations manual, risk and asset register, Q3 board pack), and planted multi-document stories, such as a water-plant endotoxin incident traced across a lab report, an RCA, an incident report and minutes. All facts come from one generator (`company.py`), so ground truth is known.

### 8.2 Question set

| Category | Count | Example | Tests |
| --- | --- | --- | --- |
| Single-fact lookup | 12 | "What was the endotoxin result for RO-H1 in August 2026?" | Exact figure retrieval from tables, logs, lab reports |
| Policy application | 6 | "A centre manager wants to buy a part costing INR 40,000. Can they approve it?" | Retrieve a rule and apply it to a new case |
| Cross-document reasoning | 4 | "Was the Hadapsar water incident a known risk before it happened?" | Linking the risk register to the incident |

### 8.3 Metrics

**Answer accuracy (as implemented).** A question passes when every expected key string appears in the answer, case-insensitively:

```latex
\mathrm{Acc} = \frac{1}{|Q|} \sum_{q \in Q} \prod_{a \in A_q} \mathbb{1}\big[ a \sqsubseteq \mathrm{lower}(\hat{y}_q) \big]
```

**Citation validity (as implemented).** The share of answers whose cited indices all fall in the range of passages sent:

```latex
\mathrm{CitVal} = \frac{1}{|Q|} \sum_{q} \mathbb{1}\big[ \mathrm{cites}(\hat{y}_q) \subseteq \{1, \dots, n_q\} \big]
```

**Context recall (as reported).** Whether the passages sent contain the evidence needed for the answer. Reported as 22/22.

**Metrics to add for the paper:**

```latex
\mathrm{Recall@}k = \frac{1}{|Q|} \sum_{q} \mathbb{1}\big[ G_q \cap R_k(q) \neq \varnothing \big], \qquad \mathrm{MRR} = \frac{1}{|Q|} \sum_{q} \frac{1}{\mathrm{rank}_q}, \qquad \mathrm{nDCG@}k = \frac{\sum_{i=1}^{k} \frac{2^{rel_i}-1}{\log_2(i+1)}}{\mathrm{IDCG@}k}
```

where G\_q is the set of gold evidence chunks. For entity extraction, report per-type precision, recall and F1 on a hand-labelled sample:

```latex
P = \frac{TP}{TP + FP}, \qquad R = \frac{TP}{TP + FN}, \qquad F_1 = \frac{2PR}{P + R}
```

For grounding, report faithfulness: the share of answer claims supported by a cited passage, judged by people or an LLM judge such as RAGAS faithfulness.

### 8.4 Measured results so far

| Measure | Value | Setting |
| --- | --- | --- |
| Known-answer accuracy | 22/22 | llama3 8B, local mode |
| Context recall | 22/22 | Same questions, after the graph schema rebuild |
| Dense search latency | 6–26 ms | In-memory per-tenant index (was 0.3–1.4 s without the cache) |
| Graph extraction | ≈ 12 ms per document | One batched encode, cached phrases |
| Time to first token, median | 1.7 s | RTX 3050 6 GB, i5-13450HX, 16 GB RAM |
| Generation speed | ≈ 23 tokens/s | llama3 via Ollama |
| Greeting reply | ≈ 2–3 s | No retrieval |
| Graph size | 166 nodes, 342 edges | Includes the 31 manually reviewed edges |
| Automated tests | 447 Python + 222 web | Unit, integration, security (Cypher injection) |

### 8.5 Recorded failure analyses

- **Fragment chunks.** Bare headings and single CSV rows crowded out real passages. Fixed by fragment merging (3.4) and title conditioning (3.5).
- **Out-of-range citations.** llama3 cited "\[7\]" from a section number. Fixed by the citation-range instruction and UI filtering (6.8).
- **"Summary" questions.** These matched nothing semantically. Fixed by overview routing, query expansion and the catalog (6.1–6.2).
- **Whole-document relation pairing.** This linked a standby pump to its neighbour's failure. Fixed by segment-scoped relation extraction (4.8).
- **NER on forms.** Names in tables were read as places. Fixed by cue and surname voting (4.3).

### 8.6 Recommended ablation grid

| Variant | Changes | Expected effect to verify |
| --- | --- | --- |
| Full system | — | Baseline |
| − graph boost | δ = 0 | Lower Recall@k on entity-centric questions |
| − title conditioning | Embed cᵢ only | Lower recall on tabular and record questions |
| − fragment merging | No merge | More fragment passages in the top k |
| − fallback | Return nothing below τ\_min | More "not found" answers |
| Forward order | Passages in order \[1\] … \[n\] | Possible accuracy drop with small LLMs |
| − background class | Drop b(p) test | Lower typing precision |
| Graph as passages | Add walked edges as text passages | More citations to non-verbatim text |

## 9. Limitations and future work

The main threats to validity are a single synthetic tenant and a substring-based accuracy metric. Both should be stated openly in the paper.

**Method limitations**

- **Evaluation scale.** One synthetic tenant and 22 questions, written by the same team that built the system. Add public benchmarks (for example multi-hop QA sets) and a second real-world domain such as finance.
- **English only.** The stop-word list, verb forms, spaCy model and MiniLM encoder are English. The OCR default is English only, because adding Hindi made EasyOCR read Latin digits as Devanagari.
- **Thresholds are hand-calibrated.** θ, μ, θ\_m, θ\_link, τ\_min and δ were tuned on the demo tenant. A sensitivity analysis is needed.
- **Linear-time local search.** The in-memory index is a brute-force scan, O(N\_t · 384) per query. This suits small tenants; larger ones need the pgvector HNSW path.
- **Relation extraction is co-occurrence plus type rules.** It cannot tell negation ("no leak found") or tense from a real relation.
- **Character-based token estimate.** |x|/4 can be off for tables and non-English text.
- **Hybrid fusion is untested locally.** In local mode BM25 is off, so RRF only sees the dense list.

**System limitations (from the readiness review, still open)**

- One login per company: no invites, roles or password reset.
- Row-level security is not effective yet, because the app connects as the table owner.
- Sessions cannot be revoked before their 24-hour expiry, and there is no audit log.
- Caches are per process, and a parser that hangs (rather than crashes) stalls the queue.

**Future work**

1. A learned or LLM-assisted relation classifier on top of the typed rules, with negation detection.
2. Learning δ and τ\_min per tenant from click or feedback signals.
3. Multilingual encoder and spaCy models selected per tenant through the schema's `nlp.models` list.
4. A cross-encoder re-ranker after fusion, compared against the graph prior.
5. Personalised PageRank over the bridge-blocked graph as an alternative to the fixed-hop walk.

## 10. Code map

Each technique and the file that implements it, for the paper's reproducibility appendix.

| Technique | Section | File |
| --- | --- | --- |
| Format parsers, OCR line grouping, record linearisation | 3.1–3.3 | `services/ingestion/src/workers/ingestion_worker.py` |
| Job claiming with SKIP LOCKED, retry cap | 3.7 | `services/ingestion/src/workers/local_worker.py` |
| Hierarchical chunking, fragment merging, token budget, prompt builder | 3.4, 3.6 | `services/intelligence/src/knowledge_graph/chunk_builder.py` |
| Title-conditioned embeddings, retrieval orchestration, RRF | 3.5, 6.3–6.6 | `services/intelligence/src/rag/pipeline.py` |
| In-memory index, xmin fingerprint, graph boost, fallback | 6.3–6.5 | `services/intelligence/src/rag/local_store.py` |
| Extraction cascade, NER voting, merging, de-duplication | 4.1–4.7 | `services/intelligence/src/entity_extraction/extractor.py` |
| Zero-shot typing, candidate mining, identifier context, LRU cache | 4.4–4.6, 4.9 | `services/intelligence/src/entity_extraction/semantic.py` |
| Schema loading, tenant merge, plural-aware term patterns | 4.2, 5.1 | `services/intelligence/src/entity_extraction/schema.py` |
| The schema itself | 5.1 | `services/intelligence/src/entity_extraction/graph_schema.json` |
| Segment-scoped relation extraction, document edges | 4.8, 5.3 | `services/intelligence/src/knowledge_graph/relationships.py` |
| Graph storage, bridge-blocked walk, query linking, findings | 5.2, 5.5, 5.6, 6.4 | `services/intelligence/src/knowledge_graph/local_graph.py` |
| Two-pass rebuild, overlap removal | 5.4 | `services/intelligence/src/knowledge_graph/rebuild.py` |
| Apache AGE backend | 5.2 | `services/intelligence/src/knowledge_graph/graph_manager.py` |
| Routing, query rewriting, catalog, prompt layout | 6.1–6.2, 6.7–6.8 | `apps/web/src/lib/chatPrompt.ts` |
| Chat endpoint and NDJSON streaming | 6.9 | `apps/web/src/app/api/chat/route.ts` |
| LLM provider layer | 6.9 | `apps/web/src/lib/llm.ts` |
| Force-directed layout, collisions, shelf packing | 5.7 | `apps/web/src/lib/graphLayout.ts` |
| Known-answer evaluation | 8 | `scripts/demo/check_chat.py` |
| Dataset generator and ground truth | 8.1 | `scripts/demo/generate_dataset.py`, `scripts/demo/company.py` |
