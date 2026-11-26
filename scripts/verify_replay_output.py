"""Verify event accounting before a replay is loaded into BigQuery Raw."""
import argparse
import json
from pathlib import Path


def _line_count(directory: Path, pattern: str) -> int:
    """Count non-empty completed JSONL records without loading full files into RAM."""
    return sum(1 for path in directory.glob(pattern)
               for line in _read_lines(path) if line.strip())


def _read_lines(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield line


def _dropped_event_count(directory: Path) -> int:
    """Sum rows removed by explicit quality rules, not informational logs."""
    total = 0
    for path in directory.glob("quality_log*.jsonl"):
        for line in _read_lines(path):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("action") == "drop_and_log":
                total += int(record.get("affected_rows", 0))
    return total


def expected_main_events(stats_path: Path) -> int:
    """Return raw events published to the main topic, excluding the separate DLQ topic."""
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    expected = int(stats["total"]) - int(stats.get("failed_to_dlq", 0))
    if expected < 0:
        raise ValueError("Publisher statistics have more DLQ events than input events")
    return expected


def validate_replay_outputs(directory: Path, expected_events: int) -> dict:
    """Compare input accounting against valid, dead-letter and dropped records."""
    valid = _line_count(directory, "events*.jsonl")
    dead_letter = _line_count(directory, "dead_letter*.jsonl")
    dropped = _dropped_event_count(directory)
    processed = valid + dead_letter + dropped
    difference = processed - expected_events
    return {
        "expected_events": expected_events,
        "valid_events": valid,
        "dead_letter_events": dead_letter,
        "dropped_quality_events": dropped,
        "accounted_events": processed,
        "difference": difference,
        "complete": difference == 0,
    }


def main() -> int:
    """Return 0 when complete, 2 when still incomplete, and 1 on discrepancies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="completed pipeline JSONL output directory")
    parser.add_argument("--stats-file", type=Path, required=True, help="publisher counter JSON")
    parser.add_argument("--output", type=Path, default=None,
                        help="write a checkpoint JSON only after complete accounting")
    args = parser.parse_args()
    if not args.dir.is_dir():
        raise ValueError(f"Replay output directory does not exist: {args.dir}")

    summary = validate_replay_outputs(args.dir, expected_main_events(args.stats_file))
    print(json.dumps(summary, indent=2))
    if summary["complete"]:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0
    if summary["difference"] > 0:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
