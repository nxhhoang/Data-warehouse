"""Inspect Pub/Sub topics and subscriptions, locally or on the emulator.

The google-cloud-pubsub client honors PUBSUB_EMULATOR_HOST, so the same
commands work against the local emulator (no credentials) and the real
service (ADC). This provides the visibility the emulator lacks: it has no
Cloud Monitoring console like the real Pub/Sub.

Examples:
    python scripts/pubsub_status.py --project local-project
    python scripts/pubsub_status.py --subscription ga4-events-sub --peek 3

Warning: --peek pulls messages from the subscription WITHOUT acknowledging
them. A concurrent subscriber (the pipeline, another status invocation)
competes for the same messages; unacknowledged messages are redelivered
after the ack deadline. Only peek while the pipeline is stopped.
"""

import argparse
import os
import sys

DEFAULT_PROJECT = "local-project"
DEFAULT_SUBSCRIPTION = "ga4-events-sub"


def list_infrastructure(publisher, subscriber, project_id: str) -> dict:
    """List topics and subscriptions in a project.

    Parameters
    ----------
    publisher : Pub/Sub publisher client
        Client used for the topics.list API or an equivalent test fake.
    subscriber : Pub/Sub subscriber client
        Client used for the subscriptions.list API or an equivalent test fake.
    project_id : str
        Project label; the emulator treats it only as part of resource names.

    Returns
    -------
    dict
        Keys 'topics' and 'subscriptions', each a sorted list of resource
        names as returned by the API.
    """
    project_path = f"projects/{project_id}"
    topics = sorted(topic.name for topic in publisher.list_topics(
        request={"project": project_path}))
    subscriptions = sorted(sub.name for sub in subscriber.list_subscriptions(
        request={"project": project_path}))
    return {"topics": topics, "subscriptions": subscriptions}


def peek_messages(subscriber, project_id: str, subscription_id: str,
                  count: int) -> list[dict]:
    """Pull up to `count` messages for inspection, without acknowledging them.

    Returns one dict per message with its id, publish_time and a short payload
    preview. Empty lists mean there is currently no backlog.
    """
    subscription = subscriber.subscription_path(project_id, subscription_id)
    response = subscriber.pull(subscription=subscription, max_messages=count,
                               return_immediately=True)
    result = []
    for received in response.received_messages:
        message = received.message
        result.append({
            "ack_id": received.ack_id,
            "message_id": message.message_id,
            "publish_time": str(message.publish_time),
            "payload_preview": message.data.decode("utf-8", errors="replace")[:160],
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID", DEFAULT_PROJECT))
    parser.add_argument("--subscription", default=None,
                        help="subscription id to inspect or peek (e.g. ga4-events-sub)")
    parser.add_argument("--peek", type=int, default=0, metavar="N",
                        help="pull at most N messages without ack; stop the pipeline first")
    args = parser.parse_args()

    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    try:
        info = list_infrastructure(publisher, subscriber, args.project)
        for topic in info["topics"]:
            print(f"topic        : {topic}")
        for subscription in info["subscriptions"]:
            print(f"subscription : {subscription}")
        if not info["topics"] and not info["subscriptions"]:
            print(f"No Pub/Sub resources found in project {args.project}")

        if args.peek:
            if not args.subscription:
                print("--peek requires --subscription")
                return 1
            print("WARNING: peeking competes with the pipeline; use only while it is stopped")
            messages = peek_messages(subscriber, args.project,
                                     args.subscription, args.peek)
            if not messages:
                print("No backlog messages available")
            for message in messages:
                print(f"message {message['message_id']} @ {message['publish_time']}\n"
                      f"  {message['payload_preview']}")
            print(f"Pulled {len(messages)} messages WITHOUT ack; they will be redelivered")
    except Exception as err:
        print(f"Cannot inspect Pub/Sub: {err}")
        print("If using the emulator, check PUBSUB_EMULATOR_HOST and that it is running.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
