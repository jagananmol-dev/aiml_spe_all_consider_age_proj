"""
Generate the Nephrova Renal Care demo dataset: 72 documents in 8 formats,
one per day from 30 July to 9 October 2026 — the documents a dialysis
company produces and uploads day by day.

    services/ingestion/.venv/Scripts/python.exe scripts/demo/generate_dataset.py

Output:
  demo-data/nephrova/<format>/<file>   the documents
  demo-data/nephrova-manifest.json     file → upload date (used to backdate uploads)

All facts come from company.py.
"""

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import company as C  # noqa: E402
from company import person  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "demo-data" / "nephrova"
MANIFEST = ROOT / "demo-data" / "nephrova-manifest.json"
FIRST_DAY = date(2026, 7, 30)
TOTAL_DAYS = 72

K, R, G, I, N, HB = C.HDK04, C.ROH1, C.GENP1, C.CRBSI, C.NABH, C.HEPB
W = C.WATER

DOCS: list[tuple[str, str, str, callable]] = []  # (date, format folder, file name, builder)


def doc(day: str, fmt: str, name: str):
    def register(builder):
        DOCS.append((day, fmt, name, builder))
        return builder
    return register


def out(fmt: str, name: str) -> Path:
    path = DATA / fmt / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── Writers ───────────────────────────────────────────
CSS = """
body { font-family: sans-serif; font-size: 10pt; }
h1 { font-size: 15pt; } h2 { font-size: 12pt; }
table { border-collapse: collapse; } td, th { border: 1px solid #555; padding: 3px; font-size: 9pt; }
"""


def write_pdf(name: str, html: str) -> None:
    import fitz

    html = f"<p><b>{C.COMPANY}</b></p>" + html
    story = fitz.Story(html=html, user_css=CSS)
    writer = fitz.DocumentWriter(str(out("pdf", name)))
    more = True
    while more:
        dev = writer.begin_page(fitz.paper_rect("a4"))
        more, _ = story.place(fitz.paper_rect("a4") + (50, 50, -50, -50))
        story.draw(dev)
        writer.end_page()
    writer.close()


