# VEDA AI — Company Knowledge Agent

**Upload your company's documents. Get a chatbot and a knowledge graph that answer from them, and only from them.**

VEDA is a multi-tenant RAG (retrieval-augmented generation) platform. Any company, whether healthcare, finance, manufacturing or anything else, signs up, uploads its files, and gets its own agent: a chat assistant grounded in its documents with citations, a knowledge graph of the assets, issues and actions those documents describe, and dashboards built from them. Nothing about a domain is hardcoded. Entity types, vocabularies and relationship rules are data, and each company can extend them.

---

## Why VEDA

| | |
|:--|:--|
| **One agent per company** | A tenant *is* its agent. Retrieval runs over everything that tenant has uploaded and never touches another tenant's data (every query is tenant-scoped, and PostgreSQL row-level security is enabled). |
| **Grounded answers with sources** | Every answer is built from retrieved passages and cites them `[1]`, `[2]`. The UI shows which documents and passages were used and how long retrieval took. If nothing matches well, the answer says so and points to what the documents *do* cover. |
| **Domain-agnostic knowledge graph** | Entities and relationships come from `graph_schema.json` plus per-tenant extensions, not from code. spaCy finds people, places and noun phrases, and embeddings type phrases nobody listed, such as "payment default" or "data breach", so a new industry works without code changes. Every uploaded document becomes a node linked to what it mentions. |
| **Efficient embeddings** | One MiniLM model serves search, entity typing and graph linking. Phrase vectors are cached and documents are embedded in one batch each, so typing a document is a single matrix product. Measured on the demo: about 12 ms per document for graph extraction and 6–26 ms per search. |
| **Many formats** | PDF, Word, PowerPoint, Excel, CSV, JSON/JSONL, Markdown, text, and images through OCR. Office files get an in-browser preview. |
| **Runs on a laptop** | Local mode needs only PostgreSQL and Python. There is no Docker, Kafka or vector extension, and Ollama provides a local LLM. Full mode scales out with Kafka, MinIO, pgvector, Apache AGE and OpenSearch. |
| **Private LLM by default** | Chat uses Ollama (local) or any OpenAI-compatible endpoint. Documents never have to leave your infrastructure. |
| **Tested** | 447 Python tests (357 intelligence, 90 ingestion) and 222 web tests, CI with lint and type checks, and a demo tenant with scripted end-to-end checks (22 known-answer chat questions). |

---

## How it works

### Upload → index

```mermaid
flowchart LR
    U[User uploads file] --> W[Next.js API<br/>/api/documents/upload]
    W -->|store file + row 'uploaded'| DB[(PostgreSQL)]
    DB -->|claim job<br/>FOR UPDATE SKIP LOCKED| ING[Ingestion worker<br/>parse PDF / Office / CSV / JSON / OCR]
    ING -->|preview| DB
    ING -->|raw text| INT[Intelligence service<br/>/documents/index]
    INT --> CH[Chunk + embed<br/>MiniLM, title-aware]
    INT --> KG[Extract entities<br/>schema patterns + terms + embeddings]
    CH --> DB
    KG -->|edges per document| DB
```

1. **Upload:** the web app stores the file and queues a `documents` row.
2. **Parse:** the ingestion worker claims the job, picks a parser by file type, extracts text and a preview, and records failures on the document so the upload page can show them.
3. **Index:** the intelligence service splits text into chunks, merging small ones up to 1,500 characters. It embeds each chunk together with its document title and stores the vectors.
4. **Graph:** spaCy parses the document once. That one parse supplies named entities, noun phrases and lemmas. Entities are then found in four layers:
   - schema regex patterns (asset codes, measurements, regulations)
   - schema term lists, plurals included ("conductivity alarms" is the term "conductivity alarm")
   - spaCy NER for people and places, filtered to proper nouns, with one type per name decided by votes
   - embedding-typed noun phrases, plus unknown codes typed by the words before them ("loan LN-2041")

   Entities in the same sentence or record are linked by the schema's relationship rules. Near-duplicate names merge into existing nodes by cosine similarity. The document itself becomes a node that `MENTIONS` its most-cited entities, so every upload adds its own node and relations.

### Ask → answer

```mermaid
flowchart LR
    Q[Question] --> P[/api/chat/]
    P --> E[Embed question]
    P --> L[Link question to graph nodes<br/>exact or by embedding]
    L --> B[Boost passages that name<br/>linked entities]
    E --> S[Vector search<br/>tenant's in-memory index]
    B --> S
    S --> C[Top passages + catalog<br/>for overview questions]
    C --> LLM[LLM: Ollama / OpenAI-compatible]
    LLM --> A[Streamed answer with<br/>citations and sources]
```

