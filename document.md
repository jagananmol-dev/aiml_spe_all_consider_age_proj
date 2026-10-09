# The 72 Sample Documents (Demo Tenant "Nephrova")

This file explains the sample data used to demonstrate VEDA: what the company is, why the documents were chosen, and what each of the 72 documents contains.

> **Everything here is fictional.** The company, every person and every number are invented for the demo. Patients appear only as de-identified IDs (for example `PMP-0412`). The files are in `demo-data/nephrova/`.

---

## 1. The company

| | |
|:--|:--|
| **Name** | Nephrova Renal Care Pvt. Ltd. (founded 2018) |
| **Niche** | Outpatient haemodialysis for people with chronic kidney disease, and nothing else (no wards, theatres or emergency) |
| **Centres** | 3 in Pune: **Kothrud** (12 machines, 96 patients), **Hadapsar** (10 machines, 80 patients), **Pimpri** (8 machines, 62 patients) |
| **Size** | 30 dialysis machines, 238 active patients, 74 staff, about 3,090 sessions a month |
| **Payers** | PM-JAY government scheme (INR 1,500 per session), self-pay (INR 2,000), private insurance (INR 2,400) |
| **Regulation** | NABH accreditation, ISO 23500 (dialysis water), Bio-Medical Waste Management Rules 2016, DPDP Act 2023 |
| **Demo login** | slug `nephrova`, email `demo@nephrova.example` (password in `scripts/demo/company.py`) |

Key people: Ritu Malhotra (CEO), Dr. Sameer Deshpande (Medical Director), Anjali Thomas (Chief Nursing Officer), Nikhil Joshi (Biomedical Engineering Lead), Rahul Pawar (Biomedical Technician), Pooja Shinde (Infection Control Nurse), Kiran Bhosale (Quality Manager), Vivek Jain (Finance Head), Snehal Patil (HR Manager), and the centre managers Amit Gokhale (Kothrud), Farah Khan (Hadapsar) and Suresh Nair (Pimpri).

Asset codes follow one scheme: `HD-K01`–`HD-K12`, `HD-H01`–`HD-H10` and `HD-P01`–`HD-P08` are dialysis machines (K = Kothrud, H = Hadapsar, P = Pimpri). `RO-K1`, `RO-H1` and `RO-P1` are the water treatment plants, `GEN-K1`, `GEN-H1` and `GEN-P1` the generators, and `UPS-P1` a UPS.

---

## 2. Why this dataset

The sample set was designed to test what a real company would ask, not just keyword search:

1. **A niche, regulated domain (healthcare).** Answers must use the company's own rules and limits, not general knowledge. A generic model doesn't know Nephrova's approval limit or notice period.
2. **Documents arrive day by day.** There is one document per day from **30 July to 9 October 2026**, and each is uploaded on its date, as a real company's data would grow. The upload dates are set from `demo-data/nephrova-manifest.json`.
3. **Every supported text format.** 8 formats, no images:

   | Format | Count | Typical content |
   |:--|:--:|:--|
   | PDF | 12 | Policies, lab reports, audits, the operations manual |
   | Word (.docx) | 12 | Incident and infection reports, minutes, board papers |
   | Markdown | 11 | Policies, SOPs, root cause analysis, lessons learned |
   | Text | 10 | Shift logs, emails, circulars, records |
   | Excel (.xlsx) | 9 | Finance MIS, registers, schedules, stock |
   | CSV | 6 | Alarm log, session counts, trackers, attendance |
   | JSON / JSONL | 6 | Inventory, records, KPI dashboard, checklist |
   | PowerPoint (.pptx) | 6 | Monthly reviews, briefings, action plans |

4. **Connected stories.** Four real-world incidents each run across 6–12 documents of different formats, so answering one question needs facts from several files (see section 3).
5. **Policies with exact rules.** 6 HR and 5 finance policies, plus clinical policies, contain precise numbers (approval limits, allowances, notice periods). The chatbot must apply them.
6. **Three long, connected documents.** The **Operations Manual**, the **Risk and Asset Register** and the **Q3 Board Pack** reference many other documents. They test retrieval over long texts and cross-document questions.

---

## 3. The four connected stories