def html_table(header: list, rows: list[list]) -> str:
    head = "".join(f"<th>{h}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def write_docx(name: str, title: str, blocks: list) -> None:
    """blocks: ("h", text) | ("p", text) | ("t", header, rows)"""
    import docx

    d = docx.Document()
    d.add_paragraph(C.COMPANY)
    d.add_heading(title, level=0)
    for block in blocks:
        if block[0] == "h":
            d.add_heading(block[1], level=1)
        elif block[0] == "p":
            d.add_paragraph(block[1])
        else:
            header, rows = block[1], block[2]
            table = d.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = str(text)
            for r in rows:
                for cell, text in zip(table.add_row().cells, r):
                    cell.text = str(text)
    d.save(out("word", name))


def write_xlsx(name: str, sheets: dict[str, list[list]]) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        ws.append([C.COMPANY, title])
        for r in rows:
            ws.append(r)
    wb.save(out("excel", name))


def write_pptx(name: str, slides: list[tuple[str, list[str]]], notes: dict[int, str] | None = None) -> None:
    from pptx import Presentation

    deck = Presentation()
    for index, (title, bullets) in enumerate(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        body = slide.placeholders[1].text_frame
        body.text = bullets[0]
        for b in bullets[1:]:
            body.add_paragraph().text = b
        if index == 0 and C.SHORT not in " ".join([title, *bullets]):
            body.add_paragraph().text = C.COMPANY
        if notes and index in notes:
            slide.notes_slide.notes_text_frame.text = notes[index]
    deck.save(out("powerpoint", name))


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    with open(out("csv", name), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["organisation", *header])
        w.writerows([[C.COMPANY, *r] for r in rows])


def write_json(name: str, data) -> None:
    assert isinstance(data, dict), "JSON documents are objects so they can carry the organisation"
    data = {"organisation": C.COMPANY, **data}
    out("json", name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(name: str, records: list[dict]) -> None:
    records = [{"organisation": C.COMPANY, **r} for r in records]
    out("json", name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")


def write_text(fmt: str, name: str, text: str) -> None:
    text = text.strip()
    if C.SHORT not in text:
        if fmt == "markdown" and text.startswith("# "):
            title, _, rest = text.partition("\n")
            text = f"{title}\n\n{C.COMPANY}\n{rest}"
        else:
            text = f"{C.COMPANY}\n{text}"
    out(fmt, name).write_text(text + "\n", encoding="utf-8")


def inr_lakh(x: float) -> str:
    return f"INR {x:.2f} lakh"


# ══════════════════════════════════════════════════════
# Week 1 — 10 to 16 August: HD-K04 conductivity alarms
# ══════════════════════════════════════════════════════
@doc("2026-08-10", "markdown", "Infection_Control_Policy.md")
def _():
    write_text("markdown", "Infection_Control_Policy.md", f"""
# Infection Control Policy

Owner: {person('infection')}, Infection Control Nurse. Approved by {person('medical')}, Medical Director.
Applies to all three {C.SHORT} centres.

## Hand hygiene

- Clean hands before and after every patient contact, before any aseptic task, and after touching the dialysis station.
- Hand hygiene compliance is audited **every month** at each centre. Target: {I['target']} percent.

## Vascular access care

- Catheter connection and disconnection follow the catheter care bundle (chlorhexidine scrub, sterile caps, dressing check).
- Every suspected bloodstream infection is reported to the Infection Control Nurse the same day.

## Blood-borne viruses

- Patients are screened for hepatitis B, hepatitis C and HIV on admission and every six months.
- Patients positive for hepatitis B are dialysed on dedicated machines in an isolation bay.

## Surveillance

The infection rate is reported monthly per 1,000 catheter days for each centre.
""")


@doc("2026-08-11", "text", "shift_log_KTH_2026-08-11.txt")
def _():
    write_text("text", "shift_log_KTH_2026-08-11.txt", f"""
SHIFT LOG — Nephrova Kothrud
Date: 11 August 2026    Shift: Morning (06:30 to 14:30)    In charge: {person('mgr_kth')}

06:30  14 patients scheduled across 12 machines. All machines passed pre-treatment tests.
08:05  HD-K04 conductivity alarm during treatment. Treatment paused, dialysate rechecked, treatment resumed.
11:40  HD-K04 conductivity alarm again. Patient moved to a spare station to finish treatment.
12:00  HD-K04 tagged "do not use" until checked by biomedical engineering.
14:30  All 28 sessions of the shift completed.
""")


@doc("2026-08-12", "csv", "machine_alarm_log_KTH_2026-08-12.csv")
def _():
    rows = [
        ["2026-08-11", "08:05", "HD-K04", "conductivity alarm", "Dialysate rechecked, treatment resumed"],
        ["2026-08-11", "11:40", "HD-K04", "conductivity alarm", "Patient moved to spare station"],
        ["2026-08-12", "07:20", "HD-K04", "conductivity alarm", "Machine stopped before treatment"],
        ["2026-08-12", "07:55", "HD-K04", "conductivity alarm", "Repeated during self test"],
        ["2026-08-12", "09:10", "HD-K07", "venous pressure alarm", "Needle position corrected by nurse"],
        ["2026-08-12", "10:30", "HD-K04", "conductivity alarm", "Machine kept out of service"],
        ["2026-08-12", "13:15", "HD-K09", "air detector alarm", "Blood line re-primed"],
    ]
    write_csv("machine_alarm_log_KTH_2026-08-12.csv", ["date", "time", "machine", "alarm", "action"], rows)


@doc("2026-08-13", "text", "email_HD-K04_service_request.txt")
def _():
    write_text("text", "email_HD-K04_service_request.txt", f"""
From: {person('mgr_kth')} <amit.gokhale@nephrova.example>
To: {person('bme_lead')} <nikhil.joshi@nephrova.example>
Date: 13 August 2026
Subject: HD-K04 — repeated conductivity alarms

Nikhil,

HD-K04 has given {K['alarm_total']} conductivity alarms between 11 and 13 August, including one today.
The machine is tagged out of service. Kothrud is running on 11 machines, which is tight for the evening shift.
Please send a technician as soon as possible.

Regards,
{person('mgr_kth')}
Centre Manager, Kothrud
""")


@doc("2026-08-14", "word", "BME_Job_Report_BME-2026-0311_HD-K04.docx")
def _():
    write_docx("BME_Job_Report_BME-2026-0311_HD-K04.docx", f"Biomedical Job Report {K['job']}", [
        ("p", f"Equipment: HD-K04 (dialysis machine, Nephrova Kothrud). Engineer: {person('bme_tech')}. Date: {K['repaired']}."),
        ("h", "Complaint"),
        ("p", f"Repeated conductivity alarms on HD-K04 ({K['alarm_total']} alarms from 11 to 13 August)."),
        ("h", "Findings"),
        ("p", f"HD-K04 read a dialysate conductivity of {K['measured']} mS/cm against {K['reference']} mS/cm on the reference meter."),
        ("p", "The conductivity cell was coated with scale and gave unstable readings."),
        ("h", "Work done"),
        ("p", "HD-K04 received a conductivity cell replacement followed by calibration against the reference meter."),
        ("p", f"After repair HD-K04 read {K['reference']} mS/cm, matching the reference meter."),
        ("h", "Result"),
        ("p", f"Machine released for patient use on {K['back']} after a full self test."),
    ])


@doc("2026-08-15", "excel", "Weekly_Session_Census_Week33.xlsx")
def _():
    days = ["2026-08-09", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"]
    kth = [42, 43, 41, 40, 41, 42, 43]
    hdp = [34, 35, 34, 35, 33, 34, 35]
    pmp = [26, 27, 26, 26, 27, 26, 26]
    rows = [["Date", "Kothrud", "Hadapsar", "Pimpri", "Total"]]
    rows += [[d, a, b, c, a + b + c] for d, a, b, c in zip(days, kth, hdp, pmp)]
    rows.append(["Week total", sum(kth), sum(hdp), sum(pmp), sum(kth) + sum(hdp) + sum(pmp)])
    write_xlsx("Weekly_Session_Census_Week33.xlsx", {
        "Sessions": rows,
        "Notes": [["Kothrud", "Ran on 11 machines from 11 to 14 August while one machine was out of service"]],
    })


@doc("2026-08-16", "json", "equipment_inventory.json")
def _():
    centres = []
    for code, (name, area, letter, count, _, _) in C.CENTRES.items():
        centres.append({
            "centre": name,
            "dialysis_machines": [{"tag": t, "model": "Renalis R5", "installed": 2021 if code != "PMP" else 2023}
                                  for t in C.machines(code)],
            "water_plant": {"tag": f"RO-{letter}1", "type": "Double-pass reverse osmosis"},
            "generator": {"tag": f"GEN-{letter}1", "rating": "125 kVA"},
        })
    write_json("equipment_inventory.json", {"company": C.COMPANY, "centres": centres,
                                            "total_dialysis_machines": C.TOTAL_MACHINES})


# ══════════════════════════════════════════════════════
# Week 2 — 17 to 23 August: RO-H1 water quality
# ══════════════════════════════════════════════════════
@doc("2026-08-17", "pdf", "SOP-WT-002_Dialysis_Water_Treatment.pdf")
def _():
    write_pdf("SOP-WT-002_Dialysis_Water_Treatment.pdf", f"""<h1>SOP-WT-002 — Dialysis Water Treatment and Testing</h1>
<p>Owner: {person('bme_lead')}. Applies to the water plants of all three centres. Revision 3.</p>
<h2>1. Limits for product water (ISO 23500)</h2>
{html_table(['Parameter', 'Action level', 'Maximum'], [
    ['Bacteria', f"{W['bacteria_action']} CFU/mL", f"{W['bacteria_max']} CFU/mL"],
    ['Endotoxin', f"{W['endotoxin_action']} EU/mL", f"{W['endotoxin_max']} EU/mL"],
])}
<h2>2. Testing</h2>
<p>A sample is taken from the end of the distribution loop every month and sent to the external laboratory.</p>
<h2>3. Disinfection</h2>
<p>Each water plant and its distribution loop receive chemical disinfection every month, recorded in the disinfection log.</p>
<h2>4. Results above the maximum</h2>
<p>Inform the Medical Director the same day, reduce or stop dialysis at the centre, disinfect the plant and loop, and resample.
Dialysis resumes only after a result below the action level.</p>""")


@doc("2026-08-18", "text", "water_sample_record_RO-H1_2026-08-18.txt")
def _():
    write_text("text", "water_sample_record_RO-H1_2026-08-18.txt", f"""
WATER SAMPLE COLLECTION RECORD — Nephrova Hadapsar
Date: {R['sampled']}    Collected by: {person('senior_tech')}
Plant: RO-H1    Sample point: end of distribution loop
Tests requested: bacteria culture, endotoxin
Sample sent to: City Diagnostic Laboratory, Pune (in a cold box)
Expected result: 21 August 2026
""")


@doc("2026-08-19", "markdown", "Patient_Transfer_Protocol.md")
def _():
    write_text("markdown", "Patient_Transfer_Protocol.md", f"""
# Protocol: Moving Dialysis Sessions Between Centres

Owner: {person('nursing')}, Chief Nursing Officer.

## When this applies

When a centre cannot run its full schedule (water quality, power, staff shortage), sessions move to the nearest centre with capacity.

## Steps

1. The Centre Manager lists affected patients and informs the Chief Nursing Officer.
2. The receiving centre confirms free slots, usually in an extra evening shift.
3. Patient records, last three treatment charts and serology results are shared before the first session.
4. Patients positive for hepatitis B are transferred only if the receiving centre has a free isolation machine.
5. Transport is arranged for patients who cannot travel on their own.

## Records

Every moved session is logged with date, patient ID, sending and receiving centre.
""")


@doc("2026-08-20", "powerpoint", "July_2026_Operations_Review.pptx")
def _():
    s = C.SESSIONS["Jul"]
    write_pptx("July_2026_Operations_Review.pptx", [
        ("July 2026 Operations Review", [C.COMPANY, f"Presented by {person('ceo')}, 20 August 2026"]),
        ("Sessions", [f"Kothrud: {s['KTH']}", f"Hadapsar: {s['HDP']}", f"Pimpri: {s['PMP']}",
                      f"Total: {C.month_sessions('Jul')}"]),
        ("Revenue", [f"July revenue: {inr_lakh(C.revenue_lakh('Jul'))}", f"Blended rate: INR {C.BLENDED_RATE} per session"]),
        ("Focus for August", ["Close PM-JAY claims older than 30 days", "Six-monthly machine maintenance at Kothrud"]),
    ])


@doc("2026-08-21", "pdf", "Water_Lab_Report_RO-H1_Aug2026.pdf")
def _():
    write_pdf("Water_Lab_Report_RO-H1_Aug2026.pdf", f"""<h1>City Diagnostic Laboratory — Dialysis Water Report</h1>
<p>Client: {C.COMPANY}, Hadapsar centre. Sample: RO-H1 product water, end of loop. Collected {R['sampled']}. Reported {R['result_date']}.</p>
{html_table(['Test', 'Result', 'Maximum allowed', 'Status'], [
    ['Bacteria culture', f"{R['bacteria']} CFU/mL", f"{W['bacteria_max']} CFU/mL", 'Within limit'],
    ['Endotoxin', f"{R['endotoxin']} EU/mL", f"{W['endotoxin_max']} EU/mL", 'ABOVE LIMIT'],
])}
<p>The RO-H1 sample showed endotoxin exceedance at {R['endotoxin']} EU/mL.</p>
<p>Results for RO-H1 are assessed against the ISO 23500 limits for dialysis water.</p>
<p>The bacteria count of {R['bacteria']} CFU/mL is just below the action level of {W['bacteria_action']} CFU/mL.</p>""")


@doc("2026-08-22", "word", "Incident_Report_IR-2026-031_RO-H1.docx")
def _():
    write_docx("Incident_Report_IR-2026-031_RO-H1.docx", f"Incident Report {R['incident']} — Hadapsar Dialysis Water", [
        ("p", f"Reported by {person('mgr_hdp')} on {R['result_date']}. Reviewed by {person('medical')}."),
        ("h", "What happened"),
        ("p", f"The monthly test of RO-H1 product water showed endotoxin exceedance at {R['endotoxin']} EU/mL "
              f"(maximum {W['endotoxin_max']} EU/mL)."),
        ("h", "Immediate actions"),
        ("p", f"Hadapsar ran a reduced schedule and {R['transferred_sessions']} sessions were moved to Kothrud during {R['transfer_window']}."),
        ("p", f"RO-H1 received chemical disinfection and heat disinfection of the loop on {R['disinfected']}."),
        ("p", "All Hadapsar patients dialysed in the week before the result were reviewed by the nephrologist; "
              "none had fever or chills during treatment."),
        ("h", "Why it happened"),
        ("p", f"The disinfection of RO-H1 due on {R['missed_due']} was missed because the trained technician was on leave and no backup was named. "
              f"The last disinfection before the result was on {R['last_disinfection']}."),
    ])


@doc("2026-08-23", "csv", "session_transfers_HDP_to_KTH_Aug2026.csv")
def _():
    write_csv("session_transfers_HDP_to_KTH_Aug2026.csv",
              ["date", "from_centre", "to_centre", "sessions_moved", "reason"],
              [[d, "Hadapsar", "Kothrud", n, "Hadapsar water plant out of use"] for d, n in C.TRANSFERS])


# ══════════════════════════════════════════════════════
# Week 3 — 24 to 30 August: recovery and maintenance
# ══════════════════════════════════════════════════════
@doc("2026-08-24", "json", "disinfection_record_RO-H1.json")
def _():
    write_json("disinfection_record_RO-H1.json", {
        "plant": "RO-H1",
        "centre": "Nephrova Hadapsar",
        "records": [
            {"date": "2026-07-02", "type": "chemical disinfection", "done_by": person("senior_tech")},
            {"date": "2026-08-02", "type": "chemical disinfection", "done_by": None, "status": "missed"},
            {"date": "2026-08-22", "type": "chemical and heat disinfection", "done_by": person("bme_tech")},
        ],
        "resample": {"date": "2026-08-23", "tests": ["bacteria", "endotoxin"]},
    })


@doc("2026-08-25", "json", "water_test_results_2026.jsonl")
def _():
    recs = []
    months = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    base = {"RO-K1": (8, 0.03), "RO-H1": (12, 0.05), "RO-P1": (5, 0.02)}
    for m in months:
        for plant, (b, e) in base.items():
            recs.append({"month": m, "plant": plant, "bacteria_cfu_ml": b, "endotoxin_eu_ml": e, "within_limits": True})
    recs.append({"month": "2026-08", "plant": "RO-K1", "bacteria_cfu_ml": 9, "endotoxin_eu_ml": 0.03, "within_limits": True})
    recs.append({"month": "2026-08", "plant": "RO-P1", "bacteria_cfu_ml": 4, "endotoxin_eu_ml": 0.02, "within_limits": True})
    recs.append({"month": "2026-08", "plant": "RO-H1", "bacteria_cfu_ml": R["bacteria"],
                 "endotoxin_eu_ml": R["endotoxin"], "within_limits": False})
    write_jsonl("water_test_results_2026.jsonl", recs)


@doc("2026-08-26", "pdf", "Water_Lab_Report_RO-H1_Resample.pdf")
def _():
    write_pdf("Water_Lab_Report_RO-H1_Resample.pdf", f"""<h1>City Diagnostic Laboratory — Dialysis Water Report (Resample)</h1>
<p>Client: {C.COMPANY}, Hadapsar centre. Sample: RO-H1 product water, end of loop. Collected {R['resampled']}. Reported {R['resample_result_date']}.</p>
{html_table(['Test', 'Result', 'Action level', 'Status'], [
    ['Bacteria culture', f"{R['bacteria_after']} CFU/mL", f"{W['bacteria_action']} CFU/mL", 'Within limit'],
    ['Endotoxin', f"{R['endotoxin_after']} EU/mL", f"{W['endotoxin_action']} EU/mL", 'Within limit'],
])}
<p>Both results for RO-H1 are below the action levels. The water is suitable for dialysis.</p>""")


@doc("2026-08-27", "markdown", "RCA_RO-H1_Endotoxin.md")
def _():
    write_text("markdown", "RCA_RO-H1_Endotoxin.md", f"""
# Root Cause Analysis — Hadapsar Water Plant Endotoxin Result

Lead: {person('bme_lead')}. Team: {person('mgr_hdp')}, {person('senior_tech')}, {person('infection')}. Incident: {R['incident']}.

## Problem

- RO-H1 showed endotoxin exceedance of {R['endotoxin']} EU/mL on the sample of {R['sampled']}.

## Root cause

- The monthly disinfection of RO-H1 was missed in August: only one technician at Hadapsar was trained to do it, and he was on leave.

## Corrective actions

| Action | Owner | Status |
|---|---|---|
| Train a second technician at each centre in water plant disinfection | {person('bme_lead')} | Due 30 September 2026 |
| Add the disinfection due date to the centre manager's weekly checklist | {person('mgr_hdp')} | Done |
| Disinfect and resample RO-H1 | {person('bme_tech')} | Done, resample result {R['endotoxin_after']} EU/mL |

Full service at Hadapsar resumed on {R['resumed']}.
""")


@doc("2026-08-28", "excel", "PM_Schedule_2026.xlsx")
def _():
    rows = [["Centre", "Machines", "First half", "Second half", "Second half dates"]]
    for code, (name, *_rest) in C.CENTRES.items():
        first, second = C.PM_MONTHS[code]
        rows.append([name, len(C.machines(code)), first, second, C.PM_DATES_2026_H2[code]])
    write_xlsx("PM_Schedule_2026.xlsx", {
        "Dialysis machines": rows,
        "Water plants": [["Plant", "Disinfection", "Water test"], ["RO-K1", "Monthly", "Monthly"],
                         ["RO-H1", "Monthly", "Monthly"], ["RO-P1", "Monthly", "Monthly"]],
    })


@doc("2026-08-29", "text", "shift_log_KTH_2026-08-29.txt")
def _():
    write_text("text", "shift_log_KTH_2026-08-29.txt", f"""
SHIFT LOG — Nephrova Kothrud
Date: 29 August 2026    Shift: Morning    In charge: {person('mgr_kth')}

06:30  Six-monthly preventive maintenance of the dialysis machines continues (second day), done by {person('bme_tech')}.
09:00  The first six machines were completed yesterday; the remaining six are done today.
13:30  Preventive maintenance of all 12 Kothrud machines complete. All passed safety checks.
14:30  Extra evening shift for Hadapsar patients ended on 26 August; normal schedule from today.
""")


@doc("2026-08-30", "word", "Notice_Hepatitis_B_Vaccination_Drive.docx")
def _():
    write_docx("Notice_Hepatitis_B_Vaccination_Drive.docx", "Notice — Staff Hepatitis B Vaccination Drive", [
        ("p", f"From: {person('hr')}, HR Manager, and {person('infection')}, Infection Control Nurse. Date: 30 August 2026."),
        ("p", f"A hepatitis B vaccination drive for staff will be held on {HB['date']} at Nephrova Kothrud from 10:00 to 16:00."),
        ("p", f"{HB['eligible']} staff members whose antibody level is below the protective level are asked to attend."),
        ("p", "Staff who cannot attend should contact HR to book a slot at the next drive."),
    ])


@doc("2026-08-31", "csv", "monthly_sessions_aug_2026.csv")
def _():
    rows = []
    for code, (name, *_rest) in C.CENTRES.items():
        total = C.SESSIONS["Aug"][code]
        split = {p: round(total * share) for p, share in C.PAYER_MIX.items()}
        split["Self-pay"] = total - split["PM-JAY"] - split["Insurance"]
        rows.append([name, total, split["PM-JAY"], split["Self-pay"], split["Insurance"]])
    write_csv("monthly_sessions_aug_2026.csv", ["centre", "sessions", "pm_jay", "self_pay", "insurance"], rows)


# ══════════════════════════════════════════════════════
# Week 4 — 31 August to 6 September: finance, Pimpri infection
# ══════════════════════════════════════════════════════
def finance_sheet(month: str) -> dict[str, list[list]]:
    revenue = [["Centre", "Sessions", "Revenue (INR lakh)"]]
    for code, (name, *_rest) in C.CENTRES.items():
        revenue.append([name, C.SESSIONS[month][code], C.revenue_lakh(month, code)])
    revenue.append(["Total", C.month_sessions(month), C.revenue_lakh(month)])
    consumables = round(C.month_sessions(month) * C.CONSUMABLES_PER_SESSION / 1e5, 2)
    pnl = [["Line", "INR lakh"], ["Revenue", C.revenue_lakh(month)], ["Consumables", consumables],
           ["Staff cost", C.STAFF_COST_LAKH], ["Other operating cost", C.OTHER_OPEX_LAKH],
           ["EBITDA", C.ebitda_lakh(month)]]
    outstanding, claims = C.RECEIVABLES[month]
    return {"Revenue": revenue, "P&L": pnl,
            "PM-JAY receivables": [["Outstanding (INR lakh)", outstanding], ["Claims older than 30 days", claims]]}


@doc("2026-09-01", "excel", "Finance_MIS_Aug_2026.xlsx")
def _():
    write_xlsx("Finance_MIS_Aug_2026.xlsx", finance_sheet("Aug"))


@doc("2026-09-02", "text", "vaccination_drive_summary_2026-09-02.txt")
def _():
    write_text("text", "vaccination_drive_summary_2026-09-02.txt", f"""
HEPATITIS B VACCINATION DRIVE — SUMMARY
Date: {HB['date']}    Venue: Nephrova Kothrud    Reported by: {person('infection')}

Staff asked to attend: {HB['eligible']}
Staff vaccinated today: {HB['vaccinated']}
Staff to be vaccinated at the next drive: {HB['eligible'] - HB['vaccinated']}
No adverse reactions were reported.
""")


@doc("2026-09-03", "word", "Infection_Report_Case1_PMP-0412.docx")
def _():
    pid, day = I["cases"][0]
    write_docx("Infection_Report_Case1_PMP-0412.docx", "Infection Report — Pimpri, Case 1", [
        ("p", f"Patient ID: {pid} (de-identified). Centre: Nephrova Pimpri. Date identified: {day}. Reported by {person('infection')}."),
        ("h", "Clinical summary"),
        ("p", "The patient dialyses through a tunnelled catheter and developed fever with chills at the start of dialysis."),
        ("p", "Blood cultures from the catheter and a peripheral vein grew the same organism."),
        ("h", "Diagnosis and treatment"),
        ("p", "The catheter-related bloodstream infection was treated with vancomycin given after each dialysis session for three weeks."),
        ("p", "The patient was reviewed by the nephrologist and continued dialysis at Pimpri."),
    ])


@doc("2026-09-04", "powerpoint", "August_2026_Operations_Review.pptx")
def _():
    s = C.SESSIONS["Aug"]
    write_pptx("August_2026_Operations_Review.pptx", [
        ("August 2026 Operations Review", [C.COMPANY, f"Presented by {person('ceo')}, 4 September 2026"]),
        ("Sessions", [f"Kothrud: {s['KTH']} (including {R['transferred_sessions']} Hadapsar sessions)",
                      f"Hadapsar: {s['HDP']}", f"Pimpri: {s['PMP']}", f"Total: {C.month_sessions('Aug')}"]),
        ("Finance", [f"Revenue: {inr_lakh(C.revenue_lakh('Aug'))}", f"EBITDA: {inr_lakh(C.ebitda_lakh('Aug'))}"]),
        ("Events", [f"Hadapsar water plant out of use {R['transfer_window']}; service resumed {R['resumed']}",
                    f"Kothrud machine maintenance completed {C.PM_DATES_2026_H2['KTH']}"]),
    ])


@doc("2026-09-05", "markdown", "Hand_Hygiene_Policy.md")
def _():
    write_text("markdown", "Hand_Hygiene_Policy.md", f"""
# Hand Hygiene Policy

Owner: {person('infection')}. Part of the Infection Control Policy.

## The five moments

1. Before touching a patient
2. Before a clean or aseptic procedure (needling, catheter connection)
3. After body fluid exposure risk
4. After touching a patient
5. After touching the patient's surroundings, including the dialysis machine

## Method

Use alcohol hand rub for 20 to 30 seconds, or soap and water for 40 to 60 seconds when hands are visibly soiled.

## Audit

Each centre is audited every month by direct observation of at least 30 opportunities. Target compliance: {I['target']} percent.
""")


@doc("2026-09-06", "json", "staff_roster_week37.json")
def _():
    write_json("staff_roster_week37.json", {
        "week": "7 to 13 September 2026",
        "centres": [
            {"centre": "Nephrova Kothrud", "shifts": ["06:30-14:30", "14:00-22:00"], "nurses_per_shift": 4, "technicians_per_shift": 5},
            {"centre": "Nephrova Hadapsar", "shifts": ["06:30-14:30", "14:00-22:00"], "nurses_per_shift": 3, "technicians_per_shift": 5},
            {"centre": "Nephrova Pimpri", "shifts": ["06:30-14:30", "14:00-22:00"], "nurses_per_shift": 3, "technicians_per_shift": 3},
        ],
        "on_call_nephrologist": person("medical"),
        "on_call_biomedical": person("bme_tech"),
    })


# ══════════════════════════════════════════════════════
# Week 5 — 7 to 13 September: Pimpri power, second infection
# ══════════════════════════════════════════════════════
@doc("2026-09-07", "text", "shift_log_PMP_2026-09-07.txt")
def _():
    write_text("text", "shift_log_PMP_2026-09-07.txt", f"""
SHIFT LOG — Nephrova Pimpri
Date: {G['date']}    Shift: Afternoon (14:00 to 22:00)    In charge: {person('mgr_pmp')}

14:10  Mains power failure in the area.
14:10  UPS-P1 carried all 8 dialysis machines; no treatment was interrupted.
14:11  GEN-P1 started after {G['start_delay_s']} seconds, slower than the {G['target_s']} second target.
15:25  Mains power restored. Generator stopped.
16:00  Incident {G['incident']} raised and biomedical engineering informed.
""")


@doc("2026-09-08", "pdf", "Generator_Load_Test_GEN-P1.pdf")
def _():
    write_pdf("Generator_Load_Test_GEN-P1.pdf", f"""<h1>Generator Service and Load Test Report</h1>
<p>Equipment: GEN-P1 (125 kVA diesel generator, Nephrova Pimpri). Date: {G['fixed']}. Engineer: {person('bme_lead')}.</p>
<h2>Complaint</h2>
<p>GEN-P1 took {G['start_delay_s']} seconds to start during the mains outage of {G['date']}.</p>
<h2>Finding</h2>
<p>The starter battery of GEN-P1 was weak (11.2 V under cranking load).</p>
<h2>Work done</h2>
<p>GEN-P1 received a battery replacement and a load test.</p>
<p>In the load test GEN-P1 started in {G['test_start_s']} seconds and ran for 2 hours at 70 percent load without fault.</p>""")


@doc("2026-09-10", "markdown", "Biomedical_Waste_Management_SOP.md")
def _():
    write_text("markdown", "Biomedical_Waste_Management_SOP.md", f"""
# SOP — Bio-Medical Waste Management

Owner: {person('quality')}. Complies with the Bio-Medical Waste Management Rules 2016. Authorisation valid until {C.BMW_AUTH_VALID}.

## Colour coding

| Bag or container | What goes in |
|---|---|
| Yellow | Dialysers, blood lines, soiled dressings |
| Red | Contaminated plastic such as tubing and gloves |
| White (puncture proof) | Needles and fistula needles |
| Blue | Glass vials and ampoules |

## Rules

- Segregate at the dialysis station, never later.
- A colour-coding chart must be displayed at every point where waste is collected, including store rooms.
- Waste is handed to the authorised common treatment facility every 24 hours and the quantity is recorded.
""")


@doc("2026-09-11", "excel", "PMJAY_Claims_Ageing_Sep2026.xlsx")
def _():
    write_xlsx("PMJAY_Claims_Ageing_Sep2026.xlsx", {
        "Ageing": [["Age of claim", "Claims", "Amount (INR lakh)"], ["0–30 days", 214, 9.8],
                   ["31–60 days", 71, 17.1], ["61–90 days", 29, 6.9], ["More than 90 days", 12, 3.2]],
        "Notes": [["Prepared by", person("finance")], ["As of", "10 September 2026"],
                  ["Action", "Resubmit claims rejected for missing session sheets"]],
    })


@doc("2026-09-12", "word", "Infection_Report_Case2_PMP-0388.docx")
def _():
    pid, day = I["cases"][1]
    write_docx("Infection_Report_Case2_PMP-0388.docx", "Infection Report — Pimpri, Case 2", [
        ("p", f"Patient ID: {pid} (de-identified). Centre: Nephrova Pimpri. Date identified: {day}. Reported by {person('infection')}."),
        ("h", "Clinical summary"),
        ("p", "The patient dialyses through a tunnelled catheter and had fever after the second hour of dialysis."),
        ("h", "Diagnosis and treatment"),
        ("p", "The catheter-related bloodstream infection was treated with vancomycin, and the catheter was exchanged over a guidewire."),
        ("h", "Note"),
        ("p", f"This is the second case at Pimpri in September. An infection control audit of Pimpri is scheduled for {I['audit_date']}."),
    ])


@doc("2026-09-13", "text", "email_infection_alert_PMP.txt")
def _():
    write_text("text", "email_infection_alert_PMP.txt", f"""
From: {person('infection')} <pooja.shinde@nephrova.example>
To: {person('medical')}, {person('nursing')}, {person('mgr_pmp')}
Date: 13 September 2026
Subject: Two catheter infections at Pimpri this month

Dear all,

Pimpri has had two catheter-related bloodstream infections this month (patients PMP-0412 and PMP-0388).
The usual rate across our centres is below one case a month. I will audit hand hygiene and catheter care at Pimpri on {I['audit_date']}.
Until then, please make sure every catheter connection uses the full care bundle.

Regards,
{person('infection')}
Infection Control Nurse
""")


# ══════════════════════════════════════════════════════
# Week 6 — 14 to 20 September: audit and training
# ══════════════════════════════════════════════════════
@doc("2026-09-15", "pdf", "Infection_Control_Audit_PMP_Sep2026.pdf")
def _():
    write_pdf("Infection_Control_Audit_PMP_Sep2026.pdf", f"""<h1>Infection Control Audit — Nephrova Pimpri</h1>
<p>Date: {I['audit_date']}. Auditor: {person('infection')}. Trigger: two catheter infections in September.</p>
{html_table(['Measure', 'Result', 'Target'], [
    ['Hand hygiene compliance', f"{I['hand_hygiene']} percent", f"{I['target']} percent"],
    ['Catheter care bundle compliance', f"{I['bundle']} percent", f"{I['target']} percent"],
])}
<h2>Main gaps</h2>
<p>Hand rub was often skipped between touching the machine and connecting the catheter.</p>
<p>Sterile caps were reused on two of ten observed connections.</p>
<p>Hand hygiene audits at Pimpri had been done quarterly instead of monthly.</p>
<h2>Actions</h2>
<p>Retrain all Pimpri nurses and technicians during {I['training']}, and re-audit on {I['reaudit_date']}.</p>
<p>The September infection rate at Pimpri is {I['rate']} per 1,000 catheter days ({len(I['cases'])} cases in {I['catheter_days']} catheter days).</p>""")


@doc("2026-09-16", "powerpoint", "Pimpri_Infection_Action_Plan.pptx")
def _():
    write_pptx("Pimpri_Infection_Action_Plan.pptx", [
        ("Pimpri Infection Action Plan", [f"Prepared by {person('infection')} and {person('nursing')}, 16 September 2026"]),
        ("What we found", [f"Hand hygiene {I['hand_hygiene']} percent against a {I['target']} percent target",
                           f"Catheter care bundle {I['bundle']} percent"]),
        ("What we will do", [f"Training for all {I['trained_staff']} Pimpri clinical staff, {I['training']}",
                             "Monthly hand hygiene audits from now on", "New sterile caps for every connection"]),
        ("How we will check", [f"Re-audit on {I['reaudit_date']}", "Infection rate reviewed monthly by the Quality Committee"]),
    ])


@doc("2026-09-17", "csv", "training_attendance_hand_hygiene_sep2026.csv")
def _():
    names = ["Shalini Gaikwad", "Prakash Jadhav", "Meena Kamble", "Rohit Salunkhe", "Kavita Pawar",
             "Sunil Shinde", "Nisha Kadam", "Ajay Mane", "Lata Bhosale", "Vijay Kale", "Sapna More",
             "Deepak Chavan", "Rekha Shirke", "Anil Thorat", "Pallavi Nikam", "Santosh Gawade",
             "Asha Lokhande", "Manoj Patole", "Swati Dhumal", "Ramesh Kokate", "Jyoti Sawant", "Kishor Lad"]
    days = ["2026-09-17", "2026-09-18", "2026-09-19"]
    rows = [[n, "Nurse" if i % 3 == 0 else "Dialysis technician", "Nephrova Pimpri", days[i % 3], "Attended"]
            for i, n in enumerate(names)]
    assert len(rows) == I["trained_staff"]
    write_csv("training_attendance_hand_hygiene_sep2026.csv", ["name", "role", "centre", "date", "status"], rows)


@doc("2026-09-18", "markdown", "Catheter_Care_Bundle.md")
def _():
    write_text("markdown", "Catheter_Care_Bundle.md", f"""
# Catheter Care Bundle

Owner: {person('nursing')}. Every step is required at every catheter connection and disconnection.

1. Hand hygiene, then clean gloves.
2. Scrub each catheter hub with chlorhexidine for 15 seconds and let it dry.
3. Connect using a no-touch technique.
4. Use a new sterile cap at the end of every session. Never reuse caps.
5. Check the exit site and dressing; change the dressing if wet or loose.
6. Record the bundle on the treatment chart.

Compliance is audited monthly with hand hygiene. Target: {I['target']} percent.
""")


@doc("2026-09-19", "word", "Quality_Committee_Minutes_Sep2026.docx")
def _():
    write_docx("Quality_Committee_Minutes_Sep2026.docx", "Quality Committee — Minutes, 19 September 2026", [
        ("p", f"Chair: {person('medical')}. Present: {person('ceo')}, {person('nursing')}, {person('quality')}, "
              f"{person('infection')}, {person('bme_lead')}."),
        ("h", "1. Dialysis water"),
        ("p", f"The Hadapsar water incident ({R['incident']}) is closed. Second technicians are being trained at all centres."),
        ("h", "2. Infections at Pimpri"),
        ("p", f"Two catheter infections at Pimpri in September. Audit found hand hygiene at {I['hand_hygiene']} percent. "
              f"Training is under way and a re-audit is due on {I['reaudit_date']}."),
        ("h", "3. NABH surveillance assessment"),
        ("p", f"The assessment is on {N['date']}. {person('quality')} will run a document check on 22 September."),
        ("h", "4. Equipment"),
        ("p", f"Hadapsar machine maintenance was completed on {C.PM_DATES_2026_H2['HDP']}."),
    ])


@doc("2026-09-20", "excel", "Consumables_Stock_Sep2026.xlsx")
def _():
    write_xlsx("Consumables_Stock_Sep2026.xlsx", {
        "Stock": [["Item", "Kothrud", "Hadapsar", "Pimpri", "Days of cover"],
                  ["Dialysers, high flux", 820, 690, 540, 21], ["Blood line sets", 790, 660, 510, 20],
                  ["Acid concentrate, 5 litre", 410, 350, 270, 18], ["Bicarbonate cartridges", 600, 520, 400, 22],
                  ["Heparin vials", 950, 800, 620, 25], ["Catheter lock caps", 300, 240, 120, 9]],
        "Notes": [["Reorder rule", "Raise an order when days of cover fall below 14"],
                  ["Open order", "Catheter lock caps ordered on 9 September 2026"]],
    })


# ══════════════════════════════════════════════════════
# Week 7 — 21 to 27 September: NABH assessment
# ══════════════════════════════════════════════════════
@doc("2026-09-21", "powerpoint", "Nursing_Quality_Indicators_Aug2026.pptx")
def _():
    write_pptx("Nursing_Quality_Indicators_Aug2026.pptx", [
        ("Nursing Quality Indicators — August 2026", [f"Prepared by {person('nursing')}"]),
        ("Treatment adequacy", ["Patients with Kt/V of 1.2 or more: 91 percent", "Missed sessions: 1.8 percent"]),
        ("Complications during dialysis", ["Hypotension episodes: 3.1 per 100 sessions",
                                           "Muscle cramps: 2.4 per 100 sessions"]),
        ("Anaemia", ["Patients with haemoglobin at 10 g/dL or more: 74 percent"]),
        ("Management", ["Hypotension during dialysis was treated with normal saline as per protocol."]),
    ])


@doc("2026-09-22", "json", "nabh_document_checklist.json")
def _():
    write_json("nabh_document_checklist.json", {
        "prepared_by": person("quality"),
        "date": "2026-09-22",
        "items": [
            {"document": "Dialysis water test reports, last 12 months", "status": "Available"},
            {"document": "Water plant disinfection logs", "status": "Gap: August entry missing at Hadapsar"},
            {"document": "Machine preventive maintenance records", "status": "Available"},
            {"document": "Hand hygiene audit reports", "status": "Gap: Pimpri audits were quarterly"},
            {"document": "Bio-medical waste records and authorisation", "status": "Available"},
            {"document": "Staff hepatitis B immunisation records", "status": "Available"},
            {"document": "Patient consent forms", "status": "Available"},
        ],
    })


@doc("2026-09-23", "powerpoint", "NABH_Readiness_Briefing.pptx")
def _():
    write_pptx("NABH_Readiness_Briefing.pptx", [
        ("NABH Surveillance Assessment — Readiness Briefing", [f"{person('quality')}, 23 September 2026"]),
        ("Tomorrow", [f"Assessor: {N['assessor']}", "All three centres will be visited", "Start at Kothrud at 09:00"]),
        ("Known gaps", ["August disinfection log entry missing at Hadapsar", "Pimpri hand hygiene audits were quarterly"]),
        ("Reminders", ["Keep logbooks at the station", "Answer only what is asked; show the record"]),
    ])


@doc("2026-09-24", "pdf", "NABH_Surveillance_Assessment_Report.pdf")
def _():
    write_pdf("NABH_Surveillance_Assessment_Report.pdf", f"""<h1>NABH Surveillance Assessment Report</h1>
<p>Organisation: {C.COMPANY} (three dialysis centres, Pune). Date: {N['date']}. Assessor: {N['assessor']}.</p>
<h2>Summary</h2>
<p>Major non-conformities: {N['majors']}. Minor non-conformities: {N['minors']}. Accreditation continues.</p>
<h2>Minor non-conformities</h2>
{html_table(['No.', 'Centre', 'Finding'], [list(nc) for nc in N['ncs']])}
<p>Corrective action evidence is due by {N['closure_due']}.</p>
<h2>Good practice</h2>
<p>The Hadapsar water incident was handled well: dialysis was moved to Kothrud and resumed only after a clean resample.</p>""")


@doc("2026-09-25", "csv", "nabh_corrective_action_tracker.csv")
def _():
    actions = {
        "NC-1": ("Add disinfection due dates to the weekly centre checklist; second technician trained", person("mgr_hdp"), "Done"),
        "NC-2": ("Monthly hand hygiene audits at Pimpri from September", person("infection"), "Done"),
        "NC-3": ("Display bio-medical waste colour-coding chart in the Kothrud store room", person("mgr_kth"), "Open"),
    }
    write_csv("nabh_corrective_action_tracker.csv", ["nc", "centre", "finding", "action", "owner", "due", "status"],
              [[nc, centre, finding, *actions[nc][:2], N["closure_due"], actions[nc][2]] for nc, centre, finding in N["ncs"]])


@doc("2026-09-26", "markdown", "Patient_Privacy_Notice.md")
def _():
    write_text("markdown", "Patient_Privacy_Notice.md", f"""
# Patient Privacy Notice

{C.COMPANY} protects the personal and health data of its patients as required by the DPDP Act 2023.

## What we collect

Name, contact details, identity and insurance or PM-JAY details, medical history, treatment records and test results.

## Why we use it

To provide dialysis, to coordinate care with your doctors, and to process payment with your insurer or the PM-JAY scheme.

## Your rights

You can ask to see your records, correct them, or withdraw consent for uses other than your treatment.
Contact the Quality Manager, {person('quality')}, at privacy@nephrova.example.

## How long we keep it

Treatment records are kept for at least 3 years after your last visit, or longer if the law requires.
""")


@doc("2026-09-27", "text", "shift_log_HDP_2026-09-27.txt")
def _():
    write_text("text", "shift_log_HDP_2026-09-27.txt", f"""
SHIFT LOG — Nephrova Hadapsar
Date: 27 September 2026    Shift: Morning    In charge: {person('mgr_hdp')}

06:30  RO-H1 product water conductivity normal at the start of the day.
07:00  36 sessions scheduled across 10 machines.
10:15  One patient had low blood pressure in the third hour; given saline bolus and recovered.
12:00  Monthly water sample from RO-H1 sent to the laboratory.
14:30  All sessions completed.
""")


# ══════════════════════════════════════════════════════
# Week 8 — 28 September to 4 October: month end
# ══════════════════════════════════════════════════════
@doc("2026-09-28", "word", "HR_Leave_and_Attendance_Policy.docx")
def _():
    write_docx("HR_Leave_and_Attendance_Policy.docx", "Leave and Attendance Policy", [
        ("p", f"Owner: {person('hr')}, HR Manager. Applies to all {C.TOTAL_STAFF} employees."),
        ("h", "Leave entitlement per year"),
        ("t", ["Leave type", "Days"], [["Earned leave", 15], ["Casual leave", 7], ["Sick leave", 10]]),
        ("h", "Shift cover"),
        ("p", "Dialysis runs every day except Sunday. Leave for nurses and technicians is approved only when the shift stays covered."),
        ("p", "Every critical task, including water plant disinfection, must have a named backup person at each centre."),
        ("h", "Attendance"),
        ("p", "Staff mark attendance with the biometric reader at the start and end of every shift."),
    ])


@doc("2026-09-29", "excel", "Staff_Strength_Sep2026.xlsx")
def _():
    write_xlsx("Staff_Strength_Sep2026.xlsx", {
        "Headcount": [["Role", "Count"]] + [[r, n] for r, n in C.STAFF.items()] + [["Total", C.TOTAL_STAFF]],
        "By centre": [["Centre", "Nurses", "Dialysis technicians"], ["Kothrud", 9, 12],
                      ["Hadapsar", 7, 10], ["Pimpri", 6, 8]],
    })


@doc("2026-09-30", "pdf", "Infection_Control_Reaudit_PMP_Sep30.pdf")
def _():
    write_pdf("Infection_Control_Reaudit_PMP_Sep30.pdf", f"""<h1>Infection Control Re-audit — Nephrova Pimpri</h1>
<p>Date: {I['reaudit_date']}. Auditor: {person('infection')}.</p>
{html_table(['Measure', 'First audit (15 Sep)', 'Re-audit (30 Sep)', 'Target'], [
    ['Hand hygiene compliance', f"{I['hand_hygiene']} percent", f"{I['hand_hygiene_after']} percent", f"{I['target']} percent"],
    ['Catheter care bundle compliance', f"{I['bundle']} percent", f"{I['bundle_after']} percent", f"{I['target']} percent"],
])}
<p>Both measures are now above target. No new catheter infections at Pimpri since 12 September 2026.</p>""")


@doc("2026-10-01", "csv", "monthly_sessions_sep_2026.csv")
def _():
    rows = []
    for code, (name, *_rest) in C.CENTRES.items():
        total = C.SESSIONS["Sep"][code]
        split = {p: round(total * share) for p, share in C.PAYER_MIX.items()}
        split["Self-pay"] = total - split["PM-JAY"] - split["Insurance"]
        rows.append([name, total, split["PM-JAY"], split["Self-pay"], split["Insurance"]])
    write_csv("monthly_sessions_sep_2026.csv", ["centre", "sessions", "pm_jay", "self_pay", "insurance"], rows)


@doc("2026-10-02", "json", "kpi_dashboard_q3_2026.json")
def _():
    write_json("kpi_dashboard_q3_2026.json", {
        "company": C.COMPANY,
        "quarter": "Q3 2026 (July to September)",
        "sessions": {m: C.month_sessions(m) for m in ("Jul", "Aug", "Sep")},
        "revenue_inr_lakh": {m: C.revenue_lakh(m) for m in ("Jul", "Aug", "Sep")},
        "ebitda_inr_lakh": {m: C.ebitda_lakh(m) for m in ("Jul", "Aug", "Sep")},
        "active_patients": C.TOTAL_PATIENTS,
        "dialysis_machines": C.TOTAL_MACHINES,
        "infection_rate_pimpri_sep_per_1000_catheter_days": I["rate"],
        "water_results_above_limit": 1,
        "pm_jay_outstanding_inr_lakh": C.RECEIVABLES["Sep"][0],
    })


@doc("2026-10-03", "excel", "Finance_MIS_Sep_2026.xlsx")
def _():
    write_xlsx("Finance_MIS_Sep_2026.xlsx", finance_sheet("Sep"))


@doc("2026-10-04", "powerpoint", "September_2026_Operations_Review.pptx")
def _():
    s = C.SESSIONS["Sep"]
    q3 = sum(C.month_sessions(m) for m in ("Jul", "Aug", "Sep"))
    write_pptx("September_2026_Operations_Review.pptx", [
        ("September 2026 Operations Review", [C.COMPANY, f"Presented by {person('ceo')}, 4 October 2026"]),
        ("Sessions", [f"Kothrud: {s['KTH']}", f"Hadapsar: {s['HDP']}", f"Pimpri: {s['PMP']}",
                      f"Total: {C.month_sessions('Sep')}; Q3 total: {q3}"]),
        ("Finance", [f"Revenue: {inr_lakh(C.revenue_lakh('Sep'))}", f"EBITDA: {inr_lakh(C.ebitda_lakh('Sep'))}",
                     f"PM-JAY outstanding: INR {C.RECEIVABLES['Sep'][0]} lakh"]),
        ("Quality", [f"NABH surveillance: {N['majors']} major, {N['minors']} minor non-conformities",
                     f"Pimpri hand hygiene back to {I['hand_hygiene_after']} percent"]),
    ])


# ══════════════════════════════════════════════════════
# Week 9 — 5 to 8 October: board and close-out
# ══════════════════════════════════════════════════════
@doc("2026-10-05", "word", "Board_Note_Q3_2026.docx")
def _():
    q3_rev = round(sum(C.revenue_lakh(m) for m in ("Jul", "Aug", "Sep")), 2)
    q3_ebitda = round(sum(C.ebitda_lakh(m) for m in ("Jul", "Aug", "Sep")), 2)
    write_docx("Board_Note_Q3_2026.docx", "Board Note — Q3 2026", [
        ("p", f"From: {person('ceo')}, CEO. Prepared with {person('finance')}, Finance Head. Date: 5 October 2026."),
        ("h", "Business"),
        ("p", f"{C.SHORT} runs {C.TOTAL_MACHINES} dialysis machines at three Pune centres and treats {C.TOTAL_PATIENTS} active patients."),
        ("p", f"Q3 revenue was {inr_lakh(q3_rev)} and Q3 EBITDA was {inr_lakh(q3_ebitda)}."),
        ("h", "Risks"),
        ("p", f"PM-JAY dues rose to INR {C.RECEIVABLES['Sep'][0]} lakh with {C.RECEIVABLES['Sep'][1]} claims older than 30 days."),
        ("p", "Single-person dependence for critical tasks caused the Hadapsar water incident; backups are now named for every centre."),
        ("h", "Quality"),
        ("p", f"NABH accreditation continues after the surveillance assessment of {N['date']} with {N['minors']} minor findings."),
    ])


@doc("2026-10-06", "markdown", "Lessons_Learned_Q3_2026.md")
def _():
    write_text("markdown", "Lessons_Learned_Q3_2026.md", f"""
# Lessons Learned — Q3 2026

Compiled by {person('quality')} for the Quality Committee.

## 1. Dialysis machine alarms (August, Kothrud)

- HD-K04 gave {K['alarm_total']} conductivity alarms in three days before it was repaired.
- The conductivity alarm on HD-K04 was cleared by a conductivity cell replacement.
- Lesson: take a machine out of service after the second unexplained alarm, not the sixth.

## 2. Dialysis water (August, Hadapsar)

- RO-H1 showed endotoxin exceedance after one missed monthly disinfection.
- Lesson: every critical task needs a trained backup person at each centre.

## 3. Power (September, Pimpri)

- GEN-P1 started late because of a weak starter battery; the UPS covered the gap.
- Lesson: test generator starter batteries every month.

## 4. Catheter infections (September, Pimpri)

- Two catheter-related bloodstream infections followed a drop in hand hygiene to {I['hand_hygiene']} percent.
- Lesson: monthly audits catch slipping practice before patients are harmed.
""")


@doc("2026-10-07", "text", "email_NABH_closure_status.txt")
def _():
    write_text("text", "email_NABH_closure_status.txt", f"""
From: {person('quality')} <kiran.bhosale@nephrova.example>
To: {person('ceo')} <ritu.malhotra@nephrova.example>
Date: 7 October 2026
Subject: NABH corrective actions — status

Ritu,

Two of the three NABH findings are closed with evidence (Hadapsar disinfection checklist and Pimpri monthly audits).
The colour-coding chart for the Kothrud store room is printed and will be put up this week.
We will send the evidence pack well before the {N['closure_due']} deadline.

Regards,
{person('quality')}
""")


@doc("2026-10-08", "pdf", "Q3_2026_Quality_Report.pdf")
def _():
    write_pdf("Q3_2026_Quality_Report.pdf", f"""<h1>Q3 2026 Quality Report</h1>
<p>{C.COMPANY}. Prepared by {person('quality')} on 8 October 2026.</p>
<h2>Indicators</h2>
{html_table(['Indicator', 'Q3 2026'], [
    ['Dialysis sessions', sum(C.month_sessions(m) for m in ('Jul', 'Aug', 'Sep'))],
    ['Water results above limit', '1 (Hadapsar, August)'],
    ['Catheter infections', f"{len(I['cases'])} (Pimpri, September)"],
    ['Staff vaccinated against hepatitis B in Q3', HB['vaccinated']],
    ['NABH findings', f"{N['majors']} major, {N['minors']} minor"],
])}
<h2>Status</h2>
<p>All incidents of the quarter are closed. One NABH corrective action remains open and is due by {N['closure_due']}.</p>""")


# ══════════════════════════════════════════════════════
# Company policies — HR and finance (published 1–9 August, two in September)
# ══════════════════════════════════════════════════════
H = C.HR
fmt_inr = lambda v: f"INR {v:,}"  # noqa: E731


@doc("2026-08-01", "markdown", "HR_Code_of_Conduct.md")
def _():
    write_text("markdown", "HR_Code_of_Conduct.md", f"""
# Code of Conduct

{C.COMPANY}. Owner: {person('hr')}, HR Manager. Approved by {person('ceo')}, CEO. Applies to all employees and contract staff.

## Patients first

- Treat every patient with dignity, whatever their payment scheme, religion, caste or illness.
- Never share patient information outside the care team. Patient data is handled as described in the Patient Privacy Notice.

## Honesty

- Record treatment, readings and times truthfully. Changing a record after the fact needs a dated correction, never an overwrite.
- Do not accept gifts above INR 1,000 in value from patients, families or suppliers. Report any offer to HR.

## Safety

- Report every incident, near miss or equipment fault the same day.
- No one may be punished for reporting a safety concern in good faith.

## Breaches

Breaches are handled under the disciplinary procedure: verbal warning, written warning, then termination. Fraud,
violence and harassment can lead to immediate termination.
""")


@doc("2026-08-02", "word", "HR_Recruitment_and_Onboarding_Policy.docx")
def _():
    write_docx("HR_Recruitment_and_Onboarding_Policy.docx", "Recruitment and Onboarding Policy", [
        ("p", f"Owner: {person('hr')}, HR Manager. Effective 2 August 2026."),
        ("h", "Hiring"),
        ("p", "Every vacancy is approved by the CEO before it is advertised. Clinical roles are interviewed by the Chief Nursing Officer and one Centre Manager."),
        ("p", "Nurses must hold a valid nursing council registration. Dialysis technicians must hold a recognised dialysis technology qualification."),
        ("p", f"Employees who refer a candidate who is hired and completes probation receive a referral bonus of {fmt_inr(H['referral_bonus_inr'])}."),
        ("h", "Before the first shift"),
        ("p", "Pre-employment health check, including hepatitis B antibody level. Staff who are not immune are vaccinated free of charge."),
        ("p", "Safety and infection control induction with the Infection Control Nurse."),
        ("h", "Probation"),
        ("p", f"All new employees serve a probation of {H['probation_months']} months. Notice during probation is 15 days on either side."),
    ])


@doc("2026-08-03", "pdf", "HR_Compensation_and_Benefits_Policy.pdf")
def _():
    write_pdf("HR_Compensation_and_Benefits_Policy.pdf", f"""<h1>Compensation and Benefits Policy</h1>
<p>Owner: {person('hr')}, HR Manager, with {person('finance')}, Finance Head. Applies to all permanent employees.</p>
<h2>Pay</h2>
<p>Salaries are credited on {H['salary_day']}. Payslips are available in the HR portal.</p>
<h2>Allowances</h2>
{html_table(['Allowance', 'Rule'], [
    ['Evening shift allowance', f"INR {H['evening_allowance_inr']} per shift that ends after 20:00"],
    ['Overtime', f"Paid at {H['overtime_rate']}, only when approved in advance by the Centre Manager"],
])}
<h2>Benefits</h2>
<p>Provident fund: {H['pf_percent']} percent of basic salary by the employee and {H['pf_percent']} percent by the company.</p>
<p>Group medical insurance: family floater cover of INR {H['insurance_cover_lakh']} lakh for the employee, spouse and two children.</p>
<p>Hepatitis B vaccination and annual health check: free for all staff.</p>
<h2>Increments</h2>
<p>Annual increments are given in {H['appraisal_cycle']} based on the performance rating (see the Performance Appraisal Policy).</p>""")


@doc("2026-08-04", "word", "HR_Performance_Appraisal_Policy.docx")
def _():
    write_docx("HR_Performance_Appraisal_Policy.docx", "Performance Appraisal Policy", [
        ("p", f"Owner: {person('hr')}, HR Manager. The appraisal cycle runs every {H['appraisal_cycle']}."),
        ("h", "Ratings and increments"),
        ("t", ["Rating", "Meaning", "Increment"], [
            [5, "Outstanding", f"{H['increment_by_rating'][5]} percent"],
            [4, "Exceeds expectations", f"{H['increment_by_rating'][4]} percent"],
            [3, "Meets expectations", f"{H['increment_by_rating'][3]} percent"],
            [2, "Needs improvement", f"{H['increment_by_rating'][2]} percent"],
            [1, "Unsatisfactory", f"{H['increment_by_rating'][1]} percent and a performance improvement plan"],
        ]),
        ("h", "What clinical staff are rated on"),
        ("p", "Patient safety and infection control practice (including hand hygiene audit results), attendance, teamwork and training completed."),
        ("p", "Employees still on probation in April are appraised at the end of probation instead."),
    ])


@doc("2026-08-05", "markdown", "HR_POSH_Policy.md")
def _():
    write_text("markdown", "HR_POSH_Policy.md", f"""
# Prevention of Sexual Harassment (POSH) Policy

{C.COMPANY} has zero tolerance for sexual harassment, as required by the Sexual Harassment of Women at Workplace Act, 2013.

## Internal Committee

- Presiding officer: {H['posh_chair']}, Chief Nursing Officer
- Members: {person('hr')} (HR Manager), one senior nurse, and one external member from a women's welfare organisation

## Making a complaint

- Write to the Internal Committee at ic@nephrova.example within 3 months of the incident.
- The committee completes its inquiry within {H['posh_days']} days and keeps the complaint confidential.
- No one who complains or gives evidence in good faith will face any adverse action.
""")


@doc("2026-08-06", "text", "HR_Circular_Notice_Period_and_Exit.txt")
def _():
    rows = "\n".join(f"  {role}: {days} days" for role, days in H["notice_days"].items())
    write_text("text", "HR_Circular_Notice_Period_and_Exit.txt", f"""
HR CIRCULAR — Notice period and exit process
{C.COMPANY}    Date: 6 August 2026    From: {person('hr')}, HR Manager

Notice period after confirmation:
{rows}

Notice may be shortened only with the Centre Manager's written approval and once the shift roster is covered.
Unserved notice is recovered from the final salary.

Exit steps: return ID card and uniforms, hand over logbooks and keys, exit interview with HR.
Full and final settlement is paid within {C.HR['fnf_days']} days of the last working day.
""")


@doc("2026-08-07", "pdf", "Finance_Delegation_of_Financial_Authority.pdf")
def _():
    write_pdf("Finance_Delegation_of_Financial_Authority.pdf", f"""<h1>Delegation of Financial Authority</h1>
<p>Owner: {person('finance')}, Finance Head. Approved by the Board. Effective 7 August 2026.</p>
<h2>Who can approve a single spend</h2>
{html_table(['Approver', 'Up to'], [[role, fmt_inr(limit)] for role, limit in C.DOFA]
            + [['Board of Directors', f"Above {fmt_inr(C.DOFA_BOARD_ABOVE)}"]])}
<h2>Rules</h2>
<p>A spend may not be split into smaller orders to stay within a lower limit.</p>
<p>Any payment above INR 1,00,000 needs two signatures, one of them the Finance Head or the CEO.</p>
<p>For a purchase needed urgently for patient safety, a Centre Manager may commit up to {fmt_inr(C.EMERGENCY_PURCHASE_LIMIT_INR)}
and must get approval from the correct approver within 3 working days.</p>""")


@doc("2026-08-08", "word", "Finance_Billing_and_Collections_Policy.docx")
def _():
    write_docx("Finance_Billing_and_Collections_Policy.docx", "Billing and Collections Policy", [
        ("p", f"Owner: {person('finance')}, Finance Head. Applies at all three centres."),
        ("h", "Rates per dialysis session"),
        ("t", ["Payer", "Rate"], [["Self-pay", fmt_inr(C.RATE_INR["Self-pay"])],
                                 ["PM-JAY (government scheme)", fmt_inr(C.RATE_INR["PM-JAY"])],
                                 ["Private insurance (cashless)", fmt_inr(C.RATE_INR["Insurance"])]]),
        ("h", "Self-pay patients"),
        ("p", "Payment is collected before the session starts. Patients may pay for up to 13 sessions in advance."),
        ("h", "PM-JAY claims"),
        ("p", f"Submit each claim within {C.PMJAY_SUBMIT_DAYS} days of the session, with the signed session sheet attached."),
        ("p", f"Rejected claims are corrected and resubmitted within {C.PMJAY_RESUBMIT_DAYS} days of the rejection."),
        ("h", "Overdue dues"),
        ("p", f"Any claim or bill unpaid for more than {C.ESCALATE_DUES_DAYS} days is escalated to the Finance Head every Monday."),
        ("p", "No patient's dialysis is ever stopped or delayed because of pending dues."),
    ])


@doc("2026-08-09", "markdown", "Finance_Patient_Refund_and_Assistance_Policy.md")
def _():
    write_text("markdown", "Finance_Patient_Refund_and_Assistance_Policy.md", f"""
# Patient Refund and Financial Assistance Policy

{C.COMPANY}. Owner: {person('finance')}, Finance Head, with {person('medical')}, Medical Director.

## Refunds

- Advance payments for sessions not taken are refunded within {C.REFUND_DAYS} working days of a written request.
- Refunds go back to the original payment method; cash refunds above INR 10,000 are paid by bank transfer.

## Financial assistance

- Self-pay patients with an annual family income below {fmt_inr(C.ASSISTANCE_INCOME_LIMIT_INR)} who are not covered by PM-JAY or insurance can get a {C.ASSISTANCE_DISCOUNT_PERCENT} percent discount on the self-pay rate.
- Apply with an income certificate. The Medical Director and the Finance Head approve each case together.
- Assistance is reviewed every six months.
""")


@doc("2026-09-09", "pdf", "Finance_Procurement_Policy.pdf")
def _():
    write_pdf("Finance_Procurement_Policy.pdf", f"""<h1>Procurement Policy</h1>
<p>Owner: {person('finance')}, Finance Head. Issued 9 September 2026 after review of the August emergency purchases.</p>
<h2>Quotations</h2>
<p>Purchases above {fmt_inr(C.QUOTES_ABOVE_INR)} need three written quotations from approved suppliers.</p>
<p>Below that amount, one quotation from an approved supplier is enough.</p>
<h2>Approval</h2>
<p>Purchase orders are approved within the limits of the Delegation of Financial Authority.</p>
<h2>Emergency purchases</h2>
<p>Spares and consumables needed to keep dialysis safe (for example a machine part or a water plant disinfectant) may be bought
without quotations up to {fmt_inr(C.EMERGENCY_PURCHASE_LIMIT_INR)}, with approval recorded within 3 working days.</p>
<h2>Approved suppliers</h2>
<p>Suppliers of dialysers, blood lines, concentrates and medicines must be reviewed by the Chief Nursing Officer every year.</p>""")


@doc("2026-09-14", "excel", "Finance_Travel_and_Expense_Rates.xlsx")
def _():
    t = C.TRAVEL
    write_xlsx("Finance_Travel_and_Expense_Rates.xlsx", {
        "Rates": [["Item", "Metro cities (INR)", "Other cities (INR)"],
                  ["Hotel per night", t["hotel_metro"], t["hotel_other"]],
                  ["Meals per day", t["meals_metro"], t["meals_other"]]],
        "Local travel": [["Mode", "INR per km"], ["Own two-wheeler", t["two_wheeler_per_km"]], ["Own car", t["car_per_km"]]],
        "Rules": [["Rule", "Detail"],
                  ["Approval", "Travel is approved by your manager before booking"],
                  ["Claims", f"Submit with receipts within {C.EXPENSE_CLAIM_DAYS} days of return"],
                  ["Payment", f"Approved claims are paid within {C.EXPENSE_PAY_DAYS} working days"],
                  ["Owner", person("finance")]],
    })


# ══════════════════════════════════════════════════════
# Long, connected documents
#   30 Jul  Operations Manual (PDF, many pages): how every part of the service runs
#   31 Jul  Risk and Asset Register (Excel, several long sheets)
#    9 Oct  Q3 Board Pack (Word, long): pulls the quarter together and cites
#           the source document for every fact
# ══════════════════════════════════════════════════════
@doc("2026-07-30", "pdf", "Nephrova_Operations_Manual_2026.pdf")
def _():
    centre_rows = [[name, area, count, patients, person(mgr)]
                   for name, area, _, count, patients, mgr in C.CENTRES.values()]
    contacts = [[role, name] for name, role in C.PEOPLE.values()]
    write_pdf("Nephrova_Operations_Manual_2026.pdf", f"""
<h1>Operations Manual 2026</h1>
<p>Version 3.0, effective 30 July 2026. Owner: {person('medical')}, Medical Director, and {person('nursing')}, Chief Nursing Officer.
Approved by {person('ceo')}, Chief Executive Officer. This manual describes how {C.SHORT} runs dialysis at all three centres.
Where a detailed SOP or policy exists, this manual names it; the SOP or policy is the controlling document.</p>

<h2>Chapter 1. About {C.SHORT}</h2>
<p>{C.COMPANY} was founded in {C.FOUNDED}. Our only service is {C.NICHE.lower()}. We do not run wards, theatres or
emergency departments. Every process in this manual exists to make each dialysis session safe, on time and well recorded.</p>
<p>We run {C.TOTAL_MACHINES} dialysis machines across three centres in Pune and treat about {C.TOTAL_PATIENTS} patients who
come two or three times a week. Most patients are funded by the PM-JAY government scheme; the others pay themselves or use private insurance.</p>
<p>Head office: {C.HEAD_OFFICE}.</p>

<h2>Chapter 2. Centres</h2>
{html_table(['Centre', 'Area', 'Dialysis machines', 'Active patients', 'Centre Manager'], centre_rows)}
<p>Every centre runs two shifts, 06:30 to 14:30 and 14:00 to 22:00, from Monday to Saturday. Sunday is kept for maintenance,
water plant disinfection and make-up sessions. Each centre has its own reverse osmosis water plant, a 125 kVA diesel generator
and a UPS that carries every dialysis machine through a power cut until the generator takes over.</p>
<p>Patients are assigned to one home centre. Sessions move to another centre only under the Patient Transfer Protocol.</p>

<h2>Chapter 3. The patient journey</h2>
<h3>3.1 Referral and admission</h3>
<p>Patients are referred by their nephrologist. Before the first session we need the referral letter, the last three months of
blood results, hepatitis B, hepatitis C and HIV screening, and payer details (PM-JAY card, insurance policy, or self-pay consent).</p>
<p>Patients positive for hepatitis B are dialysed only on the dedicated isolation machine at their centre.</p>
<h3>3.2 Scheduling</h3>
<p>Most patients dialyse three times a week for four hours. Twice-weekly schedules need the Medical Director's approval.
Missed sessions are reported to the nephrologist the same day.</p>
<h3>3.3 A dialysis session, step by step</h3>
<p>1. The technician runs the machine's self test and checks the dialysate conductivity reading.</p>
<p>2. The nurse records weight, blood pressure, pulse and temperature, and agrees the fluid removal target.</p>
<p>3. Vascular access is connected: fistula needling, or a catheter connection under the Catheter Care Bundle.</p>
<p>4. Blood pressure is recorded every 30 minutes during treatment.</p>
<p>5. At the end, the line is returned, the access is secured, weight is recorded and the treatment chart is signed.</p>
<h3>3.4 Complications during treatment</h3>
<p>Hypotension during dialysis is treated with normal saline given as a bolus into the blood line, and fluid removal is slowed.</p>
<p>Muscle cramps are managed by slowing fluid removal and stretching; the nurse records every episode.</p>
<p>Hyperkalaemia found on monthly bloods is treated with calcium gluconate in an emergency and reviewed by the nephrologist.</p>
<p>Fever or chills at the start of a catheter session is reported to the Infection Control Nurse the same day and blood cultures are taken.</p>

<h2>Chapter 4. Dialysis machines</h2>
<p>All machines are the Renalis R5 model. Biomedical engineering is led by {person('bme_lead')} with technician {person('bme_tech')}.</p>
<h3>4.1 Preventive maintenance</h3>
{html_table(['Centre', 'First half', 'Second half'], [[C.CENTRES[c][0], *C.PM_MONTHS[c]] for c in C.CENTRES])}
<p>Preventive maintenance covers the hydraulic circuit, blood pump, sensors, safety checks and electrical safety, and takes two days per centre.</p>
<h3>4.2 Responding to alarms</h3>
{html_table(['Alarm', 'First response', 'If it repeats'], [
    ['Conductivity alarm', 'Pause treatment, check the concentrate and connections', 'After the second unexplained alarm, take the machine out of service and call biomedical engineering'],
    ['Venous pressure alarm', 'Check the needle position and the venous line for kinks', 'Re-needle with the nurse in charge'],
    ['Air detector alarm', 'Clamp lines, check the blood line for air', 'Re-prime the blood line'],
    ['Blood leak alarm', 'Stop the blood pump and check the dialyser', 'Replace the dialyser and blood line'],
])}
<p>Every alarm is written in the centre's alarm log with the time, the machine and the action taken.</p>

<h2>Chapter 5. Dialysis water</h2>
<p>Dialysis water is made by a double-pass reverse osmosis plant at each centre and checked against ISO 23500 limits.
SOP-WT-002 is the controlling procedure.</p>
{html_table(['Parameter', 'Action level', 'Maximum'], [
    ['Bacteria', f"{W['bacteria_action']} CFU/mL", f"{W['bacteria_max']} CFU/mL"],
    ['Endotoxin', f"{W['endotoxin_action']} EU/mL", f"{W['endotoxin_max']} EU/mL"],
])}
<p>Each water plant and its loop receive chemical disinfection every month. A sample from the end of the loop is sent to the external laboratory every month.</p>
<p>A result above the maximum means: inform the Medical Director the same day, reduce or stop dialysis at that centre, move sessions under the
Patient Transfer Protocol, disinfect, resample, and resume only after a result below the action level.</p>

<h2>Chapter 6. Power</h2>
<p>A UPS at each centre carries all dialysis machines through a mains failure. The diesel generator must start within 10 seconds.
Generators run a monthly test on load; starter batteries are checked at the same time.</p>

<h2>Chapter 7. Infection prevention</h2>
<p>The Infection Control Policy, the Hand Hygiene Policy and the Catheter Care Bundle apply at every station.
Hand hygiene and catheter care are audited monthly at every centre with a target of {I['target']} percent.</p>
<p>A catheter-related bloodstream infection is treated with vancomycin after each session as prescribed by the nephrologist,
and the case is reported to the Infection Control Nurse and the Quality Committee.</p>
<p>The infection rate is reported every month per 1,000 catheter days for each centre.</p>

<h2>Chapter 8. Bio-medical waste</h2>
<p>Waste is segregated at the station into yellow, red, white and blue containers as described in the Bio-Medical Waste Management SOP,
and handed to the authorised treatment facility every 24 hours. The authorisation is valid until {C.BMW_AUTH_VALID}.</p>

<h2>Chapter 9. Medicines used in the unit</h2>
{html_table(['Medicine', 'Used for'], [
    ['Heparin', 'Preventing clotting in the circuit during dialysis'],
    ['Erythropoietin', 'Anaemia of dialysis patients, given after the session'],
    ['Iron sucrose', 'Iron deficiency, into the blood line'],
    ['Normal saline', 'Hypotension during dialysis'],
    ['Vancomycin', 'Catheter-related bloodstream infection, on prescription'],
    ['Calcium gluconate', 'Hyperkalaemia emergencies'],
])}
<p>Anaemia in dialysis patients is treated with erythropoietin, with iron sucrose when iron stores are low.</p>

<h2>Chapter 10. Quality and NABH</h2>
<p>All three centres are accredited by NABH. The Quality Committee meets every month under the Medical Director and reviews
water results, infections, alarms, complications, audits and incidents. {person('quality')} is the NABH coordinator.</p>
<p>Quality indicators reported monthly: treatment adequacy (Kt/V), missed sessions, hypotension episodes per 100 sessions,
infections per 1,000 catheter days, water results, and hand hygiene compliance.</p>

<h2>Chapter 11. Incidents and escalation</h2>
<p>Every incident, near miss or equipment fault is reported the same day on an incident report. The Centre Manager informs the
Medical Director at once if a patient was or could have been harmed, if dialysis must be reduced, or if water results are above limits.</p>
<p>Each incident with a systemic cause gets a root cause analysis with named owners and due dates, tracked by the Quality Committee.</p>

<h2>Chapter 12. Who to contact</h2>
{html_table(['Role', 'Name'], contacts)}

<h2>Chapter 13. Controlling documents</h2>
<p>SOP-WT-002 Dialysis Water Treatment; Patient Transfer Protocol; Infection Control Policy; Hand Hygiene Policy; Catheter Care Bundle;
Bio-Medical Waste Management SOP; Code of Conduct; and the HR and finance policies issued from August 2026.</p>""")


@doc("2026-07-31", "excel", "Risk_and_Asset_Register_2026.xlsx")
def _():
    risks = [
        ["RSK-01", "Clinical", "Dialysis water above microbiological limits", 2, 5, "Monthly disinfection and testing (SOP-WT-002)", person("bme_lead")],
        ["RSK-02", "People", "Critical tasks depend on one trained person at a centre (for example water plant disinfection)", 3, 4, "None documented; backups to be named", person("hr")],
        ["RSK-03", "Clinical", "Catheter-related bloodstream infections", 3, 5, "Catheter Care Bundle, monthly audits", person("infection")],
        ["RSK-04", "Equipment", "Dialysis machine failure during treatment", 3, 3, "Six-monthly maintenance, spare station per shift", person("bme_lead")],
        ["RSK-05", "Equipment", "Power cut during treatment", 3, 4, "UPS on every machine, generator start within 10 s", person("bme_lead")],
        ["RSK-06", "Finance", "PM-JAY payments delayed beyond 90 days", 4, 3, "Claims within 7 days, weekly ageing review", person("finance")],
        ["RSK-07", "Compliance", "NABH non-conformity at surveillance", 3, 3, "Quarterly internal audits", person("quality")],
        ["RSK-08", "Clinical", "Hepatitis B transmission to staff", 2, 4, "Staff immunisation, isolation machine", person("infection")],
        ["RSK-09", "Supply", "Shortage of dialysers or blood lines", 2, 5, "14 days of cover, two approved suppliers", person("nursing")],
        ["RSK-10", "People", "Nurse and technician attrition", 3, 3, "Referral bonus, evening allowance", person("hr")],
        ["RSK-11", "Data", "Patient data shared without consent", 2, 4, "Privacy notice, access controls", person("quality")],
        ["RSK-12", "Compliance", "Bio-medical waste authorisation lapses", 1, 4, "Renewal tracked by Quality", person("quality")],
    ]
    risk_rows = [["Risk", "Category", "Description", "Likelihood (1-5)", "Impact (1-5)", "Score", "Controls", "Owner"]]
    risk_rows += [[r[0], r[1], r[2], r[3], r[4], r[3] * r[4], r[5], r[6]] for r in risks]

    assets = [["Asset", "Type", "Centre", "Installed", "Last preventive maintenance", "Next preventive maintenance"]]
    last_pm = {"KTH": "2026-02-27", "HDP": "2026-03-18", "PMP": "2026-04-22"}
    next_pm = {"KTH": "2026-08-28", "HDP": "2026-09-15", "PMP": "2026-10-20"}
    for code, (name, *_rest) in C.CENTRES.items():
        installed = 2023 if code == "PMP" else 2021
        for tag in C.machines(code):
            assets.append([tag, "Dialysis machine", name, installed, last_pm[code], next_pm[code]])
        letter = C.CENTRES[code][2]
        assets.append([f"RO-{letter}1", "Water plant", name, installed, "Monthly disinfection", "Monthly disinfection"])
        assets.append([f"GEN-{letter}1", "Diesel generator 125 kVA", name, installed, "Monthly load test", "Monthly load test"])

    write_xlsx("Risk_and_Asset_Register_2026.xlsx", {
        "Risk register": risk_rows,
        "Asset register": assets,
        "Scoring": [["Score", "Rating", "Review"], ["1-6", "Low", "Yearly"], ["8-12", "Medium", "Quarterly"],
                    ["15-25", "High", "Monthly by the Quality Committee"]],
    })


@doc("2026-10-09", "word", "Q3_2026_Board_Pack.docx")
def _():
    q3 = ("Jul", "Aug", "Sep")
    q3_sessions = sum(C.month_sessions(m) for m in q3)
    q3_rev = round(sum(C.revenue_lakh(m) for m in q3), 2)
    q3_ebitda = round(sum(C.ebitda_lakh(m) for m in q3), 2)
    month_rows = [[m, C.month_sessions(m), C.revenue_lakh(m), C.ebitda_lakh(m)] for m in q3]
    centre_rows = [[C.CENTRES[c][0], *[C.SESSIONS[m][c] for m in q3], sum(C.SESSIONS[m][c] for m in q3)] for c in C.CENTRES]
    timeline = [
        ["11–15 Aug", "Kothrud", f"HD-K04 gave {K['alarm_total']} conductivity alarms; repaired under {K['job']}",
         "machine_alarm_log_KTH_2026-08-12.csv; BME_Job_Report_BME-2026-0311_HD-K04.docx"],
        ["18–27 Aug", "Hadapsar", f"Water result above limit; {R['transferred_sessions']} sessions moved to Kothrud; clean resample; service resumed {R['resumed']}",
         "Water_Lab_Report_RO-H1_Aug2026.pdf; Incident_Report_IR-2026-031_RO-H1.docx; Water_Lab_Report_RO-H1_Resample.pdf"],
        ["2 Sep", "All", f"Hepatitis B vaccination drive: {HB['vaccinated']} of {HB['eligible']} staff vaccinated",
         "vaccination_drive_summary_2026-09-02.txt"],
        ["3–12 Sep", "Pimpri", f"Two catheter infections ({I['cases'][0][0]}, {I['cases'][1][0]})",
         "Infection_Report_Case1_PMP-0412.docx; Infection_Report_Case2_PMP-0388.docx"],
        ["7–8 Sep", "Pimpri", f"Generator start delayed {G['start_delay_s']} s in a mains outage; starter battery replaced",
         "shift_log_PMP_2026-09-07.txt; Generator_Load_Test_GEN-P1.pdf"],
        ["15–30 Sep", "Pimpri", f"Infection audit {I['hand_hygiene']} percent, training, re-audit {I['hand_hygiene_after']} percent",
         "Infection_Control_Audit_PMP_Sep2026.pdf; Infection_Control_Reaudit_PMP_Sep30.pdf"],
        ["24 Sep", "All", f"NABH surveillance: {N['majors']} major, {N['minors']} minor non-conformities",
         "NABH_Surveillance_Assessment_Report.pdf; nabh_corrective_action_tracker.csv"],
    ]
    documents_index = [[d, f"{fmt}/{name}"] for d, fmt, name, _ in sorted(DOCS) if d < "2026-10-09"]

    write_docx("Q3_2026_Board_Pack.docx", "Board Pack — Q3 2026 (July to September)", [
        ("p", f"Prepared by {person('ceo')}, CEO, with {person('finance')} (finance), {person('medical')} (clinical), "
              f"{person('quality')} (quality) and {person('hr')} (people). Board meeting: 15 October 2026."),
        ("p", "Every figure in this pack comes from a company document; the source is named next to it, and the appendix lists every document of the quarter."),

        ("h", "1. Summary for the Board"),
        ("p", f"Q3 was our busiest quarter: {q3_sessions} dialysis sessions across three centres, revenue of {inr_lakh(q3_rev)} and EBITDA of "
              f"{inr_lakh(q3_ebitda)} (source: Finance_MIS_Aug_2026.xlsx, Finance_MIS_Sep_2026.xlsx, kpi_dashboard_q3_2026.json)."),
        ("p", "Three events tested our systems: a water quality result above limit at Hadapsar, two catheter infections at Pimpri, and a slow generator start at Pimpri. "
              "In each case patients were protected, the cause was found, and controls were strengthened. NABH accreditation continues."),
        ("p", f"PM-JAY dues are the main financial risk: INR {C.RECEIVABLES['Sep'][0]} lakh outstanding with {C.RECEIVABLES['Sep'][1]} claims older than 30 days "
              "(source: PMJAY_Claims_Ageing_Sep2026.xlsx, Finance_MIS_Sep_2026.xlsx)."),

        ("h", "2. Operations"),
        ("t", ["Centre", "July", "August", "September", "Q3 total"], centre_rows),
        ("p", f"In August, Kothrud ran an extra evening shift and absorbed {R['transferred_sessions']} Hadapsar sessions during {R['transfer_window']} "
              "(source: session_transfers_HDP_to_KTH_Aug2026.csv). Hadapsar's August total is lower for that reason, and Kothrud's is higher."),
        ("p", f"Six-monthly machine maintenance was completed at Kothrud ({C.PM_DATES_2026_H2['KTH']}) and Hadapsar ({C.PM_DATES_2026_H2['HDP']}); "
              f"Pimpri is due {C.PM_DATES_2026_H2['PMP']} (source: PM_Schedule_2026.xlsx)."),

        ("h", "3. Finance"),
        ("t", ["Month", "Sessions", "Revenue (INR lakh)", "EBITDA (INR lakh)"], month_rows),
        ("p", f"Revenue is earned at a blended rate of INR {C.BLENDED_RATE} per session: PM-JAY INR {C.RATE_INR['PM-JAY']}, self-pay INR {C.RATE_INR['Self-pay']}, "
              f"insurance INR {C.RATE_INR['Insurance']} (source: Finance_Billing_and_Collections_Policy.docx)."),
        ("p", f"Consumables cost about INR {C.CONSUMABLES_PER_SESSION} per session; staff cost is INR {C.STAFF_COST_LAKH} lakh a month."),
        ("p", f"Claims are to be submitted within {C.PMJAY_SUBMIT_DAYS} days and rejected claims resubmitted within {C.PMJAY_RESUBMIT_DAYS} days; "
              f"dues older than {C.ESCALATE_DUES_DAYS} days are escalated weekly. Most of the September ageing is claims rejected for missing session sheets."),

        ("h", "4. Clinical quality and safety"),
        ("t", ["When", "Centre", "What happened", "Source documents"], timeline),
        ("h", "4.1 Dialysis water at Hadapsar"),
        ("p", f"RO-H1 showed endotoxin exceedance at {R['endotoxin']} EU/mL against a maximum of {W['endotoxin_max']} EU/mL "
              "(source: Water_Lab_Report_RO-H1_Aug2026.pdf)."),
        ("p", f"The cause was a missed monthly disinfection: only one technician at Hadapsar was trained and he was on leave (source: RCA_RO-H1_Endotoxin.md). "
              "This was risk RSK-02 in the risk register before it happened (source: Risk_and_Asset_Register_2026.xlsx)."),
        ("p", f"No Hadapsar patient had fever or chills. After chemical and heat disinfection the resample showed {R['endotoxin_after']} EU/mL, "
              f"and full service resumed on {R['resumed']}."),
        ("h", "4.2 Catheter infections at Pimpri"),
        ("p", f"Two catheter-related bloodstream infections at Pimpri in September; both were treated with vancomycin. "
              f"The September rate was {I['rate']} per 1,000 catheter days (source: Infection_Control_Audit_PMP_Sep2026.pdf)."),
        ("p", f"The audit found hand hygiene at {I['hand_hygiene']} percent and the catheter bundle at {I['bundle']} percent. After training "
              f"{I['trained_staff']} staff, the re-audit found {I['hand_hygiene_after']} and {I['bundle_after']} percent. No new case since 12 September."),
        ("h", "4.3 Machines and power"),
        ("p", f"HD-K04 was repaired by a conductivity cell replacement after {K['alarm_total']} conductivity alarms "
              f"(source: BME_Job_Report_BME-2026-0311_HD-K04.docx). Our manual now says to remove a machine after the second unexplained alarm."),
        ("p", f"GEN-P1 received a battery replacement and passed a load test with an {G['test_start_s']} second start (source: Generator_Load_Test_GEN-P1.pdf). "
              "The UPS carried every machine during the outage, so no treatment was interrupted."),
        ("h", "4.4 NABH"),
        ("p", f"The surveillance assessment of {N['date']} found {N['majors']} major and {N['minors']} minor non-conformities. Two are closed; "
              f"the third (waste chart at Kothrud) is due by {N['closure_due']} (source: email_NABH_closure_status.txt)."),

        ("h", "5. People"),
        ("p", f"Headcount is {C.TOTAL_STAFF}: " + ", ".join(f"{n} {r.lower()}" for r, n in C.STAFF.items()) + " (source: Staff_Strength_Sep2026.xlsx)."),
        ("p", "In August we issued a complete set of HR policies (code of conduct, recruitment, pay and benefits, appraisal, POSH, notice and exit) "
              "and finance policies (delegation of financial authority, billing and collections, refunds and financial assistance), followed in September "
              "by the procurement policy and the travel and expense rates."),
        ("p", f"Every critical task now has a named backup at each centre, as required by the Leave and Attendance Policy."),

        ("h", "6. Risk register update"),
        ("t", ["Risk", "Before Q3", "Now", "Why"], [
            ["RSK-02 Single-person dependence", "Score 12", "Score 6", "Second technicians trained in water plant disinfection at all centres"],
            ["RSK-03 Catheter infections", "Score 15", "Score 10", "Monthly audits restored at Pimpri; re-audit above target"],
            ["RSK-05 Power cut during treatment", "Score 12", "Score 8", "Monthly starter battery checks added"],
            ["RSK-06 PM-JAY delays", "Score 12", "Score 16", f"Dues rose to INR {C.RECEIVABLES['Sep'][0]} lakh"],
        ]),

        ("h", "7. Decisions requested"),
        ("p", "1. Approve INR 1.8 lakh for training a second water plant technician at every centre (already started)."),
        ("p", "2. Approve a PM-JAY recovery drive led by the Finance Head, with a target of halving claims older than 30 days by 31 December 2026."),
        ("p", f"3. Note that Pimpri machine maintenance on {C.PM_DATES_2026_H2['PMP']} will reduce Pimpri capacity for two days."),

        ("h", "Appendix — documents of the quarter"),
        ("p", "The table lists every document uploaded to the company knowledge base before this pack, in date order."),
        ("t", ["Date", "Document"], documents_index),
    ])


def main() -> None:
    import shutil

    if DATA.exists():
        shutil.rmtree(DATA)
    days = [d for d, *_ in DOCS]
    assert len(DOCS) == TOTAL_DAYS and len(set(days)) == TOTAL_DAYS, "one document per day"
    expected = [(FIRST_DAY + timedelta(days=i)).isoformat() for i in range(TOTAL_DAYS)]
    assert sorted(days) == expected, "documents must cover consecutive days"

    manifest = []
    for day, fmt, name, builder in sorted(DOCS):
        builder()
        assert (DATA / fmt / name).is_file(), f"{name} was not written"
        manifest.append({"date": day, "format": fmt, "file": f"{fmt}/{name}"})
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for m in manifest:
        counts[m["format"]] = counts.get(m["format"], 0) + 1
    print(f"{len(manifest)} documents, {manifest[0]['date']} to {manifest[-1]['date']}: {counts}")


if __name__ == "__main__":
    main()