- **Search:** each tenant's vectors are cached in memory and reloaded only when its data changes.
- **Graph steering:** the knowledge graph steers retrieval and never adds passages of its own, so every citation points at real text.
- **Question types:**
  - Greetings skip search.
  - Overview questions ("what topics…?") get a document catalog.
  - Short follow-ups are searched together with the previous question.
  - Weak matches are flagged instead of guessed.

### The knowledge graph

```mermaid
flowchart TB
    S[graph_schema.json<br/>types · patterns · terms · examples · rules] --> X
    T[tenants.settings.graph_schema<br/>per-company extensions] --> X
    X[Schema for this tenant] --> EX[Extractor]
    M[MiniLM embeddings<br/>cached, batched] --> EX
    EX --> R[Relationship inference<br/>within a sentence or record]
    R --> G[(graph_nodes / graph_edges<br/>one edge set per document)]
    G --> V[Knowledge Graph view]
    G --> F[Maintenance Intel<br/>issues and actions per asset]
    G --> Q[Chat retrieval boost]
```

- **Roles:** each type has a role (`subject`, `issue`, `action`, `value` and so on). Views and graph walks use these roles instead of type names.
- **Per-document edges:** edges are stored per source document, so re-indexing or deleting a document updates the graph exactly.
- **Rebuild:** after changing a schema, run `python -m src.knowledge_graph.rebuild --tenant <slug>`. It parses all documents once in a batch (`nlp.pipe`) and decides each name's type by votes across the whole collection:
  - how spaCy labelled each mention
  - context cues such as "Owner:" or "Reported by"
  - names it is listed with (coordination in the parse)
  - other names with the same surname

  It then rebuilds the graph from scratch from those parses.
- **Layout:** every node keeps the room its circle and label need, and the view zooms to fit instead of squeezing nodes together. Document nodes can be hidden with one toggle.
- **Demo size:** the demo's 72 documents give 166 nodes and 342 edges.

---

## Architecture

![VEDA architecture: indexing path, tenant-scoped store, answering path](Report/veda_architecture.png)

VEDA has two paths that share one tenant-scoped PostgreSQL store and one sentence encoder:

- The **indexing path** runs once per upload.
- The **answering path** runs once per question.

The knowledge graph changes the *ranking* of passages, never the *context*: only real document text reaches the LLM, so every citation can be checked.

### Components

```mermaid
flowchart LR
    subgraph Browser
        UI[Web UI<br/>chat · uploads · graph · dashboards]
    end
    subgraph Web["apps/web — Next.js 15 (:3000)"]
        API[API routes<br/>auth · chat · documents · graph<br/>alerts · maintenance · compliance]
        LLMC[LLM client<br/>lib/llm.ts]
    end
    subgraph Ingestion["services/ingestion — Python (:8001)"]
        WK[Local worker<br/>claims jobs, parses files, OCR, previews]
    end
    subgraph Intelligence["services/intelligence — FastAPI (:8002)"]
        IDX["/documents/index<br/>chunk · embed · extract · graph"]
        QRY["/query/prepare<br/>graph link · dense search · RRF"]
        GR["/graph/overview · /graph/findings"]
        ENC[(MiniLM encoder<br/>+ spaCy en_core_web_sm)]
    end
    DB[(PostgreSQL<br/>tenant-scoped)]
    OL[Ollama llama3<br/>or OpenAI-compatible API]

    UI --> API
    API -->|store file, queue row| DB
    WK -->|claim: FOR UPDATE SKIP LOCKED| DB
    WK -->|parsed text| IDX
    IDX --> DB
    API -->|question| QRY
    QRY --> DB
    API --> GR
    API --> LLMC --> OL
    IDX -.-> ENC
    QRY -.-> ENC
```

