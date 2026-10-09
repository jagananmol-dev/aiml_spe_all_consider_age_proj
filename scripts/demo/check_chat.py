"""
Ask the demo tenant's chatbot questions with known answers and check them.

    services/ingestion/.venv/Scripts/python.exe scripts/demo/check_chat.py
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import company as C  # noqa: E402
from seed_tenant import ACCOUNT, BASE  # noqa: E402

# question → substrings that must ALL appear in the answer (case-insensitive)
CHECKS = [
    ("What is wrong with dialysis machine HD-K04 and how was it fixed?", ["conductivity", "cell"]),
    ("What was the endotoxin result for RO-H1 in August 2026?", ["0.31"]),
    ("Why did the Hadapsar water plant fail its water test?", ["disinfection"]),
    ("How many Hadapsar sessions were moved to Kothrud?", ["64"]),
    ("What are the endotoxin limits for dialysis water?", ["0.25"]),
    ("Why did GEN-P1 start late on 7 September?", ["battery"]),
    ("How were the catheter infections at Pimpri treated?", ["vancomycin"]),
    ("What was hand hygiene compliance at Pimpri before and after training?", ["78", "94"]),
    ("What were the results of the NABH surveillance assessment?", ["3", "minor"]),
    ("What was total revenue in September 2026?", [f"{C.revenue_lakh('Sep'):.2f}"]),
    ("How much is outstanding from PM-JAY at the end of September?", ["38.6"]),
    ("How many staff were vaccinated against hepatitis B on 2 September?", ["41"]),
    # Policies: the answer must apply the company's own rules
    ("A centre manager wants to buy a machine spare part costing INR 40,000. Can they approve it themselves?",
     ["25,000"]),
    ("What is the notice period for a dialysis technician who resigns?", ["30"]),
    ("How much evening shift allowance does a nurse get for a shift ending at 22:00?", ["120"]),
    ("A self-pay patient's family earns INR 2 lakh a year and has no insurance. What help can we offer?", ["50"]),
    ("Within how many days must a PM-JAY claim be submitted?", ["7"]),
    ("What increment does an employee rated 4 get?", ["9"]),
    # Long, connected documents (operations manual, risk register, board pack)
    ("Was the Hadapsar water incident a known risk before it happened?", ["RSK-02"]),
    ("What decisions is the Board asked to take in the Q3 board pack?", ["1.8 lakh"]),
    ("What should staff do after a second unexplained conductivity alarm?", ["out of service"]),
    ("How many dialysis sessions did Nephrova run in Q3 2026?", [str(sum(C.month_sessions(m) for m in ("Jul", "Aug", "Sep")))]),
]


def ask(client: httpx.Client, question: str) -> tuple[str, list[str]]:
    answer, titles = "", []
    with client.stream("POST", "/api/chat", json={"message": question}) as res:
        for line in res.iter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event["type"] == "sources":
                titles = [s["title"] for s in event["sources"]]
            elif event["type"] == "token":
                answer += event["text"]
            elif event["type"] == "error":
                answer += f"[ERROR {event['message']}]"
    return answer, titles


def main() -> int:
    passed = 0
    with httpx.Client(base_url=BASE, timeout=600) as client:
        client.post("/api/auth/login", json={k: ACCOUNT[k] for k in ("tenantSlug", "email", "password")}).raise_for_status()
        for question, expected in CHECKS:
            answer, titles = ask(client, question)
            ok = all(e.lower() in answer.lower() for e in expected)
            passed += ok
            print(f"\n[{'PASS' if ok else 'FAIL'}] {question}\n  expects {expected}\n  sources: {titles[:4]}")
            print("  answer: " + answer.strip().replace("\n", "\n          "))
    print(f"\n{passed}/{len(CHECKS)} passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
