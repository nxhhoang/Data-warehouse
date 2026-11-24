"""Unit tests for the Python Publisher helpers (no GCP account needed).

publish_all is tested with hand-rolled fakes so the retry and dead-letter
routing is verified without touching real Pub/Sub. time.sleep is patched out
to keep the tests fast.
Run from the repository root:  pytest tests/test_publisher.py
"""

import pytest

import src.extract.publisher as publisher
from src.extract.publisher import load_env_file, publish_all, to_yyyymmdd


class FakeFuture:
    """Mimics google.cloud.pubsub_v1 futures."""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def result(self, timeout=None):
        if self.should_fail:
            raise publisher.GoogleAPIError("fake failure")
        return "msg-id"


class FakePublisher:
    """Mimics PublisherClient.publish for the main topic and the DLQ."""

    def __init__(self, fail_topic=False):
        self.fail_topic = fail_topic
        self.topic_calls = []
        self.dlq_calls = []

    def publish(self, topic_path, data):
        if topic_path.endswith("ga4-events"):
            self.topic_calls.append(data)
            return FakeFuture(should_fail=self.fail_topic)
        self.dlq_calls.append(data)
        return FakeFuture()


class TestToYyyymmdd:
    def test_dashed_date(self):
        assert to_yyyymmdd("2020-11-01") == "20201101"

    def test_compact_date_is_unchanged(self):
        assert to_yyyymmdd("20201101") == "20201101"

    def test_strips_whitespace(self):
        assert to_yyyymmdd(" 2020-11-01 ") == "20201101"


class TestLoadEnvFile:
    def test_loads_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("UNIT_TEST_VAR_A=hello\n# comment\nUNIT_TEST_VAR_B=world\n",
                            encoding="utf-8")
        monkeypatch.delenv("UNIT_TEST_VAR_A", raising=False)
        monkeypatch.delenv("UNIT_TEST_VAR_B", raising=False)
        load_env_file(env_file)
        assert __import__("os").environ["UNIT_TEST_VAR_A"] == "hello"
        assert __import__("os").environ["UNIT_TEST_VAR_B"] == "world"

    def test_never_overwrites_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("UNIT_TEST_VAR_A=from-file\n", encoding="utf-8")
        monkeypatch.setenv("UNIT_TEST_VAR_A", "from-shell")
        load_env_file(env_file)
        assert __import__("os").environ["UNIT_TEST_VAR_A"] == "from-shell"

    def test_missing_file_is_a_noop(self, tmp_path):
        load_env_file(tmp_path / "does-not-exist")  # must not raise


class TestPublishAll:
    def test_happy_path_publishes_everything(self, monkeypatch):
        monkeypatch.setattr(publisher.time, "sleep", lambda s: None)
        fake = FakePublisher()
        payloads = [f'{{"event_name": "page_view", "n": {i}}}' for i in range(5)]
        stats = publish_all(fake, "projects/p/topics/ga4-events",
                             "projects/p/topics/ga4-events-dlq", iter(payloads))
        assert stats == {"published": 5, "failed_to_dlq": 0, "total": 5}
        assert fake.dlq_calls == []

    def test_persistent_failure_routes_to_dlq_after_retries(self, monkeypatch):
        monkeypatch.setattr(publisher.time, "sleep", lambda s: None)
        fake = FakePublisher(fail_topic=True)
        payloads = ['{"event_name": "purchase"}']
        stats = publish_all(fake, "projects/p/topics/ga4-events",
                             "projects/p/topics/ga4-events-dlq", iter(payloads))
        assert stats == {"published": 0, "failed_to_dlq": 1, "total": 1}
        # MAX_PUBLISH_RETRIES attempts against the main topic, then one DLQ publish
        assert len(fake.topic_calls) == publisher.MAX_PUBLISH_RETRIES
        assert len(fake.dlq_calls) == 1

    def test_empty_input(self):
        fake = FakePublisher()
        stats = publish_all(fake, "t", "d", iter([]))
        assert stats == {"published": 0, "failed_to_dlq": 0, "total": 0}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
