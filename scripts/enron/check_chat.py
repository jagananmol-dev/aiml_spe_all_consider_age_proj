"""
Ask the Enron tenant's chatbot questions whose answers are in the real
documents (SEC filings and the email corpus), and check them.

    services/ingestion/.venv/Scripts/python.exe scripts/enron/check_chat.py

Every expected string was confirmed in the source text before it was listed.
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from seed_tenant import ACCOUNT, BASE  # noqa: E402

# question → alternatives; each alternative is a list of substrings that must ALL
# appear in the answer (case-insensitive). The check passes when one alternative matches.
CHECKS = [
    # SEC filings
    ("What were Enron's total revenues in 2000?", [["100,789"], ["100.8 billion"], ["100.789"]]),
    ("What was Enron's 2000 net income as originally reported and as restated in November 2001?",
     [["979", "847"]]),
    ("Which partnerships were consolidated in the November 2001 restatement?", [["Chewco", "JEDI"]]),
    ("Who chaired the Special Investigative Committee of Enron's board?", [["Powers"]]),
    ("Who was the Enron officer behind the LJM partnerships?", [["Fastow"]]),
    ("By how much did Enron reduce shareholders' equity in the third quarter of 2001?", [["1.2 billion"]]),
    # Emails
    ("What exchange ratio was agreed for the Dynegy merger with Enron?", [["0.2685"]]),
    ("How much did ChevronTexaco agree to invest in Dynegy immediately in the Enron deal?",
     [["1.5 billion"]]),
    ("Who took over as CEO when Jeff Skilling left in August 2001?", [["Lay"]]),
    ("What did the anonymous letter to Ken Lay in August 2001 warn about?", [["accounting"]]),
    ("What reason did Jeff Skilling give publicly for resigning?", [["personal"]]),
    # Company policies (Code of Ethics booklet and policy emails)
    ("How long are emails kept in the inbox and how long is voicemail kept under the retention policy?",
     [["30", "90"]]),
    ("When did the Board approve Enron's new Risk Management Policy, and when was it amended?",
     [["August 14, 2001", "October 9, 2001"], ["14 August 2001", "9 October 2001"]]),
    ("How often must Enron employees change their passwords?", [["60 days"]]),
]


def ask(client: httpx.Client, question: str) -> tuple[str, list[str], dict]:
    answer, titles, context = "", [], {}
    with client.stream("POST", "/api/chat", json={"message": question}) as res:
        for line in res.iter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event["type"] == "context":
                context = event
            elif event["type"] == "sources":
                titles = [s["title"] for s in event["sources"]]
            elif event["type"] == "token":
                answer += event["text"]
            elif event["type"] == "error":
                answer += f"[ERROR {event['message']}]"
    return answer, titles, context


def main() -> int:
    passed = 0
    with httpx.Client(base_url=BASE, timeout=600) as client:
        client.post(
            "/api/auth/login", json={k: ACCOUNT[k] for k in ("tenantSlug", "email", "password")}
        ).raise_for_status()
        for question, alternatives in CHECKS:
            started = time.time()
            answer, titles, context = ask(client, question)
            lowered = answer.lower()
            ok = any(all(e.lower() in lowered for e in alt) for alt in alternatives)
            passed += ok
            cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
            bad = sorted(n for n in cited if not 1 <= n <= len(titles))
            print(f"\n[{'PASS' if ok else 'FAIL'}] {question}  ({time.time() - started:.1f}s, "
                  f"search {context.get('retrievalMs')} ms over {context.get('passagesSearched')} passages)")
            print(f"  expects {alternatives}\n  sources: {titles[:5]}")
            if bad:
                print(f"  WARNING: cites passages that were not sent: {bad}")
            print("  answer: " + answer.strip().replace("\n", "\n          ")[:1500])
    print(f"\n{passed}/{len(CHECKS)} passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
