"""
Turn the CMU Enron email corpus into upload-ready text documents.

The corpus (https://www.cs.cmu.edu/~enron/, May 2015 release) is ~517k
messages in 150 mailboxes, with the same message copied into several folders
and mailboxes. This script:

1. reads every message, keeps 1999-01 … 2002-06 (the corpus has stray dates),
2. removes duplicates (same sender, date, subject and body),
3. assigns each message to one mailbox (sent folders first, catch-all
   folders such as all_documents last),
4. writes one document per mailbox per month, each email its own section
   ("=== Email" separator, which the chunker splits on), split into parts
   when a month is large.

    services/ingestion/.venv/Scripts/python.exe scripts/enron/build_emails.py \
        --maildir .data/enron-raw/maildir [--custodians lay-k skilling-j ...] [--stats]

Output: .data/enron/emails/*.txt and .data/enron/emails_manifest.json.
"""

import argparse
import email
import email.policy
import email.utils
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".data" / "enron" / "emails"
MANIFEST = ROOT / ".data" / "enron" / "emails_manifest.json"

START, END = "1999-01", "2002-06"
MAX_BODY_CHARS = 3000  # long bodies are mostly quoted threads and attachments-as-text
MAX_PART_CHARS = 250_000  # graph extraction parses the first 200k characters of a document
SENT_FOLDERS = ("sent", "sent_items", "_sent_mail", "sent_mail")
# Catch-all folders that mostly repeat messages filed elsewhere: read last, so a
# message is kept from its real folder and these only add what is nowhere else
CATCH_ALL_FOLDERS = {"all_documents", "discussion_threads", "notes_inbox", "deleted_items"}

_QUOTED = re.compile(r"(?m)^>.*\n?")
_BLANKS = re.compile(r"\n{3,}")


def clean_body(body: str) -> str:
    body = body.replace("\r\n", "\n").replace("=20\n", "\n").replace("=\n", "")
    body = _QUOTED.sub("", body)
    # The separator must not appear inside an email
    body = re.sub(r"(?m)^={3,}", "--", body)
    body = _BLANKS.sub("\n\n", body).strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rsplit(" ", 1)[0] + " […]"
    return body


def person(value: str) -> str:
    """'Kenneth Lay <kenneth.lay@enron.com>' / X-From styles → a readable name or address."""
    value = re.sub(r"\s*<[^>]*>", "", value or "").strip().strip('"')
    return re.sub(r"\s+", " ", value)[:120]


def people(value: str, limit: int = 8) -> str:
    names = [person(p) for p in re.split(r",\s*(?![^<]*>)", value or "") if person(p)]
    more = f" and {len(names) - limit} others" if len(names) > limit else ""
    return ", ".join(names[:limit]) + more


def folder_rank(path: Path, mailbox: Path) -> int:
    top = path.relative_to(mailbox).parts[0].lower()
    return 0 if top in SENT_FOLDERS else 2 if top in CATCH_ALL_FOLDERS else 1


def long_path(path: Path) -> Path:
    """
    The corpus names messages "1.", "2." …; Windows path APIs drop a trailing
    dot unless the path uses the extended-length \\\\?\\ prefix.
    """
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        return Path("\\\\?\\" + str(path.resolve()))
    return path


def mailbox_files(mailbox: Path) -> list[Path]:
    return [
        Path(directory) / name
        for directory, _, names in os.walk(mailbox)
        for name in names
    ]


def read_message(path: Path) -> dict | None:
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.compat32)
        stamp = email.utils.parsedate_to_datetime(str(msg["Date"]))
    except Exception:
        return None
    month = f"{stamp.year:04d}-{stamp.month:02d}"
    if not START <= month <= END:
        return None
    payload = msg.get_payload(decode=True)
    body = payload.decode("latin-1") if isinstance(payload, bytes) else str(msg.get_payload())
    body = clean_body(body)
    def header(*names: str) -> str:
        for name in names:
            if msg.get(name):
                return str(msg.get(name))
        return ""

    sender = person(header("X-From", "From"))
    subject = re.sub(r"\s+", " ", header("Subject")).strip()
    return {
        "month": month,
        "date": stamp.strftime("%a, %d %b %Y %H:%M"),
        "sort": stamp.timestamp(),
        "from": sender,
        "to": people(header("X-To", "To")),
        "cc": people(header("X-cc", "Cc")),
        "subject": subject or "(no subject)",
        "custodian": folder_owner(header("X-Folder")),
        "body": body,
        "key": hashlib.sha1(
            f"{sender}|{stamp.isoformat()}|{subject}|{body[:2000]}".encode("utf-8", "replace")
        ).hexdigest(),
    }


_EXPORT_NAME = re.compile(r"^([A-Z][a-z]+)_([A-Z][A-Za-z']+(?:_(?:Jr|Sr|II|III))?)_[A-Z][a-z]{2}\d{4}")
_LAST_FIRST = re.compile(r"^([A-Z][A-Za-z' ]+?),\s*([A-Z][a-z]+)$")


