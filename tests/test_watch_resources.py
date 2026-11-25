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
    def test_does_not_double_count_wrapper_and_listener(self, tmp_path, monkeypatch):
        registrations = [
            registration(tmp_path, "emulator", 1, "pubsub"),
            registration(tmp_path, "emulator-wrapper", 2, "pubsub"),
        ]
        monkeypatch.setattr(watch, "read_registrations", lambda _: registrations)
        monkeypatch.setattr(watch, "process_snapshot", lambda _, include_group=False:
                            (128.0, "cloud-pubsub-emulator"))
        samples = watch.collect_samples(registrations)
        assert [sample["pid"] for sample in samples] == [1]

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


class TestListenerRegistration:
    def test_registers_real_listener_only_when_token_matches(self, tmp_path, monkeypatch):
        """Find and register the Java listener without killing an unrelated process."""
        monkeypatch.setattr(watch.os, "name", "nt")
        monkeypatch.setattr(watch.subprocess, "run", lambda *args, **kwargs:
                            type("Result", (), {"stdout": "1234\n"})())
        monkeypatch.setattr(watch, "process_snapshot", lambda _:
                            (151.0, "java -jar cloud-pubsub-emulator.jar --port=8085"))
        record = watch.register_windows_listener(tmp_path, 8085, "emulator",
                                                 "cloud-pubsub-emulator")
        assert record["pid"] == 1234
        assert watch.read_registrations(tmp_path) == [record]

    def test_linux_emulator_ram_includes_process_group(self, monkeypatch):
        """RSS comes from all members of the isolated broker process group."""
        original_path = watch.Path

        class FakeStatFile:
            kind = "stat"

            def read_text(self, encoding="utf-8"):
                if self.kind == "status":
                    return "VmRSS: 102400 kB\n"
                return "(java) S 1 1234 1234 0 0"

            def with_name(self, name):
                child = FakeStatFile()
                child.kind = name
                return child

        fake_stat = FakeStatFile()
        monkeypatch.setattr(watch, "Path", lambda _: type(
            "FakeProc", (), {"glob": lambda self, pattern: [fake_stat]})())
        monkeypatch.setattr(watch.os, "getpgid", lambda _: 1234, raising=False)
        assert watch._linux_emulator_group_ram_kb(1234) == 102400
        monkeypatch.setattr(watch, "Path", original_path)


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

    def test_stops_consumers_before_emulator(self, tmp_path, monkeypatch):
        """Closing the broker first would produce avoidable consumer RPC errors."""
        registration(tmp_path, name="emulator", pid=10, token="pubsub-emulator")
        registration(tmp_path, name="pipeline", pid=20, token="dataflow_pipeline.py")
        monkeypatch.setattr(watch.time, "sleep", lambda _: None)
        live = {10: True, 20: True}

        def snapshot(pid):
            if not live[pid]:
                return None, ""
            return 50.0, "dataflow_pipeline.py" if pid == 20 else "pubsub-emulator"

        monkeypatch.setattr(watch, "process_snapshot", snapshot)
        stopped = []
        if watch.os.name == "nt":
            def stop(args, **kwargs):
                stopped.append(int(args[2]))
                live[stopped[-1]] = False
            monkeypatch.setattr(watch.subprocess, "run", stop)
        else:
            monkeypatch.setattr(watch.os, "getpgid", lambda pid: pid)
            def stop(pid, signal):
                stopped.append(pid)
                live[pid] = False
            monkeypatch.setattr(watch.os, "kill", stop)
            monkeypatch.setattr(watch.os, "killpg", stop)
        watch.stop_registered(tmp_path)
        assert stopped.index(20) < stopped.index(10)