| Component | Technology | Responsibility |
|:--|:--|:--|
| Web app and API | Next.js 15, TypeScript | Upload, chat (streamed NDJSON), graph view, dashboards, signed HMAC sessions, rate limits |
| Ingestion service | Python: PyMuPDF, pdfplumber, EasyOCR, python-docx, python-pptx, openpyxl | Parse 16 file extensions to text, OCR images, build previews, track status |
| Intelligence service | Python: FastAPI, sentence-transformers, spaCy, NumPy | Chunking, embeddings, entity and relation extraction, knowledge graph, retrieval |
| Store | PostgreSQL 16 (+ pgvector, Apache AGE in full mode) | Documents, chunks, vectors, graph; every query filtered by `tenant_id` |
| LLM | Ollama (llama3 8B) or any OpenAI-compatible API | Answer generation, streamed token by token |
| Keyword search (full mode) | OpenSearch | BM25 retrieval, fused with dense results by Reciprocal Rank Fusion |
| Queue and files (full mode) | Kafka + MinIO | Event-driven ingestion, object storage |

The NLP inside the intelligence service is described file by file in [NLP_README.md](NLP_README.md).

### Data model

| Table | Holds |
|:--|:--|
| `tenants`, `users` | One row per company (its agent) and its login; `tenants.settings.graph_schema` holds the company's schema extension |
| `documents`, `document_files` | One row per upload with its status (`uploaded` → `processing` → `indexed` / `failed`); file bytes in hosted mode |
| `document_chunks` | Passages (≤1,500 characters) with their 384-d embedding |
| `graph_nodes`, `graph_edges` | Typed entities, and relations tagged with the document they came from |
| `document_previews` | Rendered previews of Office files |
| `alerts`, `maintenance_orders`, `compliance_rules` | Dashboard records |
| `compute_node`, `audit_logs` | Hosted-mode compute node registration; audit table (not yet used) |

### Tenant isolation

A tenant *is* its agent: retrieval covers everything that tenant uploaded and nothing else.

- Every SQL query filters on the session's `tenant_id`.
- The internal intelligence API requires an internal key and a UUID tenant id.
- Cypher queries (full mode) are parameterised and tenant-keyed.
- In-memory search indexes and graph caches are keyed per tenant.

### Deployment modes

| Concern | Local mode (default) | Full mode | Hosted mode ([DEPLOY.md](DEPLOY.md)) |
|:--|:--|:--|:--|
| Web app | `next dev` on your PC | Docker | Vercel |
| Database | Local PostgreSQL | PostgreSQL in Docker | Supabase |
| Queue | PostgreSQL row claiming | Apache Kafka | PostgreSQL row claiming |
| File storage | `.data/uploads` | MinIO | `document_files` table |
| Vectors | `REAL[]` + in-memory NumPy index | pgvector (HNSW) | `REAL[]` + in-memory index |
| Graph | `graph_nodes` / `graph_edges` | Apache AGE | `graph_nodes` / `graph_edges` |
| Keyword search | — | OpenSearch | — |
| LLM and Python services | Your PC | Docker | Your PC, reached through a Cloudflare tunnel (`npm run node`) |

The retrieval logic is the same in every mode.

### Repository layout

```
apps/web/                  Next.js 15 (App Router, TypeScript)
  src/app/                 pages: landing, login/register, dashboard, chat, upload
  src/app/api/             auth, chat, documents, graph, maintenance, alerts, compliance
  src/components/          KnowledgeGraph, DocumentFindings, DocumentViewer, ...
  src/lib/                 db (tenant-scoped SQL), llm, chatPrompt, intelligence client
nlp_sts/                   all NLP code, one file per step: step01_text_extraction … step10_context_building,
                           graph_schema.json, run_pipeline.py (runs the steps one by one on a sample)
services/ingestion/        Python: local worker, Kafka worker, previews (parsing = nlp_sts step 1)
services/intelligence/     Python FastAPI (NLP = nlp_sts steps 2–10)
  src/knowledge_graph/     local_graph, rebuild, AGE manager, Kafka worker
  src/rag/                 pipeline (retrieval orchestration), local_store (in-memory vector index)
infrastructure/docker/     PostgreSQL schema (full + local mode), Prometheus
scripts/                   dev.js (starts everything), demo/ (dataset + checks)
demo-data/                 fictional demo company "Nephrova" (72 documents, 8 formats)
scripts/enron/             real-data tenant: SEC filings, policies, CMU email corpus
scripts/eval/              retrieval evaluation (Hit@k, MRR, latency, graph ablation)
Report/                    architecture diagrams and technical notes for the paper
```

---

## Getting started (local mode)

