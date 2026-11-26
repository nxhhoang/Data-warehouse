"""Tests for replay accounting before any raw load is allowed."""
import json
import sys
from pathlib import Path

from scripts.verify_replay_output import main, validate_replay_outputs

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_replay_output.py"


def _rows(directory, prefix, count):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{prefix}-test.jsonl").write_text("{}\n" * count, encoding="utf-8")


def _stats(directory, total=9, failed=0):
    path = directory / "publisher_stats.json"
    path.write_text(json.dumps({"total": total, "failed_to_dlq": failed}), encoding="utf-8")
    return path


def _arguments(directory, extra=()):
    return [str(value) for value in [
        SCRIPT, "--dir", directory, "--stats-file", directory / "publisher_stats.json", *extra,
    ]]


def test_complete_accounting_includes_dropped_rows_but_not_information_logs(tmp_path, monkeypatch):
    _rows(tmp_path, "events", 4)
    _rows(tmp_path, "dead_letter", 2)
    (tmp_path / "quality_log-test.jsonl").write_text(
        '\n'.join([
            json.dumps({"action": "use_unknown_dimension", "affected_rows": 1}),
            json.dumps({"action": "drop_and_log", "affected_rows": 2}),
            json.dumps({"action": "drop_and_log", "affected_rows": 1}),
        ]) + "\n", encoding="utf-8")
    _stats(tmp_path)
    summary = validate_replay_outputs(tmp_path, 9)
    assert summary["complete"] is True
    assert summary["valid_events"] == 4
    assert summary["dead_letter_events"] == 2
    assert summary["dropped_quality_events"] == 3
    assert summary["accounted_events"] == 9

    monkeypatch.setattr(sys, "argv", _arguments(
        tmp_path, ["--output", tmp_path / "replay_counts.json"]))
    assert main() == 0
    checkpoint = json.loads((tmp_path / "replay_counts.json").read_text(encoding="utf-8"))
    assert checkpoint["complete"] is True
    assert checkpoint["expected_events"] == 9


def test_incomplete_accounting_is_pending_and_writes_no_checkpoint(tmp_path, monkeypatch, capsys):
    _rows(tmp_path, "events", 4)
    _stats(tmp_path, total=9)
    monkeypatch.setattr(sys, "argv", _arguments(
        tmp_path, ["--output", tmp_path / "replay_counts.json"]))
    assert main() == 2
    assert not (tmp_path / "replay_counts.json").exists()
    result = json.loads(capsys.readouterr().out)
    assert result["difference"] == -5


def test_more_outputs_than_published_is_fatal(tmp_path, monkeypatch):
    _rows(tmp_path, "events", 6)
    _stats(tmp_path, total=5)
    monkeypatch.setattr(sys, "argv", _arguments(tmp_path))
    assert main() == 1


def test_separate_publisher_dlq_is_not_counted_as_main_input(tmp_path):
    stats = _stats(tmp_path, total=10, failed=2)
    assert validate_replay_outputs(tmp_path, 8)["expected_events"] == 8
    assert stats.name == "publisher_stats.json"