def folder_owner(x_folder: str) -> str | None:
    r"""
    The mailbox owner named in X-Folder's first segment:
    "\Kenneth_Lay_Dec2000\...", "\Dasovich, Jeff (Non-Privileged)\...",
    "\ExMerge - Williams III, Bill\...". Short logins ("\jskillin") give None.
    """
    top = x_folder.strip("\\").split("\\", 1)[0].strip()
    top = re.sub(r"^ExMerge - |\s*\(Non-Privileged\)$", "", top).strip()
    if m := _EXPORT_NAME.match(top):
        return f"{m.group(1)} {m.group(2).replace('_', ' ')}"
    if m := _LAST_FIRST.match(top):
        return f"{m.group(2)} {m.group(1)}"
    return None


def mailbox_owner(mailbox: Path, sample: list[str]) -> str:
    """The custodian's name by vote over X-Folder names, else built from the folder name."""
    common = Counter(s for s in sample if s).most_common(1)
    if common:
        return common[0][0]
    last, _, initial = mailbox.name.partition("-")
    return f"{initial.upper()}. {last.title()}" if initial else mailbox.name


def format_email(m: dict) -> str:
    lines = [f"Date: {m['date']}", f"From: {m['from']}"]
    if m["to"]:
        lines.append(f"To: {m['to']}")
    if m["cc"]:
        lines.append(f"Cc: {m['cc']}")
    lines.append(f"Subject: {m['subject']}")
    return "=== Email\n" + "\n".join(lines) + "\n\n" + (m["body"] or "(no text)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--maildir", type=Path, default=ROOT / ".data" / "enron-raw" / "maildir")
    parser.add_argument("--custodians", nargs="*", help="mailbox folder names (default: all)")
    parser.add_argument("--stats", action="store_true", help="only print sizes, write nothing")
    args = parser.parse_args()

    mailboxes = sorted(p for p in long_path(args.maildir).iterdir() if p.is_dir())
    if args.custodians:
        wanted = set(args.custodians)
        mailboxes = [m for m in mailboxes if m.name in wanted]

    seen: set[str] = set()
    by_box: dict[str, list[dict]] = defaultdict(list)
    owners: dict[str, str] = {}
    total = 0
    for mailbox in mailboxes:
        files = mailbox_files(mailbox)
        files.sort(key=lambda p: (folder_rank(p, mailbox), str(p)))
        folder_names = []
        for path in files:
            total += 1
            m = read_message(path)
            if m is None:
                continue
            folder_names.append(m["custodian"])
            if m["key"] in seen:
                continue
            seen.add(m["key"])
            by_box[mailbox.name].append(m)
        owners[mailbox.name] = mailbox_owner(mailbox, folder_names)
        print(f"  {mailbox.name:<16} {owners[mailbox.name]:<28} {len(by_box[mailbox.name]):>6} unique",
              flush=True)

    unique = sum(len(v) for v in by_box.values())
    chars = sum(len(m["body"]) + 200 for v in by_box.values() for m in v)
    print(f"\n{total} messages read, {unique} unique in {START}…{END}, ~{chars / 1e6:.0f} MB of text")
    if args.stats:
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    manifest = []
    for box, messages in sorted(by_box.items()):
        name = re.sub(r"[^A-Za-z0-9]+", "_", owners[box]).strip("_") or box
        months: dict[str, list[dict]] = defaultdict(list)
        for m in messages:
            months[m["month"]].append(m)
        for month, items in sorted(months.items()):
            items.sort(key=lambda m: m["sort"])
            parts, current, size = [], [], 0
            for m in items:
                block = format_email(m)
                if current and size + len(block) > MAX_PART_CHARS:
                    parts.append(current)
                    current, size = [], 0
                current.append(block)
                size += len(block) + 2
            parts.append(current)
            for i, blocks in enumerate(parts, start=1):
                suffix = f"_part{i}" if len(parts) > 1 else ""
                file_name = f"Enron_Email_{name}_{month}{suffix}.txt"
                header = (f"Enron Corp. email — mailbox of {owners[box]}, {month}"
                          f"{f' (part {i} of {len(parts)})' if len(parts) > 1 else ''}\n"
                          f"{len(blocks)} emails, oldest first.\n\n")
                (OUT / file_name).write_text(header + "\n\n".join(blocks), encoding="utf-8")
                manifest.append({
                    "file": file_name,
                    "mailbox": box,
                    "owner": owners[box],
                    "month": month,
                    "emails": len(blocks),
                    # Uploaded on the last day the month's emails cover
                    "date": datetime.fromtimestamp(items[-1]["sort"]).strftime("%Y-%m-%d"),
                })
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Wrote {len(manifest)} documents to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
