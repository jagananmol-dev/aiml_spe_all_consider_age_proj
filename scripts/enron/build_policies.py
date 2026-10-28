"""
Collect Enron's real company policies as their own documents.

Enron's policies are not in the SEC filings; they reached employees by email
and in the July 2000 Code of Ethics booklet. This script builds:

1. Enron_Code_of_Ethics_July_2000.txt: the 65-page booklet, OCR'd page by page
   with the ingestion service's own OCR (the public PDF is a scan whose only
   text layer is a watermark), from the Wayback Machine copy cited by Wikipedia;
2. Enron_Code_of_Ethics_Summary_DOJ_Exhibit.txt: the cover memo and policy summary from
   the US Department of Justice's Enron trial exhibits (public record);
3. one Enron_Policy_*.txt per company policy announced by email, at full length
   (the email bundles cap each email at 3,000 characters), taken from the
   longest copy of each announcement in the raw CMU corpus.

    services/ingestion/.venv/Scripts/python.exe scripts/enron/build_policies.py [--skip-ocr]

Output: .data/enron/policies/*.txt and .data/enron/policies_manifest.json.
"""

import argparse
import json
from datetime import datetime
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import build_emails as B  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / ".data" / "enron" / "policy-src"
OUT = ROOT / ".data" / "enron" / "policies"
MANIFEST = ROOT / ".data" / "enron" / "policies_manifest.json"

ETHICS_PDF_URL = (
    "https://web.archive.org/web/20131008055111id_/http://mishkenot.org.il/Hebrew/docs/ethics/"
    "%D7%A7%D7%95%D7%93%D7%99%D7%9D%20%D7%90%D7%AA%D7%99%D7%99%D7%9D%20%D7%A9%D7%9C%20"
    "%D7%90%D7%A8%D7%92%D7%95%D7%A0%D7%99%D7%9D%20%D7%A2%D7%A1%D7%A7%D7%99%D7%99%D7%9D/"
    "Enron%20Code%20Of%20Ethics.pdf"
)
DOJ_SUMMARY_URL = (
    "https://www.justice.gov/archive/enron/exhibit/02-06/BBC-0001/ocr/EXH012-03035%5EFullText.TXT"
)
HEADERS = {"User-Agent": "VEDA research demo contact@veda-demo.org"}

# Subjects about energy *public* policy (regulators, markets, think tanks), not
# Enron's own rules for its employees and business
PUBLIC_POLICY = re.compile(
    r"NERC|NARUC|PennFuture|Electr\w* Policy|Energy Policy|Public Policy|Policy (paper|Interpretation)"
    r"|Policy Summit|Firm Redirect|Capacity Policy|MAIN Policy|Policy Committee|Policy and other"
    r"|policy statement|Gas Credit Policy|SPP Credit|Credit Policy with|Payables Policy",
    re.I,
)
# Reviewed by hand: threads that only discuss a policy or are not Enron's own
NOT_A_POLICY = re.compile(
    r"Vacation Policy Request|Communication and Policy Problems|Environmental Policy Issues"
    r"|Question re: Email retention|Bowl Game Ticket|Bush CO2|Undeliverable|Change In Vacation Policy",
    re.I,
)
# Words a company policy announcement uses
POLICY_CUES = re.compile(
    r"\b(employees?|must|required|requires|approv\w+|effective|prohibit\w*|comply|compliance"
    r"|violation|retention|limit|procedures?)\b",
    re.I,
)
_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.I)


def fetch(url: str, target: Path) -> Path:
    if not target.exists():
        res = httpx.get(url, headers=HEADERS, timeout=180, follow_redirects=True)
        res.raise_for_status()
        target.write_bytes(res.content)
    return target


