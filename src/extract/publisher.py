"""Extract layer — Python Publisher (report section 3.3, layer 2).

Queries GA4 event data from BigQuery over a configured date range, converts
each record into a JSON message and replays it through Pub/Sub in event
timestamp order, simulating online data ingestion.

Usage:
    python src/extract/publisher.py                        # query BigQuery and replay
    python src/extract/publisher.py --from-file FILE       # publish a local JSONL file;
                                                           # works with the Pub/Sub emulator
                                                           # (PUBSUB_EMULATOR_HOST) with no
                                                           # GCP account at all

Configuration comes from environment variables or the .env file
(see .env.example): GCP_PROJECT_ID, BQ_SOURCE_DATASET, EXTRACT_START_DATE,
EXTRACT_END_DATE, EXTRACT_LIMIT, PUBSUB_TOPIC, PUBSUB_DLQ_TOPIC,
PUBSUB_SUBSCRIPTION.
"""

import argparse
import os
import sys
import time
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery, pubsub_v1

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.extract.bigquery_usage import DEFAULT_USAGE_LOG, prepare_query, record_job  # noqa: E402

MAX_PUBLISH_RETRIES = 3
DEFAULT_QUERY_LIMIT_BYTES = 128 * 1024**2


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Load key/value pairs from a .env file if it exists.

    Existing environment variables are never overwritten, so values set
    in the shell always win over the file.

    Parameters
    ----------
    path : Path, optional
        Path to the .env file. Default is the repository root .env.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value.strip())


def to_yyyymmdd(date_str: str) -> str:
    """Normalize '2020-11-01' or '20201101' into '20201101'."""
    return date_str.replace("-", "").strip()


def get_setting(name: str, default: str) -> str:
    return os.environ.get(name, default)


def setup_pubsub(publisher: pubsub_v1.PublisherClient, project_id: str,
                 topic_id: str, dlq_topic_id: str, subscription_id: str) -> str:
    """Create the topic, dead-letter topic and subscription if missing.

    The subscription is created with a dead-letter policy (at most 5 delivery
    attempts). GCP requires granting the Pub/Sub service account publish
    permission on the dead-letter topic; if attaching the policy fails due
    to permissions, the subscription is still created without the policy and
    remediation instructions are printed.

    Parameters
    ----------
    publisher : pubsub_v1.PublisherClient
        Client used to create and look up topics.
    project_id : str
        GCP project that owns the Pub/Sub resources.
    topic_id : str
        Topic that carries the replayed GA4 events.
    dlq_topic_id : str
        Dead-letter topic for messages that cannot be processed.
    subscription_id : str
        Subscription the Dataflow pipeline reads from.

    Returns
    -------
    str
        Full path of the subscription.
    """
    topic_path = publisher.topic_path(project_id, topic_id)
    dlq_path = publisher.topic_path(project_id, dlq_topic_id)
    sub_path = f"projects/{project_id}/subscriptions/{subscription_id}"

    try:
        publisher.get_topic(topic=topic_path)
    except GoogleAPIError:
        publisher.create_topic(name=topic_path)
        print(f"[pubsub] created topic {topic_id}")
    try:
        publisher.get_topic(topic=dlq_path)
    except GoogleAPIError:
        publisher.create_topic(name=dlq_path)
        print(f"[pubsub] created dead-letter topic {dlq_topic_id}")

    subscriber = pubsub_v1.SubscriberClient()
    try:
        subscriber.get_subscription(subscription=sub_path)
        return sub_path
    except GoogleAPIError:
        pass

    try:
        subscriber.create_subscription(
            request={
                "name": sub_path,
                "topic": topic_path,
                "dead_letter_policy": {
                    "dead_letter_topic": dlq_path,
                    "max_delivery_attempts": 5,
                },
            },
        )
        print(f"[pubsub] created subscription {subscription_id} (with dead-letter policy)")
    except GoogleAPIError as err:
        print(f"[pubsub] could not attach dead-letter policy ({err}); creating plain subscription")
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        print(
            "Note: grant roles/pubsub.publisher to the Pub/Sub service account "
            f"on topic {dlq_topic_id} to enable dead-letter mode."
        )
    return sub_path


