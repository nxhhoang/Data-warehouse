"""Unit tests for the Pub/Sub inspection helper (fake clients only)."""

from types import SimpleNamespace

from scripts.pubsub_status import list_infrastructure, peek_messages


class FakePublisher:
    def project_path(self, project_id):
        return f"projects/{project_id}"

    def list_topics(self, request):
        assert request["project"] == "projects/test-project"
        return [SimpleNamespace(name="projects/test-project/topics/ga4-events")]


class FakeSubscriber:
    def project_path(self, project_id):
        return f"projects/{project_id}"

    def list_subscriptions(self, request):
        return [SimpleNamespace(name="projects/test-project/subscriptions/ga4-events-sub")]

    def subscription_path(self, project_id, subscription_id):
        return f"projects/{project_id}/subscriptions/{subscription_id}"

    def pull(self, subscription, max_messages, return_immediately):
        assert max_messages == 1
        message = SimpleNamespace(
            data=b'{"event_name": "purchase"}',
            message_id="message-1",
            publish_time="2026-01-01T00:00:00Z",
        )
        return SimpleNamespace(received_messages=[
            SimpleNamespace(message=message, ack_id="ack-1")
        ])

    def ack(self, **kwargs):
        raise AssertionError("peek must never ack messages")


class TestInfrastructure:
    def test_lists_both_resources(self):
        info = list_infrastructure(FakePublisher(), FakeSubscriber(), "test-project")
        assert info["topics"] == ["projects/test-project/topics/ga4-events"]
        assert info["subscriptions"] == [
            "projects/test-project/subscriptions/ga4-events-sub"
        ]


class TestPeek:
    def test_returns_message_preview_without_ack(self):
        messages = peek_messages(FakeSubscriber(), "test-project", "sub", 1)
        assert messages[0]["message_id"] == "message-1"
        assert messages[0]["payload_preview"] == '{"event_name": "purchase"}'
        assert messages[0]["ack_id"] == "ack-1"
