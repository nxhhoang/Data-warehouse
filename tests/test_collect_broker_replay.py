"""Local checks for the bounded broker-to-snapshot reader."""
import json
from types import SimpleNamespace

import pytest

import scripts.collect_broker_replay as collector


def _received(message_id, payload, ack_id=None):
    if isinstance(payload, list):
        payload = json.dumps(payload)
    # Publisher.publish sends raw bytes and does not JSON-encode a string again.
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return SimpleNamespace(
        message=SimpleNamespace(message_id=message_id, data=payload),
        ack_id=ack_id or f"ack-{message_id}",
    )


class FakeSubscriber:
    def __init__(self, batches):
        self.batches = list(batches)
        self.acked = []
        self.return_immediately = []

    def pull(self, **kwargs):
        self.return_immediately.append(kwargs["return_immediately"])
        response = self.batches.pop(0) if self.batches else []
        return SimpleNamespace(received_messages=response)

    def acknowledge(self, **kwargs):
        self.acked.extend(kwargs["ack_ids"])


def test_collects_raw_payloads_and_acks_after_writing(tmp_path, monkeypatch):
    monkeypatch.setattr("os.fsync", lambda _: None)
    stats = tmp_path / "publisher_stats.json"
    stats.write_text(json.dumps({"total": 3, "failed_to_dlq": 0}), encoding="utf-8")
    raw_one = json.dumps({"event": "first"})
    raw_two = json.dumps({"event": "second"})
    inputs = [[raw_one, "{broken"], raw_two]
    subscriber = FakeSubscriber([
        [_received("one", inputs[0])],
        # redelivery: acknowledge it, but do not append the payload again
        [_received("one", raw_one)],
        [_received("two", inputs[1])],
    ])
    output = tmp_path / "snapshot.jsonl"
    result = collector.collect_snapshot(
        subscriber, "projects/p/subscriptions/s", stats, output,
        wait_seconds=2, poll_interval=0,
    )
    serialized = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert serialized == [[raw_one, "{broken"], [raw_two]]
    assert result["accounted_events"] == 3
    # Redelivery is acked too, but only its message ID is deduplicated in the file.
    assert subscriber.acked == ["ack-one", "ack-one", "ack-two"]
    assert all(subscriber.return_immediately)


def test_preserves_an_invalid_non_object_json_payload():
    raw = "[1, 2, 3]"
    assert collector.message_payload_strings(raw) == [raw]
    assert collector.message_payload_strings("{}") == ["{}"]


def test_timeout_does_not_wait_for_an_empty_subscription(tmp_path):
    stats = tmp_path / "publisher_stats.json"
    stats.write_text(json.dumps({"total": 1}), encoding="utf-8")
    subscriber = FakeSubscriber([[] for _ in range(200)])
    with pytest.raises(TimeoutError, match="timed out"):
        collector.collect_snapshot(
            subscriber, "subscription", stats, tmp_path / "snapshot.jsonl",
            wait_seconds=0.05, poll_interval=0,
        )


def test_cli_requires_the_local_emulator(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBSUB_EMULATOR_HOST", raising=False)
    monkeypatch.setattr("sys.argv", [
        "collect_broker_replay.py", "--subscription", "projects/p/subscriptions/s",
        "--stats-file", str(tmp_path / "stats.json"), "--out-file", str(tmp_path / "out.jsonl"),
    ])
    with pytest.raises(RuntimeError, match="PUBSUB_EMULATOR_HOST"):
        collector.main()