def ocr_code_of_ethics() -> str:
    """OCR every page of the scanned booklet with the ingestion service's OCR."""
    cache = SRC / "code_of_ethics_ocr.json"
    pages: dict[str, str] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    pdf = fetch(ETHICS_PDF_URL, SRC / "enron_code_of_ethics_2000.pdf")

    import fitz

    sys.path.insert(0, str(ROOT))
    from nlp_sts.step01_text_extraction import parse_image_ocr

    doc = fitz.open(pdf)
    for number, page in enumerate(doc, start=1):
        if str(number) in pages:
            continue
        image = SRC / f"page_{number:02d}.png"
        page.get_pixmap(dpi=200).save(image)
        text = parse_image_ocr(str(image))["raw_text"]
        # The host stamped its name on every page
        text = "\n".join(
            line for line in text.splitlines()
            if not re.fullmatch(r"\s*(THE SMOKING GUN|WWW\.THESMOKINGGUN\.COM)\s*", line, re.I)
        )
        pages[str(number)] = text
        image.unlink()
        cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        print(f"  OCR page {number}/{len(doc)}: {len(text)} chars", flush=True)
    body = "\n\n".join(f"[Page {n}]\n{pages[str(n)]}" for n in range(1, len(doc) + 1))
    return (
        "Enron Corp. — Code of Ethics (booklet revised July 2000)\n"
        "Issued to all employees with a cover memo dated July 1, 2000. Text read by OCR from the\n"
        "scanned public copy, so some words may be misread.\n"
        f"Source: {ETHICS_PDF_URL}\n\n{body}"
    )


def subject_of(path: Path) -> str | None:
    """The Subject header, read cheaply from the top of the file."""
    with open(path, "rb") as f:
        head = f.read(4000).decode("latin-1")
    m = re.search(r"^Subject:(.*)$", head, re.M)
    return m.group(1).strip() if m else None


def policy_emails(maildir: Path) -> list[dict]:
    B.MAX_BODY_CHARS = 60_000  # full policy text, not the bundle cap
    best: dict[str, dict] = {}
    for mailbox in sorted(p for p in B.long_path(maildir).iterdir() if p.is_dir()):
        for path in B.mailbox_files(mailbox):
            subject = subject_of(path)
            if not subject or "polic" not in subject.lower():
                continue
            title = _PREFIX.sub("", subject).strip()
            if PUBLIC_POLICY.search(title) or NOT_A_POLICY.search(title):
                continue
            m = B.read_message(path)
            if m is None or len(m["body"]) < 600 or len(POLICY_CUES.findall(m["body"])) < 5:
                continue
            key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
            if key not in best or len(m["body"]) > len(best[key]["body"]):
                best[key] = {**m, "title": title, "mailbox": mailbox.name}
    return sorted(best.values(), key=lambda m: m["sort"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maildir", type=Path, default=ROOT / ".data" / "enron-raw" / "maildir")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()
    SRC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    manifest = []

    doj = fetch(DOJ_SUMMARY_URL, SRC / "doj_ethics.txt").read_text(encoding="utf-8", errors="replace")
    name = "Enron_Code_of_Ethics_Summary_DOJ_Exhibit.txt"
    (OUT / name).write_text(
        "Enron Corp. — Code of Ethics: cover memo (July 1, 2000) and summary of policies\n"
        f"US Department of Justice, Enron trial exhibit (OCR text)\nSource: {DOJ_SUMMARY_URL}\n\n{doj}",
        encoding="utf-8",
    )
    manifest.append({"file": name, "date": "2000-07-01"})

    if not args.skip_ocr:
        name = "Enron_Code_of_Ethics_July_2000.txt"
        (OUT / name).write_text(ocr_code_of_ethics(), encoding="utf-8")
        manifest.append({"file": name, "date": "2000-07-01"})

    for m in policy_emails(args.maildir):
        slug = re.sub(r"[^A-Za-z0-9]+", "_", m["title"]).strip("_")[:80]
        name = f"Enron_Policy_{slug}_{m['month']}.txt"
        lines = [f"Enron Corp. policy — {m['title']}", "Distributed to employees by email.", "",
                 f"Date: {m['date']}", f"From: {m['from']}"]
        if m["to"]:
            lines.append(f"To: {m['to']}")
        lines += [f"Subject: {m['subject']}", f"(Copy from the mailbox of {m['mailbox']})", "", m["body"]]
        (OUT / name).write_text("\n".join(lines), encoding="utf-8")
        manifest.append({"file": name, "date": datetime.fromtimestamp(m["sort"]).strftime("%Y-%m-%d")})
        print(f"  {name} ({len(m['body'])} chars)")

    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Wrote {len(manifest)} policy documents to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
