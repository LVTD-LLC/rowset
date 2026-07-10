import json
from types import SimpleNamespace

from django.test import RequestFactory, override_settings

from apps.core import stripe_webhooks
from apps.core import tasks as core_tasks
from apps.core import utils as core_utils
from apps.core.choices import EmailType
from apps.core.views import stripe_webhook
from apps.datasets import tasks as dataset_tasks


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_alias_log_contains_only_safe_completion_context(captured_events, monkeypatch):
    profile = SimpleNamespace(id=7, user=SimpleNamespace(email="private@example.com"))
    monkeypatch.setattr(core_tasks.Profile.objects, "get", lambda **_kwargs: profile)
    aliases = []
    monkeypatch.setattr(core_tasks.posthog, "alias", lambda *args: aliases.append(args))
    cookie = json.dumps({"distinct_id": "anonymous-private-id", "session_id": "private"})

    core_tasks.try_create_posthog_alias(
        7,
        {"ph_phc_test_posthog": cookie, "sessionid": "private-session-cookie"},
        source_function="signup",
    )

    event = captured_events.event("posthog.alias.completed")
    assert event == {
        "profile_id": 7,
        "source_function": "signup",
        "alias_found": True,
        "outcome": "success",
        "event": "posthog.alias.completed",
        "project": "rowset",
        "logger": "rowset.apps.core.tasks",
        "level": "info",
        "timestamp": event["timestamp"],
    }
    assert len(aliases) == 2
    assert "private@example.com" not in str(event)
    assert "anonymous-private-id" not in str(event)
    assert "private-session-cookie" not in str(event)


@override_settings(POSTHOG_API_KEY="phc_test")
def test_posthog_event_log_records_property_count_not_property_values(captured_events, monkeypatch):
    profile = SimpleNamespace(
        id=7,
        state="signed_up",
        user=SimpleNamespace(email="private@example.com"),
    )
    monkeypatch.setattr(core_tasks.Profile.objects, "get", lambda **_kwargs: profile)
    monkeypatch.setattr(core_tasks.posthog, "capture", lambda *args, **kwargs: None)

    core_tasks.track_event(
        7,
        "dataset_created",
        {"private_value": "dataset contents", "dataset_id": 3},
        source_function="test",
    )

    event = captured_events.event("posthog.event.completed")
    assert event["properties_count"] == 2
    assert "properties" not in event
    assert "dataset contents" not in str(event)


def test_email_tracking_log_uses_profile_identity_not_email(captured_events, monkeypatch):
    monkeypatch.setattr(
        "apps.core.models.EmailSent.objects.create",
        lambda **_kwargs: SimpleNamespace(id=12),
    )

    core_utils.track_email_sent(
        "private@example.com",
        EmailType.WELCOME,
        profile=SimpleNamespace(id=7),
    )

    event = captured_events.event("email.tracking.completed")
    assert event["profile_id"] == 7
    assert event["email_sent_id"] == 12
    assert event["outcome"] == "success"
    assert "email_address" not in event
    assert "private@example.com" not in str(event)


def test_stripe_webhook_does_not_log_django_request_object(captured_events):
    response = stripe_webhook(RequestFactory().get("/stripe/webhook/"))

    assert response.status_code == 405
    assert not any(event.get("event") == "Stripe webhook received" for event in captured_events)


def test_stripe_checkout_log_replaces_arbitrary_metadata_with_count(captured_events):
    event = {
        "id": "evt_1",
        "data": {
            "object": {
                "id": "cs_1",
                "customer": "cus_1",
                "subscription": "sub_1",
                "payment_status": "unpaid",
                "mode": "subscription",
                "metadata": {"private": "dataset value", "plan": "pro"},
            }
        },
    }

    stripe_webhooks.handle_checkout_completed(event)

    log_event = captured_events.event("stripe.checkout.completed")
    assert log_event["metadata_count"] == 2
    assert "metadata" not in log_event
    assert "dataset value" not in str(log_event)


def test_vector_deletion_log_uses_count_instead_of_row_id_list(captured_events, monkeypatch):
    monkeypatch.setattr(dataset_tasks, "qdrant_is_enabled", lambda: True)

    def missing_dataset(**_kwargs):
        raise dataset_tasks.Dataset.DoesNotExist

    monkeypatch.setattr(dataset_tasks.Dataset.objects, "get", missing_dataset)

    dataset_tasks.delete_dataset_row_vectors(9, [11, 12, 13])

    event = captured_events.event("Skipping vector row deletion for missing dataset")
    assert event["dataset_id"] == 9
    assert event["row_count"] == 3
    assert "row_ids" not in event
