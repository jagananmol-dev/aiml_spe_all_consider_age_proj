"""
Nephrova Renal Care — single source of truth for the demo dataset.

A fictional healthcare company with one niche: outpatient haemodialysis for
people with chronic kidney disease, at three centres in Pune. Every
generated document takes its names, dates, and numbers from here, so the
documents agree with each other. All people, patients, and the company are
fictional; patients appear only as de-identified IDs.
"""

COMPANY = "Nephrova Renal Care Pvt. Ltd."
SHORT = "Nephrova"
NICHE = "Outpatient haemodialysis for people with chronic kidney disease"
FOUNDED = 2018
HEAD_OFFICE = "Office 402, Sai Plaza, Baner Road, Pune 411045"

ACCOUNT = {
    "companyName": "Nephrova Renal Care",
    "tenantSlug": "nephrova",
    "name": "Ritu Malhotra",
    "email": "demo@nephrova.example",
    "password": "Nephrova@Demo#2026",
}

PEOPLE = {
    "ceo": ("Ritu Malhotra", "Chief Executive Officer"),
    "medical": ("Dr. Sameer Deshpande", "Medical Director (Nephrologist)"),
    "nursing": ("Anjali Thomas", "Chief Nursing Officer"),
    "bme_lead": ("Nikhil Joshi", "Biomedical Engineering Lead"),
    "bme_tech": ("Rahul Pawar", "Biomedical Technician"),
    "infection": ("Pooja Shinde", "Infection Control Nurse"),
    "quality": ("Kiran Bhosale", "Quality Manager (NABH Coordinator)"),
    "finance": ("Vivek Jain", "Finance Head"),
    "hr": ("Snehal Patil", "HR Manager"),
    "mgr_kth": ("Amit Gokhale", "Centre Manager, Kothrud"),
    "mgr_hdp": ("Farah Khan", "Centre Manager, Hadapsar"),
    "mgr_pmp": ("Suresh Nair", "Centre Manager, Pimpri"),
    "senior_tech": ("Ganesh More", "Senior Dialysis Technician, Hadapsar"),
}


def person(key: str) -> str:
    return PEOPLE[key][0]


# code: name, area, tag letter, dialysis machines, active patients, manager key
CENTRES = {
    "KTH": ("Nephrova Kothrud", "Kothrud, Pune", "K", 12, 96, "mgr_kth"),
    "HDP": ("Nephrova Hadapsar", "Hadapsar, Pune", "H", 10, 80, "mgr_hdp"),
    "PMP": ("Nephrova Pimpri", "Pimpri, Pune", "P", 8, 62, "mgr_pmp"),
}
TOTAL_MACHINES = sum(c[3] for c in CENTRES.values())
TOTAL_PATIENTS = sum(c[4] for c in CENTRES.values())


def machines(code: str) -> list[str]:
    letter, count = CENTRES[code][2], CENTRES[code][3]
    return [f"HD-{letter}{i:02d}" for i in range(1, count + 1)]


# Six-monthly preventive maintenance of dialysis machines
PM_MONTHS = {"KTH": ("February", "August"), "HDP": ("March", "September"), "PMP": ("April", "October")}
PM_DATES_2026_H2 = {"KTH": "28–29 August 2026", "HDP": "15–16 September 2026", "PMP": "20–21 October 2026"}

# Dialysis sessions per month. In August, 64 Hadapsar sessions ran at Kothrud.
SESSIONS = {
    "Jul": {"KTH": 1230, "HDP": 1052, "PMP": 798},
    "Aug": {"KTH": 1312, "HDP": 976, "PMP": 806},
    "Sep": {"KTH": 1236, "HDP": 1044, "PMP": 812},
}

PAYER_MIX = {"PM-JAY": 0.45, "Self-pay": 0.35, "Insurance": 0.20}
RATE_INR = {"PM-JAY": 1500, "Self-pay": 2000, "Insurance": 2400}
BLENDED_RATE = round(sum(PAYER_MIX[p] * RATE_INR[p] for p in PAYER_MIX))  # INR per session
CONSUMABLES_PER_SESSION = 780  # INR: dialyser, bloodlines, concentrate, heparin
STAFF_COST_LAKH = 22.0  # per month, all centres (74 staff)
OTHER_OPEX_LAKH = 6.5  # per month: rent, power, water, admin


def month_sessions(month: str) -> int:
    return sum(SESSIONS[month].values())


def revenue_lakh(month: str, centre: str | None = None) -> float:
    sessions = SESSIONS[month][centre] if centre else month_sessions(month)
    return round(sessions * BLENDED_RATE / 1e5, 2)


def ebitda_lakh(month: str) -> float:
    consumables = month_sessions(month) * CONSUMABLES_PER_SESSION / 1e5
    return round(revenue_lakh(month) - consumables - STAFF_COST_LAKH - OTHER_OPEX_LAKH, 2)


STAFF = {"Nurses": 22, "Dialysis technicians": 30, "Biomedical engineers": 4, "Administration and support": 18}
TOTAL_STAFF = sum(STAFF.values())

# Dialysis water limits (ISO 23500 / AAMI)
WATER = {"bacteria_max": 100, "bacteria_action": 50, "endotoxin_max": 0.25, "endotoxin_action": 0.125}