**Prerequisites:** Node 20+, Python 3.12+, PostgreSQL 16+, and [Ollama](https://ollama.com) for chat.

```bash
# 1. Configuration
cp .env.example .env            # set DATABASE_URL, SESSION_SECRET, INTERNAL_API_KEY, LLM_*

# 2. Database
psql "$DATABASE_URL" -f infrastructure/docker/postgres/init_local.sql
for f in infrastructure/docker/postgres/local/*.sql; do psql "$DATABASE_URL" -f "$f"; done   # 002–005: passages, graph, previews, alerts and work orders

# 3. Python services (one virtualenv each)
cd services/ingestion    && python -m venv .venv && .venv/Scripts/pip install -e .   # bin/ on Linux/macOS
cd ../intelligence       && python -m venv .venv && .venv/Scripts/pip install -e .

# 4. A local model
ollama pull llama3

# 5. Run everything (web on :3000, intelligence on :8002, ingestion worker)
npm run dev
```

`scripts/dev.js` installs the frontend dependencies, starts both Python services with local-mode settings, and preloads the Ollama model.

### Free hosting

To put it online for free, see [DEPLOY.md](DEPLOY.md): the web app goes on Vercel and the data on Supabase. Ollama and the Python services stay on your PC, which opens a Cloudflare tunnel only while someone is using the site (`npm run node`).

### Demo tenant

`demo-data/` contains a fictional dialysis-care company with 72 documents uploaded one a day (each one is described in [document.md](document.md)): policies, logs, reports, an operations manual, a risk register and a board pack. To load and check it:

```bash
services/ingestion/.venv/Scripts/python.exe scripts/demo/seed_tenant.py      # upload + backdate (idempotent)
services/ingestion/.venv/Scripts/python.exe scripts/demo/check_chat.py       # 22 known-answer questions
services/ingestion/.venv/Scripts/python.exe scripts/demo/export_graph.py     # graph + upload-date checks
```

The login is in `scripts/demo/company.py`. It is a local demo account only.

---

## Customising the graph for a company

Add vocabulary as data, not code. Store it in `tenants.settings.graph_schema`. Types merge with the base schema, lists are appended, and rules are added:

```json
{
  "types": {
    "LOAN": { "label": "Loan", "role": "subject", "identifier": true,
              "examples": ["loan account", "credit facility"] },
    "FAILURE_MODE": { "terms": ["npa classification", "covenant breach"] }
  },
  "relationships": [
    { "source": "LOAN", "target": "FAILURE_MODE", "type": "HAS_ISSUE", "inverse": "ISSUE_OF" }
  ]
}
```

Thresholds live in the schema's `semantic` block:

- `min_similarity`, `min_margin`: how confident embedding typing must be
- `merge_similarity`: when near-duplicate names become one node
- `query_link_similarity`: when a question links to a graph node

To replace the base schema for a whole deployment, set `VEDA_GRAPH_SCHEMA_FILE`.

---

## Testing

```bash
cd apps/web && npx jest                                                # 222 tests
cd services/intelligence && .venv/Scripts/python -m pytest tests -q   # 357 tests
cd services/ingestion && .venv/Scripts/python -m pytest tests -q      # 90 tests
```

CI (`.github/workflows/ci.yml`) runs lint, type checks, tests and the build for the web app and both services.

---

## Known limitations

Before using it with real company or patient data:

- **One login per company.** Registration creates a single admin; there is no way to invite staff, assign roles or reset a forgotten password yet.
- **Tenant isolation is enforced in code, not by the database.** Every query filters on the session's tenant (reviewed route by route), but PostgreSQL row-level security is not effective: the app connects as the table owner in Docker mode, and RLS is off in local mode. Enabling it needs a separate role for the background workers.
- **Sessions are not revocable.** A session cookie stays valid for up to 24 hours, even after logout elsewhere or deactivation.
- **No audit trail.** Who viewed or deleted what is not recorded (`audit_logs` is unused).
- **One process holds the caches.** The search index, the login rate limits and the schema cache are in memory; with several app or service instances, they need a shared store such as Redis.
- **A file that hangs the parser stalls the queue.** Crashes are retried at most 3 times; a parse that never finishes needs a worker restart.

- **NLP and embedding typing are statistical.** Most entities are typed well, but some slip through, for example a heading read as a person's name. Each company tunes this with its schema terms, examples, NER cues and thresholds.
- **Local vector search is linear per tenant.** That is fast for thousands of passages; large tenants should use full mode (pgvector HNSW).
- **Work orders are not extracted.** The work-orders list on the Maintenance page is only filled through its API. The findings above it come from documents.
- **Full mode is less exercised.** Local mode is what the demo and most tests exercise; the Kafka, AGE and OpenSearch path has unit tests but less end-to-end use.

---

## License

Apache 2.0, see [LICENSE](LICENSE).