def fetch_event_payloads(bq_client: bigquery.Client, source_dataset: str,
                         start_date: str, end_date: str, limit: int,
                         maximum_bytes_billed: int = DEFAULT_QUERY_LIMIT_BYTES,
                         usage_log=DEFAULT_USAGE_LOG):
    """Query BigQuery and yield each event as a JSON string (TO_JSON_STRING).

    Rows are ordered by event_timestamp so the replay follows the original
    chronological order.

    Parameters
    ----------
    bq_client : bigquery.Client
        Client used to run the query.
    source_dataset : str
        Dataset containing the events_* wildcard tables.
    start_date : str
        First day to replay, formatted as YYYYMMDD.
    end_date : str
        Last day to replay, formatted as YYYYMMDD.
    limit : int
        Maximum number of events; replay requires a positive limit.
    maximum_bytes_billed : int, optional
        Per-query dry-run and execution ceiling. Default is 128 MiB.
    usage_log : pathlib.Path, optional
        Append-only JSONL file containing dry-run and actual job metrics.

    Yields
    ------
    str
        One GA4 event serialized as a JSON string.
    """
    query = f"""
        SELECT TO_JSON_STRING(t) AS payload
        FROM `{source_dataset}.events_*` t
        WHERE _TABLE_SUFFIX BETWEEN @start_date AND @end_date
        ORDER BY t.event_timestamp
    """
    if limit and limit > 0:
        query += f" LIMIT {int(limit)}"
    params = [
        bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
        bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
    ]
    job = prepare_query(bq_client, query, params, maximum_bytes_billed,
                        "source_extract", usage_log)
    print(f"[extract] BigQuery job id: {job.job_id}", flush=True)
    try:
        for row in job.result():
            yield row["payload"]
    finally:
        scanned_mib = (job.total_bytes_processed or 0) / 1024**2
        print(f"[extract] query completed, scanned {scanned_mib:.2f} MiB", flush=True)
        record_job(job, "source_extract", usage_log)


def file_payloads(path: str):
    """Yield each non-empty line of a JSONL file as a Pub/Sub payload.

    The fixture from scripts/make_test_fixture.py uses exactly the message
    format the pipeline expects, so this path can drive a full local chain
    against the Pub/Sub emulator without any GCP account.

    Parameters
    ----------
    path : str
        Path to a JSONL file, one event per line.

    Yields
    ------
    str
        One JSON string per line, blank lines skipped.
    """
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield line


def rate_per_second(total: int, started_at: float) -> float:
    """Return messages published per second since a monotonic start time."""
    elapsed = max(time.monotonic() - started_at, 1e-6)
    return total / elapsed


def publish_all(publisher: pubsub_v1.PublisherClient, topic_path: str,
                dlq_path: str, payloads, rate_limit_per_second: float = 0.0) -> dict:
    """Publish every payload, routing persistent failures to the dead-letter topic.

    Each message is retried up to MAX_PUBLISH_RETRIES times with exponential
    backoff; after that it is published to the dead-letter topic instead.

    Parameters
    ----------
    publisher : pubsub_v1.PublisherClient
        Client used to publish messages.
    topic_path : str
        Full path of the main topic.
    dlq_path : str
        Full path of the dead-letter topic.
    payloads : Iterable[str]
        JSON strings produced by fetch_event_payloads.
    rate_limit_per_second : float, optional
        Maximum scheduled publishing rate; 0 disables throttling.

    Returns
    -------
    dict
        Counters with keys 'published', 'failed_to_dlq' and 'total'.
    """
    if rate_limit_per_second < 0:
        raise ValueError("Publish rate limit cannot be negative")
    stats = {"published": 0, "failed_to_dlq": 0, "total": 0}
    started_at = time.monotonic()
    last_beat = started_at
    for payload in payloads:
        if rate_limit_per_second > 0 and stats["total"] > 0:
            scheduled_time = started_at + stats["total"] / rate_limit_per_second
            time.sleep(max(0.0, scheduled_time - time.monotonic()))
        now = time.monotonic()
        if now - last_beat >= 10:
            elapsed = now - started_at
            print(f"[publish] heartbeat: {stats} at {rate_per_second(stats['total'], started_at):.1f} ev/s")
            last_beat = now
        stats["total"] += 1
        data = payload.encode("utf-8")
        published = False
        for attempt in range(1, MAX_PUBLISH_RETRIES + 1):
            try:
                future = publisher.publish(topic_path, data)
                future.result(timeout=60)
                stats["published"] += 1
                published = True
                break
            except (GoogleAPIError, TimeoutError) as err:
                print(f"[publish] attempt {attempt} failed: {err}")
                time.sleep(min(2 ** attempt, 30))
        if not published:
            try:
                future = publisher.publish(dlq_path, data)
                future.result(timeout=60)
                stats["failed_to_dlq"] += 1
            except (GoogleAPIError, TimeoutError) as err:
                print(f"[dlq] could not publish to the dead-letter topic: {err}")
        if stats["total"] % 10000 == 0:
            print(f"[publish] sent {stats['total']} events...")
    return stats


