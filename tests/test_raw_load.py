"""Local tests for loading replay output into a project-owned raw dataset."""
import json
from types import SimpleNamespace

from google.cloud import bigquery

from scripts.load_raw_to_bigquery import load_from_jsonl


class FakeLoadJob:
    """A completed local load job with the metadata used by the recorder."""

    job_id = "load-test"
    location = "US"
    dry_run = False
    job_type = "load"
    cache_hit = False
    total_bytes_processed = 0
    total_bytes_billed = 0
    num_dml_affected_rows = None

    def result(self):
        """Simulate successful completion without using the network."""
        return self


class FakeLoadClient:
    """Capture load jobs made by the JSONL loader."""

    def __init__(self):
        self.jobs = []
        self.created = False
        self.existing_rows = 0

    def get_table(self, table_id):
        """Return metadata for an existing table in the fixture."""
        return SimpleNamespace(num_rows=self.existing_rows)

    def get_dataset(self, reference):
        """Act as if the adapter found the requested dataset."""
        return reference

    def create_dataset(self, reference):
        """Record dataset creation without contacting BigQuery."""
        self.created = True
        return reference

    def load_table_from_file(self, stream, table_id, job_config):
        """Read the local stream and preserve the job configuration."""
        stream.read()
        job = FakeLoadJob()
        self.jobs.append((table_id, job_config, job))
        return job


def test_load_ignores_extra_ga4_fields_and_records_job(tmp_path, monkeypatch):
    """Extra fields must not break the intentionally smaller raw schema."""
    record = {"event_date": "20201101", "event_previous_timestamp": "123"}
    (tmp_path / "events-test.jsonl").write_text(json.dumps(record) + "\n",
                                                encoding="utf-8")
    client = FakeLoadClient()
    monkeypatch.setattr(bigquery, "Client", lambda project: client)
    usage_log = tmp_path / "usage.jsonl"
    stats = load_from_jsonl(tmp_path, "test-project", "raw_test", usage_log)
    assert stats == {"test-project.raw_test.events_20201101": 1}
    assert client.jobs[0][1].ignore_unknown_values is True
    assert client.jobs[0][1].write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    recorded = json.loads(usage_log.read_text(encoding="utf-8"))
    assert recorded["job_id"] == "load-test"


def test_load_refuses_to_replace_existing_day(tmp_path, monkeypatch):
    """A small replay cannot silently erase a populated daily table."""
    import pytest

    (tmp_path / "events-test.jsonl").write_text(
        '{"event_date": "20201101"}\n', encoding="utf-8")
    client = FakeLoadClient()
    client.existing_rows = 5000
    monkeypatch.setattr(bigquery, "Client", lambda project: client)
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        load_from_jsonl(tmp_path, "test-project", "raw_test", tmp_path / "usage.jsonl")
    assert client.jobs == []