# ── Events ────────────────────────────────────────────
HDK04 = {
    "tag": "HD-K04",
    "alarms": {"11 August 2026": 2, "12 August 2026": 3, "13 August 2026": 1},
    "measured": 15.6,
    "reference": 14.0,
    "job": "BME-2026-0311",
    "repaired": "14 August 2026",
    "back": "15 August 2026",
}
HDK04["alarm_total"] = sum(HDK04["alarms"].values())

ROH1 = {
    "tag": "RO-H1",
    "last_disinfection": "2 July 2026",
    "missed_due": "2 August 2026",
    "sampled": "18 August 2026",
    "result_date": "21 August 2026",
    "endotoxin": 0.31,
    "bacteria": 48,
    "incident": "IR-2026-031",
    "disinfected": "22 August 2026",
    "resampled": "23 August 2026",
    "resample_result_date": "26 August 2026",
    "endotoxin_after": 0.04,
    "bacteria_after": 6,
    "transferred_sessions": 64,
    "transfer_window": "21–26 August 2026",
    "resumed": "27 August 2026",
}
TRANSFERS = [("2026-08-21", 10), ("2026-08-22", 12), ("2026-08-23", 11),
             ("2026-08-24", 10), ("2026-08-25", 11), ("2026-08-26", 10)]
assert sum(n for _, n in TRANSFERS) == ROH1["transferred_sessions"]

GENP1 = {
    "tag": "GEN-P1",
    "date": "7 September 2026",
    "time": "14:10",
    "start_delay_s": 45,
    "target_s": 10,
    "fixed": "8 September 2026",
    "test_start_s": 8,
    "incident": "IR-2026-036",
}

CRBSI = {
    "cases": [("PMP-0412", "3 September 2026"), ("PMP-0388", "12 September 2026")],
    "catheter_days": 640,
    "audit_date": "15 September 2026",
    "hand_hygiene": 78,
    "bundle": 70,
    "target": 90,
    "training": "17–19 September 2026",
    "trained_staff": 22,
    "reaudit_date": "30 September 2026",
    "hand_hygiene_after": 94,
    "bundle_after": 92,
}
CRBSI["rate"] = round(len(CRBSI["cases"]) * 1000 / CRBSI["catheter_days"], 1)

HEPB = {"date": "2 September 2026", "eligible": 46, "vaccinated": 41}

NABH = {
    "date": "24 September 2026",
    "assessor": "Dr. R. Iyer",
    "majors": 0,
    "minors": 3,
    "closure_due": "24 October 2026",
    "ncs": [
        ("NC-1", "Hadapsar", "The RO-H1 disinfection log had no entry for August 2026."),
        ("NC-2", "Pimpri", "Hand hygiene audits were done quarterly instead of monthly."),
        ("NC-3", "Kothrud", "The colour-coding chart for bio-medical waste was missing in the store room."),
    ],
}

RECEIVABLES = {"Aug": (31.2, 88), "Sep": (38.6, 112)}  # PM-JAY: INR lakh outstanding, claims older than 30 days

BMW_AUTH_VALID = "31 March 2028"

# ── HR policies ───────────────────────────────────────
HR = {
    "probation_months": 6,
    "notice_days": {"Nurses and dialysis technicians": 30, "Managers and engineers": 60, "Other staff": 30},
    "fnf_days": 45,  # full and final settlement after the last working day
    "salary_day": "the last working day of each month",
    "evening_allowance_inr": 120,  # per shift that ends after 20:00
    "overtime_rate": "twice the normal hourly rate",
    "insurance_cover_lakh": 3,  # family floater, employee + spouse + 2 children
    "pf_percent": 12,
    "increment_by_rating": {5: 12, 4: 9, 3: 6, 2: 3, 1: 0},  # percent
    "appraisal_cycle": "April",
    "referral_bonus_inr": 10000,
    "posh_chair": "Anjali Thomas",
    "posh_days": 90,
}

# ── Finance policies ──────────────────────────────────
# Delegation of financial authority: who may approve a single spend, INR
DOFA = [
    ("Centre Manager", 25_000),
    ("Biomedical Engineering Lead (equipment spares and service only)", 50_000),
    ("Finance Head", 500_000),
    ("Chief Executive Officer", 2_500_000),
]
DOFA_BOARD_ABOVE = 2_500_000
QUOTES_ABOVE_INR = 50_000  # three written quotations needed above this
EMERGENCY_PURCHASE_LIMIT_INR = 100_000  # patient-safety purchases, post-facto approval within 3 working days
PMJAY_SUBMIT_DAYS = 7
PMJAY_RESUBMIT_DAYS = 15
ESCALATE_DUES_DAYS = 90
ASSISTANCE_DISCOUNT_PERCENT = 50
ASSISTANCE_INCOME_LIMIT_INR = 300_000  # annual family income
REFUND_DAYS = 7
EXPENSE_CLAIM_DAYS = 15
EXPENSE_PAY_DAYS = 10
TRAVEL = {"hotel_metro": 5000, "hotel_other": 3000, "meals_metro": 1000, "meals_other": 700, "two_wheeler_per_km": 4, "car_per_km": 10}
