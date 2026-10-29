#!/usr/bin/env python3
"""Validate the synthetic JSONL demo dataset using only Python's standard library."""
import json
import sys
from pathlib import Path

REQUIRED_FIELDS = {
    "record_id", "created_date", "category", "priority", "status", "channel",
    "summary", "customer_id", "resolution_minutes", "is_synthetic"
}

def validate(path: Path) -> int:
    count = 0
    errors = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"Line {line_number}: invalid JSON: {exc}")
                errors += 1
                continue
            missing = REQUIRED_FIELDS - record.keys()
            if missing:
                print(f"Line {line_number}: missing fields: {', '.join(sorted(missing))}")
                errors += 1
            if record.get("is_synthetic") is not True:
                print(f"Line {line_number}: is_synthetic must be true")
                errors += 1
            count += 1
    print(f"Records checked: {count}")
    print(f"Validation errors: {errors}")
    return 1 if errors else 0

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo-data/synthetic_support_records.jsonl")
    raise SystemExit(validate(target))
