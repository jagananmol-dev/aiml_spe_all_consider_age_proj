# Compliance Score and the Enron Dataset

This file covers two things:

1. how the dashboard's **Compliance Score** is calculated, and how far it can be trusted;
2. the second demo tenant, **Enron Corp.**, built from real public data. It sits next to the synthetic tenant described in [document.md](document.md).

Figures for Enron are from 16 October 2026, while its ingestion was still running. Section 2.8 shows how to refresh them.

---

## Part 1 — The Compliance Score

### 1.1 How it is calculated

The score is computed in the browser, in `apps/web/src/app/dashboard/page.tsx` (the "COMPLIANCE SCORE" tile):

```ts
complianceRules.length > 0
  ? `${Math.round((complianceRules.filter((r) => r.complianceStatus === "compliant").length
                   / complianceRules.length) * 100)}%`
  : "100%"
```

So the score is:

```
score = round( 100 × rules with status "compliant" / all rules of the tenant )
score = "100%"  when the tenant has no rules at all
```

The rules come from `GET /api/compliance/status` (`apps/web/src/app/api/compliance/status/route.ts`). That route returns every row of the `compliance_rules` table for the session's tenant. Each row has:

| Column | Meaning |
|:--|:--|
| `regulation_name`, `regulation_version`, `section_reference` | Which law or standard, for example "NABH · Dialysis water management" |
| `requirement_text`, `requirement_type` | The requirement, and `mandatory` or `recommended` |
| `compliance_status` | `compliant`, `non_compliant`, `gaps` or `not_applicable` (local schema). The Docker schema has no check constraint and defaults to `unknown`. |
| `evidence_document_ids` | UUIDs of documents said to prove the status |
| `notes`, `last_reviewed_at` | Free text, and when someone last looked |

**Where the rows come from.** Nothing in the platform creates rules from uploaded documents. They exist only if:

- a script seeds them (`scripts/demo/seed_tenant.py` writes 6 for Nephrova), or
- someone calls `POST /api/compliance/status`, which can only *change* the status and notes of an existing rule.

There is no API to create a rule. The dashboard's Compliance view (with a "Compliant / Has Gaps" toggle) exists in the code, but no menu item opens it.

### 1.2 What the two tenants show today

| Tenant | Rules | Compliant | Other | Score shown |
|:--|:--:|:--:|:--|:--:|
| Nephrova (synthetic) | 6 | 5 | 1 `gaps` (NABH bio-medical waste segregation) | **83%** |
| Enron (real data) | 0 | 0 | — | **100%** |

The Enron line shows the core problem. A company that restated four years of earnings and filed for bankruptcy shows a perfect score, only because nobody entered any rules.

### 1.3 Is it accurate?

**The arithmetic is correct. The number is not an accurate measure of compliance.** It is a checklist ratio, and every input to it is typed in by hand.

| # | Problem | Effect |
|:--|:--|:--|
| 1 | **No rules shows 100%.** | A new or unconfigured tenant looks fully compliant. It should say "no rules defined" instead. |
| 2 | **Not computed from documents.** Statuses are entered by hand. The uploaded documents, graph and chat are never consulted. | The score can contradict the company's own documents. Nephrova's "ISO 23500 water quality: compliant" stays green even if a new lab report shows a failed test. |
| 3 | **Evidence is not checked.** `evidence_document_ids` is a plain UUID array with no foreign key. | A rule can claim evidence from a deleted or unrelated document and still count as compliant. |
| 4 | **`not_applicable` counts against the score.** Only `compliant` is counted on top, but every rule is in the denominator. | Marking a rule "not applicable" *lowers* the score. N/A rules should be left out. |
| 5 | **All rules weigh the same.** | A missing waste-segregation chart counts as much as a failed water-safety limit. `mandatory` and `recommended` are treated alike. |
| 6 | **Partial compliance is all-or-nothing.** `gaps` and `non_compliant` both count as zero. | One minor non-conformity and a total failure look the same. |
| 7 | **Not time-aware.** `last_reviewed_at` and `next_assessment_due` (Docker schema) are ignored. | A rule reviewed two years ago counts the same as one reviewed yesterday. |
| 8 | **`unknown` counts as failing in Docker mode.** | The same data gives a different score in local and Docker mode. |
| 9 | **Rounding hides small sets.** | With 6 rules, one change moves the score by 17 points. The tile doesn't show the count ("5 of 6"). |

