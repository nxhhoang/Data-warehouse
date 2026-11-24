"""Verify the pipeline dry-run outputs against the expected fixture routing.

The fixture from scripts/make_test_fixture.py has a deterministic expected
outcome (10 input lines -> 4 valid events, 2 dropped purchases, 1 duplicate,
2 dead-letter rows, 4 quality-log rows). This script reads the JSONL shards
written by the dry-run and fails loudly if anything deviates.

Usage:
    python scripts/verify_dry_run.py [--dir build/pipeline_dry_run]

Exit code 0 = all checks passed, 1 = mismatch (details printed).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

EXPECTED_VALID = 4
EXPECTED_DEAD_LETTER = 2
EXPECTED_QUALITY_ROWS = 4
EXPECTED_RULES = {
    "purchase_without_transaction_id",
    "negative_or_zero_revenue",
    "missing_session_id",
    "duplicate_event",
}


def read_jsonl(directory: Path, prefix: str) -> list[dict]:
    """Read and merge all WriteToText shards matching <prefix>*.jsonl."""
    records = []
    shards = sorted(directory.glob(f"{prefix}*.jsonl"))
    if not shards:
        return records
    for shard in shards:
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="build/pipeline_dry_run",
                        help="dry-run output directory")
    args = parser.parse_args()
    out_dir = Path(args.dir)
    if not out_dir.exists():
        print(f"FAIL: output directory not found: {out_dir}")
        return 1

    failures = []

    events = read_jsonl(out_dir, "events")
    dead_letter = read_jsonl(out_dir, "dead_letter")
    quality = read_jsonl(out_dir, "quality_log")

    if len(events) != EXPECTED_VALID:
        failures.append(f"expected {EXPECTED_VALID} valid events, got {len(events)}")
    if len(dead_letter) != EXPECTED_DEAD_LETTER:
        failures.append(f"expected {EXPECTED_DEAD_LETTER} dead-letter rows, "
                        f"got {len(dead_letter)}")
    if len(quality) != EXPECTED_QUALITY_ROWS:
        failures.append(f"expected {EXPECTED_QUALITY_ROWS} quality-log rows, "
                        f"got {len(quality)}")

    rules = {row["rule_name"] for row in quality}
    if rules != EXPECTED_RULES:
        failures.append(f"quality-log rules mismatch: got {sorted(rules)}, "
                        f"expected {sorted(EXPECTED_RULES)}")

    # Content checks on the surviving events
    purchases = [e for e in events if e["event_name"] == "purchase"]
    if len(purchases) != 1:
        failures.append(f"expected exactly 1 valid purchase, got {len(purchases)}")
    else:
        purchase = purchases[0]
        if purchase["ecommerce"]["transaction_id"] != "AT-001":
            failures.append("valid purchase should keep transaction_id AT-001")
        if not isinstance(purchase["event_timestamp"], int):
            failures.append("event_timestamp should be coerced to int "
                            f"(got {type(purchase['event_timestamp']).__name__})")

    # The user_engagement event of user 9876543210 carries placeholder sources
    no_source = [e for e in events if e["user_pseudo_id"] == "9876543210.9876543210"]
    if len(no_source) == 1:
        traffic = no_source[0]["traffic_source"]
        if traffic != {"source": None, "medium": None, "name": None}:
            failures.append(f"placeholder traffic_source should be nulled, got {traffic}")
    else:
        failures.append(f"expected 1 event from the anonymized user, got {len(no_source)}")

    dead_errors = Counter(row["error"].split(":")[0] for row in dead_letter)
    if dead_errors.get("json_parse", 0) != 1:
        failures.append("dead letter should contain exactly 1 json_parse error")
    if dead_errors.get("missing_or_invalid", 0) != 1:
        failures.append("dead letter should contain exactly 1 missing_or_invalid error")

    if failures:
        print("FAIL: dry-run output does not match the expected fixture routing")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    summary = Counter(row["rule_name"] for row in quality)
    print("PASS: dry-run output matches the expected fixture routing")
    print(f"  valid events   : {len(events)}")
    print(f"  dead letter    : {len(dead_letter)}")
    print(f"  quality log    : {len(quality)} rows -> {dict(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
