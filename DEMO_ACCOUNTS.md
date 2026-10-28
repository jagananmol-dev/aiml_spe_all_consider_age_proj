# VEDA AI — Demo Accounts

VEDA has two demo companies (tenants), each with its own login, documents, knowledge graph and chatbot:

| | Synthetic data | Real data |
|---|---|---|
| **Company** | Nephrova Renal Care Pvt. Ltd. (fictional) | Enron Corp. (real, 1999–2002) |
| **Industry** | Healthcare: outpatient dialysis | Energy trading and utilities |
| **Workspace (slug)** | `nephrova` | `enron` |
| **Email** | `demo@nephrova.example` | `demo@enron-corp.example` |
| **Password** | `Nephrova@Demo#2026` | `Enron@Demo#2001` |
| **Documents** | 72 | 3,123 (SEC filings, policies, email bundles) |
| **Seed script** | `scripts/demo/seed_tenant.py` | `scripts/enron/seed_tenant.py` |

**How to log in:** start the stack (`pnpm dev`), open <http://localhost:3000/login>, and enter the workspace slug, email and password.

> These are demo accounts for a local install. Change the passwords on any deployment that is reachable from the internet.

---

## 1. Nephrova Renal Care (synthetic data)

### What the company does

Nephrova Renal Care Pvt. Ltd. is a **fictional** healthcare company with one niche: **outpatient haemodialysis for people with chronic kidney disease**. It was founded in 2018 and has its head office on Baner Road, Pune. It runs three dialysis centres:

| Centre | Area | Dialysis machines | Active patients | Centre manager |
|---|---|---|---|---|
| Nephrova Kothrud (KTH) | Kothrud, Pune | 12 (HD-K01…K12) | 96 | Amit Gokhale |
| Nephrova Hadapsar (HDP) | Hadapsar, Pune | 10 (HD-H01…H10) | 80 | Farah Khan |
| Nephrova Pimpri (PMP) | Pimpri, Pune | 8 (HD-P01…P08) | 62 | Suresh Nair |

Leadership: Ritu Malhotra (CEO), Dr. Sameer Deshpande (Medical Director), Anjali Thomas (Chief Nursing Officer), Nikhil Joshi (Biomedical Engineering Lead), Kiran Bhosale (Quality Manager / NABH coordinator), Vivek Jain (Finance Head) and Snehal Patil (HR Manager).

### The data

Every document is **generated**. The company, its people and its patients are all fictional, and patients appear only as de-identified IDs. All names, dates and figures come from one source file, `scripts/demo/company.py`, so the documents agree with each other.

- **72 documents, one or more per day from 2026-07-30 to 2026-10-09**, in 8 formats (no images): 12 PDF, 12 Word, 11 Markdown, 10 text, 9 Excel, 6 CSV, 6 JSON, 6 PowerPoint.
- **Policies:** 6 HR policies (code of conduct, recruitment, compensation, appraisal, POSH, leave), 5 finance policies (delegation of authority, billing, refunds, procurement, travel rates), plus clinical SOPs (infection control, hand hygiene, water treatment, biomedical waste, catheter care).
- **Day-to-day operations:** shift logs, machine alarm logs, biomedical engineering job reports, water lab results, disinfection records, staff rosters, session census and stock sheets.
- **Connected storylines that run across many documents:**
  - conductivity alarms on machine **HD-K04**, through the service request, the job report and the repair;
  - an **endotoxin exceedance** at the Hadapsar water plant **RO-H1**, through the incident report, patient transfers to Kothrud, the RCA and the resample;
  - **catheter infections at Pimpri**, through the infection reports, audit, action plan, training and re-audit;
  - **NABH accreditation readiness**, through the checklist, briefing, assessment and corrective-action tracker.
- **Management reporting:** monthly operations reviews, finance MIS for August and September, the Q3 quality report, the board note and the Q3 board pack.

Each document is backdated to the day listed in `demo-data/nephrova-manifest.json`. The knowledge graph is exported to `demo-data/nephrova-knowledge-graph.json`, and the source files are in `demo-data/nephrova/`.

**Rebuild:** run these with the ingestion venv's Python, with the stack running:

```bash
python scripts/demo/generate_dataset.py
python scripts/demo/seed_tenant.py
python scripts/demo/check_chat.py
```

`seed_tenant.py` can be run again safely. `--rebuild` wipes the documents and uploads them again.

---

## 2. Enron Corp. (real data)

### What the company did

Enron Corp. was a Houston-based **energy, commodities and services company**. It began in natural-gas pipelines and became one of the largest US **energy traders**: wholesale gas and electricity trading (Enron North America, EnronOnline), retail energy services (Enron Energy Services), gas transmission (Enron Transportation Services), broadband and international power projects. In late 2001 it restated its earnings after losses hidden in **special-purpose entities** (LJM, Chewco, the Raptors) came to light, and it filed for **bankruptcy in December 2001**. It is the only large public corpus of a real company's internal documents, which is why it was chosen.

### The data

Everything is **real public data**. Nothing is invented: no alerts, orders or compliance rules are seeded.

| Source | What | Count |
|---|---|---|
| **SEC EDGAR** (CIK 1024401), `scripts/enron/fetch_sec.py` | 10-K annual reports (1999, 2000), 10-Q quarterly reports (Q1 2000 to Q3 2001), 8-K current reports including the **Nov 2001 restatement** and the **Feb 2002 Powers Report**, and DEF 14A proxy statements (2000, 2001) | 20 filings |
| **Enron policies**, `scripts/enron/build_policies.py` | The July 2000 **Code of Ethics** booklet (OCR'd page by page from the public scan), the DOJ trial-exhibit summary, and 37 company policies announced by email (risk management, VaR limits, document and e-mail retention, HR, conflict of interest…) | 39 documents |
| **CMU Enron Email Corpus** (May 2015 release), `scripts/enron/build_emails.py` | 517,401 files from 150 mailboxes, deduplicated to **254,402 unique emails** from Jan 1999 to Jun 2002, bundled into one document per mailbox per month | 3,064 documents (314 MB) |

The tenant also has its own graph-schema extension, `scripts/enron/graph_schema_enron.json`, stored in `tenants.settings.graph_schema`. It adds Enron's SPEs, business units and finance issues as entity types and terms.

**Status (2026-10-26):** ingestion is still running. 1,124 of 3,123 documents are indexed (78,563 passages, 37,340 graph edges), with about 2,000 still queued. On a CPU-only machine it processes about 12 passages per second, so the full corpus takes several hours.

**Rebuild:** the raw data is gitignored under `.data/` and is downloaded and rebuilt by the scripts. Run them in order with the ingestion venv's Python:

```bash
python scripts/enron/fetch_sec.py
python scripts/enron/build_emails.py
python scripts/enron/build_policies.py
python scripts/enron/seed_tenant.py
python scripts/enron/check_chat.py   # 11 known-answer questions, each verified in the source
```