### Story A: Dialysis machine HD-K04 alarms (Kothrud, August)
HD-K04 gave 6 conductivity alarms between 11 and 13 August. It was tagged out of service, and the biomedical engineer found a scaled conductivity cell reading 15.6 mS/cm against the true 14.0 mS/cm. A **conductivity cell replacement** and calibration fixed it, and the machine was released on 15 August. The lesson: take a machine out of service after the *second* unexplained alarm.
Documents: #13, #14, #15, #16, #17, #31, #69, #72

### Story B: Water plant RO-H1 endotoxin (Hadapsar, August)
The monthly water test showed **endotoxin at 0.31 EU/mL**, above the 0.25 limit. Hadapsar ran a reduced schedule, and **64 sessions** moved to Kothrud (21–26 August). The plant got chemical and heat disinfection, and the resample was clean (0.04 EU/mL). Root cause: the August disinfection was missed because only one technician was trained to do it, and it was already a known risk (RSK-02).
Documents: #2, #19, #20, #23, #24, #25, #26, #27, #28, #29, #52, #55–#58, #69, #72

### Story C: Generator GEN-P1 starts late (Pimpri, September)
During a mains power failure, the UPS carried all machines, but **GEN-P1 took 45 seconds** to start (target 10 s). The cause was a weak starter battery. After a **battery replacement** and load test, it started in 8 s.
Documents: #40, #41, #69, #72

### Story D: Catheter infections (Pimpri, September)
Two catheter-related bloodstream infections occurred in one month, both **treated with vancomycin**. An audit found hand hygiene at 78% and the care bundle at 70% (target 90%), with audits done quarterly instead of monthly. Staff were retrained, and the re-audit reached **94%** and **92%**.
Documents: #36, #45, #46, #48, #49, #50, #51, #52, #63, #69, #72

