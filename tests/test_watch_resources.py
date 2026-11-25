"""Unit tests for the replay resource watchdog (no real processes required)."""

import json

import scripts.watch_resources as watch


def registration(tmp_path, name="pipeline", pid=123, token="dataflow_pipeline.py"):
    payload = {"pid": pid, "label": name, "token": token}
    (tmp_path / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


class TestReadRegistrations:
    def test_reads_valid_entries(self, tmp_path):
        registration(tmp_path)
        (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
        records = watch.read_registrations(tmp_path)
        assert len(records) == 1
        assert records[0]["label"] == "pipeline"

    def test_missing_directory_is_empty(self, tmp_path):
        assert watch.read_registrations(tmp_path / "missing") == []


class TestFormattingAndLimits:
    def test_format_status(self):
        samples = [{"label": "pipeline", "ram_mb": 1024.6}]
        assert watch.format_status(samples, 5000) == "[watch] pipeline=1025 MB | disk free=4.9 GB"

    def test_format_status_without_processes(self):
        assert watch.format_status([], 2048) == "[watch] disk free=2.0 GB"

    def test_no_violations_below_limits(self):
        assert watch.violations([{"label": "p", "ram_mb": 4096}], 2048) == []

    def test_detects_ram_and_disk_violations(self):
        issues = watch.violations([{"label": "p", "ram_mb": 5000}], 100)
        assert len(issues) == 2
        assert "5000 MB" in issues[0]
        assert "100 MB" in issues[1]


class TestStopRegistered:
    def test_stops_registered_and_removes_pid_file(self, tmp_path, monkeypatch):
        registration(tmp_path, pid=42)
        monkeypatch.setattr(watch.time, "sleep", lambda _: None)
        snapshots = iter([(50.0, "python dataflow_pipeline.py"), (None, "")])
        monkeypatch.setattr(watch, "process_snapshot", lambda _: next(snapshots))
        calls = []
        if watch.os.name == "nt":
            monkeypatch.setattr(
                watch.subprocess, "run",
                lambda args, **kwargs: calls.append(args) or type("R", (), {"returncode": 0})(),
            )
        else:
            monkeypatch.setattr(watch.os, "kill", lambda pid, sig: calls.append((pid, sig)))
        watch.stop_registered(tmp_path)
        assert calls
        assert not list(tmp_path.glob("*.json"))

    def test_never_kills_on_command_line_mismatch(self, tmp_path, monkeypatch):
        registration(tmp_path, pid=99, token="dataflow_pipeline.py")
        monkeypatch.setattr(watch, "process_snapshot", lambda _: (50.0, "unrelated-process"))
        watch.stop_registered(tmp_path)
        assert (tmp_path / "pipeline.json").exists()