The tile's caption, "Compliance checklists", is the honest description. The score answers "what share of the checklist did someone mark compliant?" It does not answer "is the company compliant?"

### 1.4 What a trustworthy score would need

In order of value:

1. **Show "No rules defined"** instead of 100%, and always show "5 of 6 rules" next to the percentage.
2. **Exclude `not_applicable`** from the denominator. Give `gaps` partial credit, or show it separately.
3. **Weight by requirement type and severity**, for example mandatory = 3 and recommended = 1.
4. **Check evidence.** A rule counts as compliant only if at least one evidence document still exists, belongs to the tenant, and is newer than the review period.
5. **Flag contradicting documents.** For each rule, search the tenant's documents for recent passages about the requirement (the same retrieval the chatbot uses). Mark the rule "needs review" when a newer document mentions an issue (`FAILURE_MODE` in the graph) about it. This keeps the human in charge while letting the documents raise flags.
6. **Expire stale reviews.** A rule not reviewed within its period drops to "needs review".
7. **Let admins create and edit rules** (an API plus a reachable Compliance view), since today rules can only come from a seed script.

---

## Part 2 — The Enron Dataset (real public data)

### 2.1 Why a second, real dataset

The Nephrova tenant is synthetic: one generator writes every document, so the facts agree and the ground truth is known. That is ideal for checking correctness, but it is clean in ways real data never is. A second tenant built from a **real company's real documents** tests what synthetic data can't:

- **Scale.** Hundreds of thousands of emails instead of 72 files.
- **Noise.** Duplicates, forwarded threads, signatures, disclaimers, typos, broken encodings and stray dates.
- **Real people and organisations.** These are names the system has never seen, in formats nobody designed for it.
- **A domain the base schema doesn't cover.** Energy trading and corporate finance, not industrial maintenance or healthcare.

**Enron is the only large, public corpus of a real company's internal documents.** The US Federal Energy Regulatory Commission released its email during the Enron investigation. Carnegie Mellon University cleaned and published it, and it has been a standard research dataset since. Enron's SEC filings from the same years are public records on EDGAR. Together they give both the *internal* view (email) and the *official* view (filings) of one company over the same period. That period includes the events that led to its collapse.

Other options were looked at. EnterpriseRAG-Bench (Onyx) has 500k+ enterprise documents, but they are synthetic, so it wouldn't serve as the realistic tenant.

### 2.2 The company

| | |
|:--|:--|
| **Name** | Enron Corp., Houston, Texas |
| **Business** | Natural gas pipelines, wholesale energy trading (EnronOnline), retail energy services, broadband, water (Azurix), international power plants (Dabhol in India, Elektro in Brazil) |
| **Scale** | Reported revenue of **$100,789 million** in 2000 (10-K filed 2 April 2001), and net income of $979 million |
| **Collapse** | CEO Jeff Skilling resigned in August 2001. In October 2001 a $1.2 billion cut to shareholders' equity was announced. On 8 November 2001 four years of results were restated (2000 net income restated from $979M to $847M; Chewco and JEDI consolidated). Dynegy agreed to acquire Enron at 0.2685 Dynegy shares per Enron share, then pulled out, and Enron filed for Chapter 11 on 2 December 2001. |
| **Key structures** | Off-balance-sheet partnerships run by CFO Andrew Fastow: LJM1, LJM2, Chewco, JEDI, and the Raptor vehicles (Talon, Timberwolf, Bobcat, Porcupine) |
| **Demo login** | slug `enron`, email `demo@enron-corp.example`, password `Enron@Demo#2001` (local demo account only) |

### 2.3 Sources