These stories feed the **NABH surveillance assessment** on 24 September (0 major and 3 minor findings, accreditation continues: #55–#58, #70, #71), the **finances** (#33, #34, #44, #64–#66) and the **Q3 board papers** (#67, #68, #72).

---

## 4. All 72 documents

Category key: **Ref** = long reference, **HR**, **Fin** = finance, **Clin** = clinical policy or SOP, **Ops** = operational record, **Qual** = quality and compliance, **Mgmt** = management reporting.

| # | Uploaded | Format | File | Cat. | What it contains |
|:-:|:--|:--|:--|:--|:--|
| 1 | 30 Jul | PDF | Nephrova_Operations_Manual_2026.pdf | Ref | Operations manual v3.0 (1,285 words): how dialysis runs at all 3 centres, with pointers to each SOP and policy. Covers alarms, water, infection control, complications and their treatment. |
| 2 | 31 Jul | Excel | Risk_and_Asset_Register_2026.xlsx | Ref | Risks RSK-01 to RSK-09 with likelihood, impact, score, controls and owner (RSK-02 = single-person dependence). Asset sheet of machines and generators. |
| 3 | 1 Aug | Markdown | HR_Code_of_Conduct.md | HR | Patients first, honest records, no gifts above INR 1,000, report every incident. |
| 4 | 2 Aug | Word | HR_Recruitment_and_Onboarding_Policy.docx | HR | CEO approves vacancies, required qualifications, referral bonus INR 10,000, hepatitis B check before the first shift. |
| 5 | 3 Aug | PDF | HR_Compensation_and_Benefits_Policy.pdf | HR | Evening shift allowance **INR 120** per shift ending after 20:00, overtime at 2×, PF 12%, medical cover INR 3 lakh. |
| 6 | 4 Aug | Word | HR_Performance_Appraisal_Policy.docx | HR | April cycle. Increments by rating: 5 → 12%, **4 → 9%**, 3 → 6%, 2 → 3%, 1 → 0% plus an improvement plan. |
| 7 | 5 Aug | Markdown | HR_POSH_Policy.md | HR | Prevention of sexual harassment: Internal Committee (presiding officer Anjali Thomas), complaints within 3 months, inquiry within 90 days. |
| 8 | 6 Aug | Text | HR_Circular_Notice_Period_and_Exit.txt | HR | Notice period: **30 days** for nurses and technicians, 60 for managers. Exit steps; settlement within 45 days. |
| 9 | 7 Aug | PDF | Finance_Delegation_of_Financial_Authority.pdf | Fin | Approval limits: Centre Manager **INR 25,000**, BME Lead 50,000, Finance Head 5 lakh, CEO 25 lakh, Board above that. Urgent patient-safety buys up to 1 lakh. |
| 10 | 8 Aug | Word | Finance_Billing_and_Collections_Policy.docx | Fin | Session rates by payer, PM-JAY claims within **7 days**, dues over 90 days escalated weekly. |
| 11 | 9 Aug | Markdown | Finance_Patient_Refund_and_Assistance_Policy.md | Fin | Refunds within 7 working days. **50% discount** for self-pay families earning under INR 3 lakh with no cover. |
| 12 | 10 Aug | Markdown | Infection_Control_Policy.md | Clin | Monthly hand hygiene audits (target 90%), catheter care bundle, blood-borne virus screening. |
| 13 | 11 Aug | Text | shift_log_KTH_2026-08-11.txt | Ops | Kothrud shift log: HD-K04 conductivity alarms at 08:05 and 11:40; machine tagged "do not use". |
| 14 | 12 Aug | CSV | machine_alarm_log_KTH_2026-08-12.csv | Ops | Alarm log: HD-K04 conductivity alarms, HD-K07 venous pressure alarm, HD-K09 air detector alarm. |
| 15 | 13 Aug | Text | email_HD-K04_service_request.txt | Ops | Centre manager to the BME lead: 6 alarms in 3 days, Kothrud running on 11 machines. |
| 16 | 14 Aug | Word | BME_Job_Report_BME-2026-0311_HD-K04.docx | Ops | Repair report: reads 15.6 vs 14.0 mS/cm, scaled cell; **conductivity cell replacement** and calibration; released 15 Aug. |
| 17 | 15 Aug | Excel | Weekly_Session_Census_Week33.xlsx | Ops | Daily sessions per centre for week 33 (716 in total), with a note on the out-of-service machine. |
| 18 | 16 Aug | JSON | equipment_inventory.json | Ref | All 30 machines (Renalis R5, install year), generators and UPS, by centre. |
| 19 | 17 Aug | PDF | SOP-WT-002_Dialysis_Water_Treatment.pdf | Clin | ISO 23500 limits: bacteria 50 / **100** CFU/mL, endotoxin 0.125 / **0.25** EU/mL. Monthly testing and disinfection; what to do above the limit. |
| 20 | 18 Aug | Text | water_sample_record_RO-H1_2026-08-18.txt | Ops | Sample collection record for RO-H1, sent to City Diagnostic Laboratory. |
| 21 | 19 Aug | Markdown | Patient_Transfer_Protocol.md | Clin | How sessions move between centres; hepatitis B positive patients only where an isolation machine is free. |
| 22 | 20 Aug | PowerPoint | July_2026_Operations_Review.pptx | Mgmt | July: 3,080 sessions, revenue INR 57.13 lakh. |
| 23 | 21 Aug | PDF | Water_Lab_Report_RO-H1_Aug2026.pdf | Ops | Lab result: endotoxin **0.31 EU/mL, above the 0.25 limit**; bacteria 48 CFU/mL. |
| 24 | 22 Aug | Word | Incident_Report_IR-2026-031_RO-H1.docx | Qual | Incident report: reduced schedule, **64 sessions moved to Kothrud**, chemical and heat disinfection; cause: missed 2 Aug disinfection. |
| 25 | 23 Aug | CSV | session_transfers_HDP_to_KTH_Aug2026.csv | Ops | Sessions moved Hadapsar → Kothrud, day by day (64 in total). |
| 26 | 24 Aug | JSON | disinfection_record_RO-H1.json | Ops | RO-H1 disinfection log: July done, **2 Aug missed**, 22 Aug chemical and heat, resample 23 Aug. |
| 27 | 25 Aug | JSONL | water_test_results_2026.jsonl | Ops | Monthly bacteria and endotoxin results for all 3 plants since March. |
| 28 | 26 Aug | PDF | Water_Lab_Report_RO-H1_Resample.pdf | Ops | Resample: bacteria 6 CFU/mL, endotoxin 0.04 EU/mL; water suitable again. |
| 29 | 27 Aug | Markdown | RCA_RO-H1_Endotoxin.md | Qual | Root cause analysis: only one trained technician, who was on leave. Corrective actions with owners. |
| 30 | 28 Aug | Excel | PM_Schedule_2026.xlsx | Ops | Six-monthly machine maintenance per centre; monthly water disinfection and tests. |
| 31 | 29 Aug | Text | shift_log_KTH_2026-08-29.txt | Ops | Preventive maintenance of all 12 Kothrud machines completed; extra evening shift ended. |
| 32 | 30 Aug | Word | Notice_Hepatitis_B_Vaccination_Drive.docx | HR | Staff vaccination drive on 2 Sep at Kothrud; 46 staff asked to attend. |
| 33 | 31 Aug | CSV | monthly_sessions_aug_2026.csv | Fin | August sessions by centre and payer (1,312 / 976 / 806). |
| 34 | 1 Sep | Excel | Finance_MIS_Aug_2026.xlsx | Fin | August P&L: revenue INR 57.39 lakh, EBITDA 4.76 lakh; PM-JAY outstanding 31.2 lakh. |
| 35 | 2 Sep | Text | vaccination_drive_summary_2026-09-02.txt | HR | **41** of 46 staff vaccinated; 5 at the next drive. |
| 36 | 3 Sep | Word | Infection_Report_Case1_PMP-0412.docx | Clin | Case 1: catheter-related bloodstream infection, **treated with vancomycin** for 3 weeks. |
| 37 | 4 Sep | PowerPoint | August_2026_Operations_Review.pptx | Mgmt | August: 3,094 sessions (including 64 Hadapsar sessions at Kothrud); revenue and EBITDA. |
| 38 | 5 Sep | Markdown | Hand_Hygiene_Policy.md | Clin | The five moments, hand rub technique, monthly audit of at least 30 observations, target 90%. |
| 39 | 6 Sep | JSON | staff_roster_week37.json | Ops | Shifts and staffing per centre; on-call nephrologist and engineer. |
| 40 | 7 Sep | Text | shift_log_PMP_2026-09-07.txt | Ops | Pimpri mains power failure: the UPS carried the machines, **GEN-P1 started after 45 s** (target 10 s). |
| 41 | 8 Sep | PDF | Generator_Load_Test_GEN-P1.pdf | Ops | Weak starter battery (11.2 V); **battery replacement** and load test; now starts in 8 s. |
| 42 | 9 Sep | PDF | Finance_Procurement_Policy.pdf | Fin | Three quotations above INR 50,000; emergency purchases up to INR 1 lakh. |
| 43 | 10 Sep | Markdown | Biomedical_Waste_Management_SOP.md | Clin | Colour-coded bags, Bio-Medical Waste Rules 2016, collection every 24 hours. |
| 44 | 11 Sep | Excel | PMJAY_Claims_Ageing_Sep2026.xlsx | Fin | PM-JAY claims by age; 12 claims over 90 days (INR 3.2 lakh). |
| 45 | 12 Sep | Word | Infection_Report_Case2_PMP-0388.docx | Clin | Case 2: second infection at Pimpri, vancomycin plus catheter exchange; audit scheduled. |
| 46 | 13 Sep | Text | email_infection_alert_PMP.txt | Qual | Infection nurse's alert: two infections this month against a usual rate below one. |
| 47 | 14 Sep | Excel | Finance_Travel_and_Expense_Rates.xlsx | Fin | Hotel and meal limits, per-km rates, claim rules. |
| 48 | 15 Sep | PDF | Infection_Control_Audit_PMP_Sep2026.pdf | Qual | Pimpri audit: hand hygiene **78%**, bundle 70%; audits were quarterly, not monthly. |
| 49 | 16 Sep | PowerPoint | Pimpri_Infection_Action_Plan.pptx | Qual | Action plan: train 22 staff on 17–19 Sep, monthly audits, re-audit on 30 Sep. |
| 50 | 17 Sep | CSV | training_attendance_hand_hygiene_sep2026.csv | HR | Who attended the hand hygiene training (Pimpri staff, by date). |
| 51 | 18 Sep | Markdown | Catheter_Care_Bundle.md | Clin | The 6 required steps at every catheter connection. |
| 52 | 19 Sep | Word | Quality_Committee_Minutes_Sep2026.docx | Qual | Minutes: water incident closed, Pimpri infections, NABH assessment due 24 Sep. |
| 53 | 20 Sep | Excel | Consumables_Stock_Sep2026.xlsx | Ops | Stock and days of cover per centre; reorder below 14 days; lock caps on order. |
| 54 | 21 Sep | PowerPoint | Nursing_Quality_Indicators_Aug2026.pptx | Clin | Kt/V ≥ 1.2 in 91% of patients; hypotension 3.1 per 100 sessions, treated with normal saline; anaemia indicator. |
| 55 | 22 Sep | JSON | nabh_document_checklist.json | Qual | Pre-assessment check: gaps in the Hadapsar disinfection log and Pimpri audit frequency. |
| 56 | 23 Sep | PowerPoint | NABH_Readiness_Briefing.pptx | Qual | Briefing before the NABH assessment (assessor Dr. R. Iyer), with the known gaps. |
| 57 | 24 Sep | PDF | NABH_Surveillance_Assessment_Report.pdf | Qual | **0 major, 3 minor** non-conformities (NC-1 to NC-3); accreditation continues; evidence due 24 Oct. |
| 58 | 25 Sep | CSV | nabh_corrective_action_tracker.csv | Qual | Each finding with its action, owner, due date and status. |
| 59 | 26 Sep | Markdown | Patient_Privacy_Notice.md | Clin | What patient data is collected and why, rights under the DPDP Act 2023, retention. |
| 60 | 27 Sep | Text | shift_log_HDP_2026-09-27.txt | Ops | Normal Hadapsar day; one low blood pressure episode treated with saline. |
| 61 | 28 Sep | Word | HR_Leave_and_Attendance_Policy.docx | HR | Leave days (15 earned, 7 casual, 10 sick); every critical task needs a named backup. |
| 62 | 29 Sep | Excel | Staff_Strength_Sep2026.xlsx | HR | 74 staff by role and by centre. |
| 63 | 30 Sep | PDF | Infection_Control_Reaudit_PMP_Sep30.pdf | Qual | Re-audit: hand hygiene **94%**, bundle 92%; no new infections. |
| 64 | 1 Oct | CSV | monthly_sessions_sep_2026.csv | Fin | September sessions by centre and payer (1,236 / 1,044 / 812). |
| 65 | 2 Oct | JSON | kpi_dashboard_q3_2026.json | Mgmt | Q3 KPIs: monthly sessions, revenue and EBITDA; 238 patients; PM-JAY outstanding **INR 38.6 lakh**. |
| 66 | 3 Oct | Excel | Finance_MIS_Sep_2026.xlsx | Fin | September P&L: revenue INR **57.36 lakh**, EBITDA 4.74 lakh; 112 claims over 30 days. |
| 67 | 4 Oct | PowerPoint | September_2026_Operations_Review.pptx | Mgmt | September: 3,092 sessions; **Q3 total 9,266**; quality summary. |
| 68 | 5 Oct | Word | Board_Note_Q3_2026.docx | Mgmt | Short board note: Q3 revenue INR 171.88 lakh, EBITDA 14.11 lakh; key risks. |
| 69 | 6 Oct | Markdown | Lessons_Learned_Q3_2026.md | Qual | One lesson per incident, including "out of service after the second unexplained alarm". |
| 70 | 7 Oct | Text | email_NABH_closure_status.txt | Qual | Two of the three NABH findings closed; the third due this week. |
| 71 | 8 Oct | PDF | Q3_2026_Quality_Report.pdf | Qual | Q3 quality indicators; all incidents closed; one corrective action open until 24 Oct. |
| 72 | 9 Oct | Word | Q3_2026_Board_Pack.docx | Ref | Board pack (1,213 words): summary, finance, the incidents, risks, and decisions for the Board, with each figure's source named. |

Most documents are short (40–160 words), like real records and policies. Three are long (#1, #2, #72). In total the set is indexed as **92 passages**.

---

## 5. What the system builds from them

- **Search index.** Each document is split into passages, merged up to 1,500 characters, and each passage is embedded together with its document title.
- **Knowledge graph.** A full rebuild from these 72 documents gives **166 nodes and 342 edges**:
  - 63 document nodes, each linked to the entities it mentions
  - 29 assets (machines, water plants, generators, UPS)
  - 8 failures or alarms and 9 maintenance actions
  - 9 clinical conditions and 6 medicines
  - 27 people and 4 places
  - 5 regulations and 6 measurements

  Examples of edges: `HD-K04 → FAILED_WITH → conductivity alarm → REPAIRED_BY → conductivity cell replacement`, `RO-H1 → FAILED_WITH → endotoxin exceedance`, `catheter-related bloodstream infection → TREATED_WITH → vancomycin`, `GEN-P1 → LOCATED_IN → Pimpri`.

  Nine documents have no document node because they hold only figures with no named entities: #17, #25, #33, #34, #38, #62, #64, #65 and #66. Their content is still fully searchable in chat.
- **Maintenance Intel.** Assets with their issues and fixes, read from the graph (for example RO-H1: endotoxin exceedance → chemical and heat disinfection).

---

## 6. How the demo is checked

`scripts/demo/check_chat.py` asks the chatbot 22 questions with known answers:

| Question | Expected answer | Answer is in |
|:--|:--|:--|
| What is wrong with HD-K04 and how was it fixed? | conductivity alarms; cell replaced | #13–#16 |
| Endotoxin result for RO-H1 in August? | 0.31 EU/mL | #23 |
| Why did the Hadapsar water plant fail its test? | missed disinfection | #24, #29 |
| How many Hadapsar sessions moved to Kothrud? | 64 | #24, #25 |
| Endotoxin limit for dialysis water? | 0.25 EU/mL | #19 |
| Why did GEN-P1 start late on 7 September? | weak battery | #40, #41 |
| How were the Pimpri catheter infections treated? | vancomycin | #36, #45 |
| Pimpri hand hygiene before and after training? | 78% → 94% | #48, #63 |
| Results of the NABH assessment? | 3 minor | #57 |
| Total revenue in September 2026? | INR 57.36 lakh | #66 |
| PM-JAY outstanding at end of September? | INR 38.6 lakh | #65, #66 |
| Staff vaccinated on 2 September? | 41 | #35 |
| Can a centre manager approve a INR 40,000 spare part? | No, their limit is INR 25,000 | #9 (policy) |
| Notice period for a dialysis technician? | 30 days | #8 (policy) |
| Evening allowance for a shift ending at 22:00? | INR 120 | #5 (policy) |
| Help for a self-pay family earning INR 2 lakh? | 50% discount | #11 (policy) |
| Deadline for a PM-JAY claim? | 7 days | #10 (policy) |
| Increment for rating 4? | 9% | #6 (policy) |
| Was the Hadapsar incident a known risk? | yes, RSK-02 | #2 (long document) |
| What decisions is the Board asked to take? | includes INR 1.8 lakh to train a second water-plant technician per centre | #72 (long document) |
| What to do after a second unexplained alarm? | take it out of service | #69, #1 |
| Sessions run in Q3 2026? | 9,266 | #67, #72 |

All 22 pass. The six policy questions show the agent applying company rules. The cross-document and long-document questions show retrieval across files.

---

## 7. Rebuilding the demo

```bash
services/ingestion/.venv/Scripts/python.exe scripts/demo/generate_dataset.py   # regenerate the 72 files
services/ingestion/.venv/Scripts/python.exe scripts/demo/validate_graph.py     # parse every file, list graph edges
services/ingestion/.venv/Scripts/python.exe scripts/demo/seed_tenant.py        # upload with backdated dates (idempotent)
services/ingestion/.venv/Scripts/python.exe scripts/demo/check_chat.py         # the 22 questions
services/ingestion/.venv/Scripts/python.exe scripts/demo/export_graph.py       # graph export + upload-date check
```

All names, dates and numbers come from one file, `scripts/demo/company.py`, so the 72 documents agree with each other.
