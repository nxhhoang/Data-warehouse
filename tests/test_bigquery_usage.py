"""Local tests for BigQuery free-tier safeguards; no network is used."""
import json

import pytest

from src.extract.bigquery_usage import prepare_query
from src.extract.publisher import fetch_event_payloads, publish_all


class FakeJob:
    """Enough query job metadata to exercise the byte and recording guards."""

    def __init__(self, estimated_bytes, config, actual_bytes=None):
        self._config = config
        self.dry_run = config.dry_run
        self.job_type = "query"
        self.job_id = "dry-job" if self.dry_run else "real-job"
        self.location = "US"
        self.cache_hit = False
        self.total_bytes_processed = (
            estimated_bytes if self.dry_run else
            estimated_bytes if actual_bytes is None else actual_bytes
        )
        self.total_bytes_billed = self.total_bytes_processed
        self.num_dml_affected_rows = None

    def result(self):
        """Return one serialized event as a source extractor would."""
        if self.dry_run:
            return iter([])
        return iter([{"payload": '{"event_name": "page_view"}'}])


class FakeClient:
    """Returns a dry-run job and, only if permitted, a real query job."""

    def __init__(self, estimated_bytes):
        self.estimated_bytes = estimated_bytes
        self.configs = []

    def query(self, query, job_config):
        self.configs.append(job_config)
        return FakeJob(self.estimated_bytes, job_config)


def test_query_guard_stops_before_real_query(tmp_path):
    """A large dry-run estimate must not launch a billable-query job."""
    client = FakeClient(129)
    with pytest.raises(ValueError, match="above the"):
        prepare_query(client, "SELECT 1", None, 128,
                      "unit_test", tmp_path / "usage.jsonl")
    assert len(client.configs) == 1
    assert client.configs[0].dry_run is True


def test_extract_uses_hard_limit_and_records_actual_bytes(tmp_path):
    """Source extraction records both the estimate and actual scanned bytes."""
    log = tmp_path / "usage.jsonl"
    client = FakeClient(100)
    payloads = list(fetch_event_payloads(
        client, "source.dataset", "20201101", "20201101", 1,
        maximum_bytes_billed=128, usage_log=log))
    assert payloads == ['{"event_name": "page_view"}']
    real_config = client.configs[1]
    assert real_config.maximum_bytes_billed == 128
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [row["purpose"] for row in rows] == [
        "source_extract_dry_run", "source_extract"]
    assert rows[-1]["total_bytes_processed"] == 100
    assert rows[-1]["job_id"] == "real-job"


def test_direct_kpi_script_can_import_repo_helpers():
    """Regression: executing src/kpi/deploy_views.py must find the repo root."""
    import runpy

    module = runpy.run_path("src/kpi/deploy_views.py", run_name="import_test")
    assert len(module["VIEW_FILES"]) == 3


def test_zero_query_limit_is_rejected(tmp_path):
    """Zero cannot silently turn off the query-size guard."""
    with pytest.raises(ValueError, match="positive"):
        prepare_query(FakeClient(1), "SELECT 1", None, 0,
                      "unit_test", tmp_path / "usage.jsonl")


def test_publisher_throttles_between_messages(monkeypatch):
    """Three events at ten per second require two 100 ms pauses."""
    from tests.test_publisher import FakePublisher

    clock = [0.0]
    sleeps = []
    monkeypatch.setattr("src.extract.publisher.time.monotonic", lambda: clock[0])

    def advance(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr("src.extract.publisher.time.sleep", advance)
    stats = publish_all(FakePublisher(), "ga4-events", "ga4-events-dlq",
                        iter(["a", "b", "c"]), rate_limit_per_second=10)
    assert stats["total"] == 3
    assert sleeps == pytest.approx([0.1, 0.1])