def main() -> int:
    """Replay GA4 events into Pub/Sub (from BigQuery or a local JSONL file)."""
    parser = argparse.ArgumentParser(
        description="Replay GA4 events into Pub/Sub (real service or emulator).")
    parser.add_argument("--from-file", default=None, metavar="PATH",
                        help="publish each line of this JSONL file instead of "
                             "querying BigQuery (e.g. tests/fixtures/"
                              "ga4_events_sample.jsonl)")
    parser.add_argument("--limit", type=int, default=None,
                        help="maximum events extracted from BigQuery")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--publish-rate-per-second", type=float, default=None)
    parser.add_argument("--max-query-mib", type=float, default=None,
                        help="fail dry runs above this estimate (default: 128 MiB)")
    parser.add_argument("--setup-only", action="store_true",
                        help="create the Pub/Sub resources, then exit without extracting")
    args = parser.parse_args()

    load_env_file()
    project_id = get_setting("GCP_PROJECT_ID", "")
    if not project_id:
        print("Missing GCP_PROJECT_ID (see .env.example)")
        return 1
    topic_id = get_setting("PUBSUB_TOPIC", "ga4-events")
    dlq_topic_id = get_setting("PUBSUB_DLQ_TOPIC", "ga4-events-dlq")
    subscription_id = get_setting("PUBSUB_SUBSCRIPTION", f"{topic_id}-sub")

    publisher = pubsub_v1.PublisherClient()
    sub_path = setup_pubsub(
        publisher, project_id, topic_id, dlq_topic_id, subscription_id)

    topic_path = publisher.topic_path(project_id, topic_id)
    dlq_path = publisher.topic_path(project_id, dlq_topic_id)
    if args.setup_only:
        print(f"[pubsub] ready: {sub_path}")
        return 0

    if args.from_file:
        print(f"[extract] replaying events from file {args.from_file}")
        payloads = file_payloads(args.from_file)
    else:
        source_dataset = get_setting(
            "BQ_SOURCE_DATASET",
            "bigquery-public-data.ga4_obfuscated_sample_ecommerce",
        )
        start_date = to_yyyymmdd(args.start_date or get_setting(
            "EXTRACT_START_DATE", "20201101"))
        end_date = to_yyyymmdd(args.end_date or get_setting(
            "EXTRACT_END_DATE", "20201101"))
        limit = args.limit if args.limit is not None else int(get_setting(
            "EXTRACT_LIMIT", "100"))
        if limit <= 0:
            print("Sandbox tests require a positive EXTRACT_LIMIT or --limit")
            return 1
        max_query_bytes = int(args.max_query_mib * 1024**2) \
            if args.max_query_mib is not None else int(get_setting(
                "BQ_MAX_QUERY_BYTES", str(DEFAULT_QUERY_LIMIT_BYTES)))
        usage_log = get_setting("BQ_USAGE_LOG", str(DEFAULT_USAGE_LOG))
        print(f"[extract] replaying events from {source_dataset} "
              f"({start_date} -> {end_date}, limit={limit})")
        query_project_id = get_setting("BQ_QUERY_PROJECT", project_id)
        print(f"[extract] query project: {query_project_id}")
        bq_client = bigquery.Client(project=query_project_id)
        payloads = fetch_event_payloads(
            bq_client, source_dataset, start_date, end_date, limit,
            maximum_bytes_billed=max_query_bytes, usage_log=usage_log)

    publish_rate = args.publish_rate_per_second
    if publish_rate is None:
        publish_rate = float(get_setting("PUBLISH_RATE_PER_SEC", "0"))
    stats = publish_all(publisher, topic_path, dlq_path, payloads,
                        rate_limit_per_second=publish_rate)
    print(f"[extract] finished: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
