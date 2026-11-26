"""Collect a bounded replay from the local Pub/Sub emulator before running Beam.

The bounded mode is for a known replay batch, not a continuously running stream.
Each snapshot write is flushed before acknowledging the source message. Beam
runs afterwards on the completed snapshot instead of an unbounded native source.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_replay_output import expected_main_events


def message_payload_strings(data) -> list[str]:
    """Recover raw event strings from legacy one-event or batched wire data."""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
    try:
        decoded = json.loads(text)
    except ValueError:
        return [text]
    if isinstance(decoded, list) and decoded and all(
            isinstance(item, str) for item in decoded):
        return decoded
    return [text]


def collect_snapshot(subscriber, subscription, stats_file, output_file,
                     wait_seconds=1800, poll_size=64, poll_interval=0.1):
    """Write and ack every message in a bounded replay, with a hard wait limit."""
    if wait_seconds <= 0 or poll_size < 1:
        raise ValueError("Snapshot wait seconds and poll size must be positive")
    from google.api_core.exceptions import GoogleAPIError

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_seconds
    expected = None
    received_events = 0
    seen_message_ids = set()
    failures = 0
    with output_file.open("x", encoding="utf-8") as snapshot:
        while time.monotonic() < deadline:
            if expected is None and Path(stats_file).exists():
                expected = expected_main_events(Path(stats_file))
                if expected < 1:
                    raise ValueError("Replay statistics contain no positive input count")
            if expected is not None and received_events >= expected:
                break
            try:
                response = subscriber.pull(
                    subscription=subscription, max_messages=poll_size,
                    return_immediately=True,
                )
                written = []
                for received in response.received_messages:
                    message_id = received.message.message_id
                    if message_id and message_id in seen_message_ids:
                        # A redelivery is acknowledged but not appended again.
                        written.append(received.ack_id)
                        continue
                    payloads = message_payload_strings(received.message.data)
                    snapshot.write(json.dumps(payloads, ensure_ascii=False) + "\n")
                    if message_id:
                        seen_message_ids.add(message_id)
                    written.append(received.ack_id)
                    received_events += len(payloads)
                if written:
                    # ACK is only sent once this group has reached the local disk.
                    snapshot.flush()
                    os.fsync(snapshot.fileno())
                    subscriber.acknowledge(subscription=subscription, ack_ids=written)
                elif expected is None:
                    # Empty responses are normal while the publisher is still extracting.
                    pass
                failures = 0
            except (GoogleAPIError, OSError) as error:
                failures += 1
                if failures > 3:
                    raise RuntimeError(f"Broker pull/ack failed repeatedly: {error}") from error
            time.sleep(poll_interval)
        else:
            raise TimeoutError(
                f"Snapshot collection timed out after {wait_seconds}s: "
                f"received {received_events}; expected {expected}")

    if expected is None or received_events != expected:
        raise RuntimeError(
            f"Snapshot count mismatch: received {received_events}; expected {expected}")
    return {"snapshot_file": str(output_file), "input_messages": len(seen_message_ids),
            "accounted_events": received_events, "expected_events": expected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True,
                        help="projects/<project>/subscriptions/<name>")
    parser.add_argument("--stats-file", type=Path, required=True,
                        help="publisher statistics written after publication")
    parser.add_argument("--out-file", type=Path, required=True,
                        help="new JSONL snapshot containing arrays of raw event strings")
    parser.add_argument("--wait-seconds", type=float, default=1800,
                        help="maximum total wait, including publisher extraction")
    parser.add_argument("--poll-size", type=int, default=64,
                        help="maximum messages per immediate pull call")
    args = parser.parse_args()
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        raise RuntimeError("Bounded replay collection requires PUBSUB_EMULATOR_HOST")
    from google.cloud import pubsub_v1

    result = collect_snapshot(
        pubsub_v1.SubscriberClient(), args.subscription, args.stats_file,
        args.out_file, args.wait_seconds, args.poll_size)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