| Source | What | Size | Where it comes from |
|:--|:--|:--|:--|
| **CMU Enron Email Dataset** (May 2015 release) | Mailboxes of 150 Enron employees, mostly senior management, traders and lawyers. Attachments are not included. | 443 MB compressed, 2.4 GB on disk, **517,401** message files | `https://www.cs.cmu.edu/~enron/` |
| **SEC EDGAR filings**, CIK 1024401 | **20 filings** from 2000–2002: two 10-K annual reports, six 10-Q quarterly reports, two DEF 14A proxy statements, ten 8-K current reports | 4 MB of text | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1024401` |

The most important filings:

- **10-K filed 2001-04-02**: annual report for 2000, the last before the collapse.
- **8-K filed 2001-11-08**: the restatement of 1997–2000 results.
- **8-K filings of 2001-11-13 and 2001-11-14**: the Dynegy merger agreement and the ChevronTexaco investment.
- **10-Q filed 2001-11-19**: Q3 2001, with the $1.2 billion equity reduction and a going-concern warning.
- **8-K filed 2002-02-07**: contains the **Powers Report**, the board's Special Investigative Committee report, chaired by William Powers, Jr.

**Licence and privacy.** EDGAR filings are public records. CMU publishes the email corpus without a formal licence and asks users to respect the privacy of the people involved. (A derivative release on EnronData.org is under CC BY 3.0 US.) The raw data is therefore **not committed to the repository**: it lives in `.data/` (gitignored), and the scripts download it again. The corpus contains real names and some personal messages. It is used here as the research community uses it, for a local demo only.

### 2.4 How the data was prepared

All scripts are in `scripts/enron/` and run with the ingestion virtualenv's Python.

**SEC filings (`fetch_sec.py`).** Each filing's full submission is downloaded from EDGAR. The main document and its press-release exhibits (`EX-99*`) are kept. Financial data schedules and graphics are dropped, and HTML and SGML page tags are reduced to plain text. Each file starts with the form, filing date and source URL.

**Emails (`build_emails.py`):**

1. **Read all 517,401 files.** The corpus names messages `1.`, `2.` … with a trailing dot, which Windows path functions silently remove. Files are read through extended-length `\\?\` paths, or Python sees no files at all.
2. **Keep January 1999 to June 2002.** The corpus has stray dates from 1979 and 2044.
3. **Remove duplicates.** The same message appears in several folders and several people's mailboxes. A message is a duplicate when sender, timestamp, subject and the start of the body match. Sent folders are read first and catch-all folders (`all_documents`, `discussion_threads`, `deleted_items`, `notes_inbox`) last. So a message is kept from its proper folder, and catch-all folders only add what exists nowhere else. That catch-all pass recovered about 69,000 emails that a stricter filter would have dropped.
4. **Clean bodies.** Lines quoted with `>` are removed, encoding artefacts are fixed, and each body is capped at 3,000 characters (long bodies are mostly forwarded chains).
5. **Name each mailbox's owner.** The owner comes from the `X-Folder` header ("Kenneth_Lay_Dec2000", "Dasovich, Jeff (Non-Privileged)"), not from who sent the mail. In Ken Lay's and Jeff Skilling's sent folders, most mail was written by their assistants.
6. **Bundle into documents.** There is **one document per mailbox per month**, split into parts above 250,000 characters (the graph's NLP reads the first 200,000 characters of a document). Each email starts with a `=== Email` line and its Date, From, To, Cc and Subject. The chunker splits on that line, so passages and citations still point at individual emails. Uploading each email as its own document would have meant 254,000 document rows, which the single local worker can't process in reasonable time.

| Result | Value |
|:--|:--|
| Unique emails, 1999-01 to 2002-06 | **254,402** |
| Email documents | **3,064** (131 from 1999, 887 from 2000, 1,755 from 2001, 291 from 2002) |
| Email text | 314 MB |
| Plus SEC filings | 20 documents |
| **Total documents** | **3,084** |
| Mailboxes with the most unique mail | Vince Kaminski (research), Jeff Dasovich (government affairs), Kay Mann (legal), Sara Shackleton (legal), Tana Jones, Chris Germany, Steven Kean, Louise Kitchen |

**Upload dates.** As with Nephrova, documents are dated as if uploaded when they were written: filings on their filing date, and email bundles on the date of the month's last email. `seed_tenant.py` sets this after indexing.

### 2.5 A graph schema for an energy-trading company (data, not code)

The base `graph_schema.json` knows industrial assets and healthcare. Enron's vocabulary is added **per tenant**: `scripts/enron/graph_schema_enron.json` is stored in `tenants.settings.graph_schema` before anything is indexed. No code was changed, which is the platform's design goal.

| Addition | Examples |
|:--|:--|
| New type **Partnership / SPE** (subject) | LJM, LJM1, LJM2, Chewco, JEDI, Raptor I–IV, Talon, Timberwolf, Bobcat, Porcupine, Whitewing, Osprey, Marlin, Braveheart |
| New type **Business unit** (subject) | Enron North America, Enron Energy Services, Enron Broadband Services, EnronOnline, Azurix, Portland General Electric, Dabhol, Northern Natural Gas, Transwestern Pipeline, Elektro, … |
| More **issue** terms | restatement, write-down, impairment, credit downgrade, liquidity crisis, bankruptcy, Chapter 11, margin call, rolling blackouts, California energy crisis, conflict of interest, class action, layoffs |
| More **action** terms | hedging, merger, acquisition, divestiture, asset sale, equity issuance, internal investigation, mark-to-market accounting, price cap |
| More **regulators and rules** | FERC, SEC, CFTC, PUHCA, CPUC, GAAP, FAS 140, FAS 125 |
| New relationships | SPE → MANAGED_BY → person, SPE → HAS_ISSUE → issue, SPE ↔ TRANSACTED_WITH ↔ business unit, business unit → LED_BY → person, business unit → GOVERNED_BY → regulation, and others |
| Name cues for email headers | "cc", "regards", "thanks", "dear", "sent by" vote for PERSON |

A tenant's `nlp` block *replaces* the base block's keys rather than extending them (a shallow merge). So the extension repeats the base `type_cues` and adds to them.

### 2.6 Ingestion and the two performance fixes it needed

Documents go through the normal product path: `/api/documents/upload`, then the local worker, then the intelligence service's `/documents/index`. There, each document is chunked, embedded with its title, and its graph edges are extracted.

At this scale two hidden performance problems showed up and were fixed in `services/intelligence/src/entity_extraction/`:

| Problem | Cause | Before | After |
|:--|:--|:--|:--|
| Entity extraction was slow on long documents | spaCy's `Doc.text` rebuilds the whole text on every call, and it was called once per named entity and once per noun phrase. That costs document length × number of entities. | 27 s for the 2000 10-K | **0.9 s**, identical output (1,183 entities) |
| Merging new names into the graph got slower as the graph grew | Each document's names were clustered together with *every existing node name*, which is quadratic in the graph's size, on every document | 2.1 s at 2,000 nodes, about 50 s at 10,000, about 8 min at 30,000 per document | **About 0.3 s** at any size: one matrix product against the existing nodes, and only the document's own names clustered |

The phrase-embedding cache was also raised from 50,000 to 200,000 entries, so a large tenant's node names stay cached. All 361 intelligence tests pass. Rebuilding Nephrova's graph with the new code gives the same result as before: 342 edges and 166 nodes.

**Throughput** on this laptop (i5-13450HX, 16 GB, CPU-only PyTorch) is about 14–15 passages per second. Spread over the corpus, that is about **4 hours** of indexing time for the full tenant. spaCy parsing and embedding are the main costs, and both are linear.

**Status on 16 Oct 2026:** 500 of 3,084 documents indexed (28,235 passages, the SEC filings plus email through mid-2000). Ingestion stopped twice: once when the laptop slept, and once when the system ran short of memory with the web app, Ollama, Chrome and the services all running. No data was lost; queued documents resume where they stopped.

### 2.7 First results

**Chatbot, known-answer questions** (`scripts/enron/check_chat.py`). Each expected answer was confirmed in the source text first. This run was at partial ingestion, with all filings but no email after mid-2000 yet:

| Question | Result | Answer given |
|:--|:--:|:--|
| Partnerships consolidated in the Nov 2001 restatement | ✅ | Chewco and JEDI, with the LJM1 subsidiary |
| Who chaired the Special Investigative Committee | ✅ | William Powers, Jr. |
| Enron officer behind the LJM partnerships | ✅ | Andrew S. Fastow, managing member of the LJM general partners |
| Reduction of shareholders' equity in Q3 2001 | ✅ | $1.2 billion |
| Exchange ratio of the Dynegy merger | ✅ | 0.2685 Dynegy shares per Enron share |
| ChevronTexaco's immediate investment in Dynegy | ✅ | $1.5 billion of a $2.5 billion commitment |
| What the anonymous August 2001 letter to Ken Lay warned about | ✅ | Aggressive accounting, especially the Raptor transactions |
| Total revenues in 2000 | ❌ | Said it couldn't find them. The figure ($100,789 million) is in a table in the 10-K that retrieval didn't rank high enough. |
| 2000 net income, reported vs restated | ❌ | Didn't give both figures ($979M and $847M, from a table in the restatement 8-K) |
| Who took over as CEO when Skilling left | ❌ | **Wrong:** named Stephen Cooper, who was appointed in January 2002. The emails saying Ken Lay resumed as CEO were not indexed yet. |
| Skilling's public reason for resigning | ❌ | Not found (those August 2001 emails were not indexed yet) |

**7 of 11** at partial ingestion. The failures show real weaknesses that synthetic data hid:

- **Financial tables are hard to retrieve.** Wide, number-heavy tables in filings embed poorly, so a question about "total revenues" doesn't match the table row that holds the number.
- **The model can attribute a fact to the wrong time.** Asked about August 2001, it took a January 2002 fact from a document it did have, instead of saying the answer wasn't there. This is a faithfulness problem the prompt rules didn't prevent.

**Search latency.** While ingestion runs, a search over about 18,000 passages took 0.6–11 seconds, against 6–26 ms on Nephrova. The tenant's in-memory index is rebuilt whenever the tenant's data has changed since the last search, and the worker writes new passages before nearly every question. Once ingestion stops, the index is built once and stays cached. Latency at full size (about 200,000 passages) still needs to be measured.

**Knowledge graph** (at 500 documents: 5,272 nodes, 14,566 edges):

| Works well | Gets wrong |
|:--|:--|
| SPEs are found cleanly: LJM2, Raptor, Marlin, LJM, Whitewing, Chewco, JEDI, Talon, Osprey | **The base schema's industrial patterns misfire.** "crude", "Cruise", "Cruz", "Crum" and "Crump" become assets through the refinery-unit pattern `CRU…`, and "v74", "k12" and "e204" through valve and exchanger patterns. A tenant can add to the base schema but cannot switch off its patterns. |
| Business units: EnronOnline (the most connected node), Enron North America, Azurix, Enron Europe, Elektro, Transwestern Pipeline | **Embedding typing over-reaches.** "Golf Delays", "Credit Approvals" and "Regulatory Committee" are typed as issues, and "natural gas", "power plants" and "ENRON EMPLOYEES" as business units. |
| People: Mark Taylor, Sara Shackleton, Vince Kaminski, Louise Kitchen, Richard Shapiro … | **Name typing errors.** "Molly Johnson" and "Casas" become places, and "PRC" (Enron's Performance Review Committee) becomes the People's Republic of China. |
| Places: Houston, London, Texas, Brazil, California, Argentina | **Healthcare types leak in.** "water injection" was typed as a medication, because base types can't be removed per tenant. |
| Issues: bankruptcy, restatement, impairment, Chapter 11, conflict of interest, price spikes | **Plurals of single-word terms:** "wears" matches the term "wear". |

### 2.8 Synthetic versus real: what each tenant is for

| | Nephrova (synthetic) | Enron (real) |
|:--|:--|:--|
| Documents | 72 | 3,084 (254,402 emails + 20 filings) |
| Text | ≈ 1 MB | ≈ 318 MB |
| Formats | 8 (PDF, Word, PowerPoint, Excel, CSV, JSON, Markdown, text) | Plain text only (email bundles and filings) |
| Ground truth | Complete: every fact comes from one generator | Partial: checked by hand against the sources |
| Noise | None by design | Duplicates, threads, signatures, encodings, wrong dates |
| Domain | Healthcare (dialysis) | Energy trading and corporate finance |
| Best for | Correctness, policy questions, demos, regression checks | Scale, robustness, realistic retrieval and graph quality |
| Compliance rules | 6 seeded (score 83%) | None (score shows a misleading 100%, see Part 1) |

To rebuild or refresh the Enron tenant (stack running, ingestion virtualenv Python):

```bash
python scripts/enron/fetch_sec.py        # 20 filings → .data/enron/sec
python scripts/enron/build_emails.py     # needs .data/enron-raw/maildir (CMU tarball)
python scripts/enron/seed_tenant.py      # register, store schema, upload, wait, backdate
python scripts/enron/check_chat.py       # 11 known-answer questions
```

### 2.9 Limitations and next steps

- **Finish ingestion and re-measure:** the chat check, search latency at about 200k passages, and graph size.
- **Base patterns need a per-tenant off switch:** let `tenants.settings.graph_schema` disable types or patterns (for example `"EQUIPMENT_TAG": {"enabled": false}`).
- **Table-aware retrieval for filings:** keep a table's header row with every chunk of the table, or add keyword search (BM25) next to dense search in local mode.
- **Temporal grounding:** pass each passage's date to the model and ask it to check that the date fits the question.
- **The Data Uploads list stops at 500 rows:** `GET /api/documents/upload` has `LIMIT 500`, so Enron's 3,084 documents need paging in the API and the page.
- **Transient outages fail documents:** the local worker marks a document failed when the intelligence service is briefly unreachable, for example during a restart. It should wait and retry.
- **No compliance rules:** to compare the score across tenants, Enron would need real rules (for example SEC and FERC requirements). Those exist only once rules can be created and checked against documents, as described in Part 1.
