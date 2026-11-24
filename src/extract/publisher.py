"""Extract layer — Python Publisher (report section 3.3, layer 2).

Queries GA4 event data from BigQuery over a configured date range, converts
each record into a JSON message and replays it through Pub/Sub in event
timestamp order, simulating online data ingestion.

Usage:
    python src/extract/publisher.py

Configuration comes from environment variables or the .env file
(see .env.example): GCP_PROJECT_ID, BQ_SOURCE_DATASET, EXTRACT_START_DATE,
EXTRACT_END_DATE, EXTRACT_LIMIT, PUBSUB_TOPIC, PUBSUB_DLQ_TOPIC,
PUBSUB_SUBSCRIPTION.
"""

import os
import sys
import time
from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery, pubsub_v1

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_PUBLISH_RETRIES = 3


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
            name=sub_path,
            topic=topic_path,
            dead_letter_policy={
                "dead_letter_topic": dlq_path,
                "max_delivery_attempts": 5,
            },
        )
        print(f"[pubsub] created subscription {subscription_id} (with dead-letter policy)")
    except GoogleAPIError as err:
        print(f"[pubsub] could not attach dead-letter policy ({err}); creating plain subscription")
        subscriber.create_subscription(name=sub_path, topic=topic_path)
        print(
            "Note: grant roles/pubsub.publisher to the Pub/Sub service account "
            f"on topic {dlq_topic_id} to enable dead-letter mode."
        )
    return sub_path


def fetch_event_payloads(bq_client: bigquery.Client, source_dataset: str,
                         start_date: str, end_date: str, limit: int):
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
        Maximum number of events; 0 means no limit (for testing).

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
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
        ]
    )
    job = bq_client.query(query, job_config=job_config)
    for row in job.result():
        yield row["payload"]


def publish_all(publisher: pubsub_v1.PublisherClient, topic_path: str,
                dlq_path: str, payloads) -> dict:
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

    Returns
    -------
    dict
        Counters with keys 'published', 'failed_to_dlq' and 'total'.
    """
    stats = {"published": 0, "failed_to_dlq": 0, "total": 0}
    for payload in payloads:
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
            except GoogleAPIError as err:
                print(f"[publish] attempt {attempt} failed: {err}")
                time.sleep(min(2 ** attempt, 30))
        if not published:
            try:
                future = publisher.publish(dlq_path, data)
                future.result(timeout=60)
                stats["failed_to_dlq"] += 1
            except GoogleAPIError as err:
                print(f"[dlq] could not publish to the dead-letter topic: {err}")
        if stats["total"] % 10000 == 0:
            print(f"[publish] sent {stats['total']} events...")
    return stats


def main() -> int:
    """Replay GA4 events from BigQuery into Pub/Sub; returns an exit code."""
    load_env_file()
    project_id = get_setting("GCP_PROJECT_ID", "")
    if not project_id:
        print("Missing GCP_PROJECT_ID (see .env.example)")
        return 1
    source_dataset = get_setting(
        "BQ_SOURCE_DATASET",
        "bigquery-public-data.ga4_obfuscated_sample_ecommerce",
    )
    start_date = to_yyyymmdd(get_setting("EXTRACT_START_DATE", "20201101"))
    end_date = to_yyyymmdd(get_setting("EXTRACT_END_DATE", "20210131"))
    limit = int(get_setting("EXTRACT_LIMIT", "0"))
    topic_id = get_setting("PUBSUB_TOPIC", "ga4-events")
    dlq_topic_id = get_setting("PUBSUB_DLQ_TOPIC", "ga4-events-dlq")
    subscription_id = get_setting("PUBSUB_SUBSCRIPTION", f"{topic_id}-sub")

    bq_client = bigquery.Client(project=project_id)
    publisher = pubsub_v1.PublisherClient()
    setup_pubsub(publisher, project_id, topic_id, dlq_topic_id, subscription_id)

    topic_path = publisher.topic_path(project_id, topic_id)
    dlq_path = publisher.topic_path(project_id, dlq_topic_id)
    print(f"[extract] replaying events from {source_dataset} "
          f"({start_date} -> {end_date}, limit={limit or 'none'})")

    payloads = fetch_event_payloads(bq_client, source_dataset, start_date, end_date, limit)
    stats = publish_all(publisher, topic_path, dlq_path, payloads)
    print(f"[extract] finished: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
