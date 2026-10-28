"""
Download Enron Corp.'s real SEC filings from the email years (1999–2002) and
save each as a plain-text document for the Enron tenant.

Each filing's full submission is fetched from EDGAR; the main document and
its press-release exhibits (EX-99*) are kept, financial data schedules and
graphics are dropped, and any HTML is reduced to text.

    services/ingestion/.venv/Scripts/python.exe scripts/enron/fetch_sec.py

Output: .data/enron/sec/*.txt (gitignored; EDGAR filings are public records).
"""

import html
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".data" / "enron" / "sec"
CIK = "1024401"
# SEC asks automated clients to identify themselves
HEADERS = {"User-Agent": "VEDA research demo contact@veda-demo.org"}

# (form, filing date, accession number, short description)
FILINGS = [
    ("10-K", "2000-03-30", "0001024401-00-000002", "Annual report for 1999"),
    ("DEF 14A", "2000-03-21", "0000950129-00-001279", "Proxy statement 2000"),
    ("10-Q", "2000-05-15", "0001024401-00-000018", "Quarterly report Q1 2000"),
    ("8-K", "2000-05-19", "0000950129-00-002545", "Current report May 2000"),
    ("10-Q", "2000-08-14", "0001024401-00-000036", "Quarterly report Q2 2000"),
    ("10-Q", "2000-11-14", "0001024401-00-500007", "Quarterly report Q3 2000"),
    ("8-K", "2001-01-31", "0000950129-01-000416", "Current report January 2001"),
    ("8-K", "2001-02-28", "0000909281-01-500005", "Current report February 2001"),
    ("DEF 14A", "2001-03-27", "0000950129-01-001669", "Proxy statement 2001"),
    ("10-K", "2001-04-02", "0001024401-01-500010", "Annual report for 2000"),
    ("10-Q", "2001-05-15", "0001024401-01-500014", "Quarterly report Q1 2001"),
    ("10-Q", "2001-08-14", "0001024401-01-500028", "Quarterly report Q2 2001"),
    ("8-K", "2001-11-08", "0000950129-01-503835", "Restatement of prior financial statements"),
    ("8-K", "2001-11-13", "0000950129-01-503913", "Current report November 9 2001"),
    ("8-K", "2001-11-14", "0000950129-01-504015", "Current report November 9 2001 amended"),
    ("10-Q", "2001-11-19", "0000950129-01-504218", "Quarterly report Q3 2001"),
    ("8-K", "2001-12-17", "0001024401-01-500046", "Current report December 2001"),
    ("8-K", "2002-02-07", "0000909518-02-000089", "Current report February 7 2002"),
    ("8-K", "2002-02-12", "0000909518-02-000098", "Current report February 12 2002"),
    ("8-K", "2002-02-14", "0000909518-02-000120", "Current report February 14 2002"),
]

KEEP_TYPES = re.compile(r"^(10-K|10-K405|10-Q|8-K|DEF 14A|EX-99[\.\d]*)$", re.I)
_DOC = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S | re.I)
_TYPE = re.compile(r"<TYPE>([^\n<]+)", re.I)
_TEXT = re.compile(r"<TEXT>(.*?)</TEXT>", re.S | re.I)


def to_text(body: str) -> str:
    """Plain text of an EDGAR document body (HTML reduced, SGML page tags removed)."""
    if re.search(r"<(html|table|p|div|br)\b", body, re.I):
        body = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
        body = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h\d|li)>", "\n", body)
        body = re.sub(r"(?i)</t[dh]>", " | ", body)
        body = re.sub(r"<[^>]+>", "", body)
        body = html.unescape(body)
    body = re.sub(r"(?im)^\s*</?(PAGE|S|C|FN|CAPTION|TABLE)>[ \t\d]*$", "", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def extract(submission: str) -> str:
    parts = []
    for doc in _DOC.findall(submission):
        kind = (_TYPE.search(doc).group(1).strip() if _TYPE.search(doc) else "")
        text = _TEXT.search(doc)
        if not KEEP_TYPES.match(kind) or not text:
            continue
        body = to_text(text.group(1))
        if body:
            parts.append(body if not parts else f"=== Exhibit {kind} ===\n\n{body}")
    return "\n\n".join(parts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for form, date, accession, description in FILINGS:
            name = f"Enron_SEC_{form.replace(' ', '')}_{date}_{description.replace(' ', '_')}.txt"
            target = OUT / name
            if target.exists():
                continue
            url = (f"https://www.sec.gov/Archives/edgar/data/{CIK}/"
                   f"{accession.replace('-', '')}/{accession}.txt")
            res = client.get(url)
            if res.status_code != 200:
                print(f"  FAILED {form} {date}: HTTP {res.status_code}", file=sys.stderr)
                continue
            text = extract(res.text)
            header = (f"Enron Corp. — SEC Form {form}, filed {date}\n"
                      f"{description}\nSource: {url}\n\n")
            target.write_text(header + text, encoding="utf-8")
            print(f"  {name}: {len(text) // 1024} KB")
            time.sleep(0.3)  # SEC fair-access limit is 10 requests/second
    return 0


if __name__ == "__main__":
    sys.exit(main())
