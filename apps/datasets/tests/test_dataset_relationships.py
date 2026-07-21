import csv
import io
import re

import pytest
from django.urls import reverse

from apps.datasets.choices import DatasetMutationType
from apps.datasets.models import DatasetRelationship, DatasetRow
from apps.datasets.tests.dataset_test_helpers import create_crm_datasets

pytestmark = pytest.mark.django_db


def test_dataset_row_detail_links_relationship_value_to_target_row(auth_client, profile):
    people, messages = create_crm_datasets(profile)
    relationship = DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Message person",
        source_column="person_id",
        target_index_column="person_id",
        enforce_integrity=True,
    )
    message_row = messages.rows.get(index_value="M-1")
    person_row = people.rows.get(index_value="P-1")

    response = auth_client.get(reverse("dataset_row_detail", args=[messages.key, message_row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    target_url = reverse("dataset_row_detail", args=[people.key, person_row.id])
    assert f'href="{target_url}"' in content
    assert f"View related People row 1 via {relationship.name}" in content
    assert re.search(r"<a[^>]+>\s*P-1\s*</a>", content) is not None


def test_dataset_row_detail_leaves_unresolved_relationship_value_unlinked(auth_client, profile):
    people, messages = create_crm_datasets(profile)
    DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Optional message person",
        source_column="person_id",
        target_index_column="person_id",
        enforce_integrity=False,
    )
    message_row = messages.rows.get(index_value="M-1")
    message_row.data["person_id"] = "P-missing"
    message_row.save(update_fields=["data"])

    response = auth_client.get(reverse("dataset_row_detail", args=[messages.key, message_row.id]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "P-missing" in content
    assert "View related People" not in content
    assert not re.search(r"<a[^>]+>\s*P-missing\s*</a>", content)


def test_dataset_relationship_api_creates_lists_resolves_and_enforces_rows(api_client, profile):
    people, messages = create_crm_datasets(profile)

    create_response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "name": "Message person",
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201
    relationship_payload = create_response.json()["relationship"]
    relationship_key = relationship_payload["key"]
    assert relationship_payload["source_column"] == "person_id"
    assert relationship_payload["target_dataset"]["key"] == str(people.key)
    assert relationship_payload["target_index_column"] == "person_id"
    assert relationship_payload["enforce_integrity"] is True
    relationship = DatasetRelationship.objects.get(key=relationship_key)
    assert relationship.source_dataset == messages
    assert relationship.target_dataset == people

    list_response = api_client.get(f"/api/datasets/{messages.key}/relationships")
    assert list_response.status_code == 200
    assert [item["key"] for item in list_response.json()["relationships"]] == [relationship_key]

    resolve_response = api_client.get(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}/resolve"
        "?source_index_value=M-1"
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["target_index_value"] == "P-1"
    assert resolve_response.json()["target_row"]["data"]["name"] == "Ada Lovelace"

    invalid_key_response = api_client.get(
        f"/api/datasets/{messages.key}/relationships/not-a-key/resolve?source_index_value=M-1"
    )
    assert invalid_key_response.status_code == 400
    assert invalid_key_response.json()["detail"] == "Invalid relationship key."

    invalid_row_response = api_client.post(
        f"/api/datasets/{messages.key}/rows",
        data={
            "data": {
                "message_id": "M-2",
                "person_id": "P-404",
                "body": "Missing person.",
            }
        },
        content_type="application/json",
    )
    assert invalid_row_response.status_code == 400
    assert "references a missing row" in invalid_row_response.json()["detail"]
    assert messages.rows.filter(index_value="M-2").exists() is False

    blank_row_response = api_client.post(
        f"/api/datasets/{messages.key}/rows",
        data={
            "data": {
                "message_id": "M-2",
                "person_id": "",
                "body": "Unmatched message.",
            }
        },
        content_type="application/json",
    )
    assert blank_row_response.status_code == 200

    delete_response = api_client.delete(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}"
    )
    assert delete_response.status_code == 200
    assert not DatasetRelationship.objects.filter(key=relationship_key).exists()
    delete_mutation = messages.mutations.get(mutation_type=DatasetMutationType.RELATIONSHIP_DELETED)
    assert delete_mutation.metadata["enforce_integrity"] is True


def test_dataset_relationship_api_rejects_existing_unmatched_values(api_client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.create(
        row_number=2,
        index_value="M-2",
        data={
            "message_id": "M-2",
            "person_id": "P-404",
            "body": "Unmatched.",
        },
    )
    messages.row_count = 2
    messages.save(update_fields=["row_count"])

    response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "without a matching row" in response.json()["detail"]
    assert not DatasetRelationship.objects.filter(source_dataset=messages).exists()


def test_dataset_relationship_api_resolves_unenforced_orphan_as_null(api_client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.create(
        row_number=2,
        index_value="M-2",
        data={
            "message_id": "M-2",
            "person_id": "P-404",
            "body": "Unmatched.",
        },
    )
    messages.row_count = 2
    messages.save(update_fields=["row_count"])
    create_response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": False,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    relationship_key = create_response.json()["relationship"]["key"]

    resolve_response = api_client.get(
        f"/api/datasets/{messages.key}/relationships/{relationship_key}/resolve"
        "?source_index_value=M-2"
    )

    assert resolve_response.status_code == 200
    assert resolve_response.json()["target_index_value"] == "P-404"
    assert resolve_response.json()["target_row"] is None


def test_dataset_relationship_count_calculated_column_reads_live_counts(api_client, profile):
    people, messages = create_crm_datasets(profile)
    DatasetRow.objects.create(
        dataset=people,
        row_number=2,
        index_value="P-2",
        data={
            "person_id": "P-2",
            "name": "Grace Hopper",
            "email": "grace@example.com",
        },
    )
    people.row_count = 2
    people.save(update_fields=["row_count"])
    DatasetRow.objects.bulk_create(
        [
            DatasetRow(
                dataset=messages,
                row_number=2,
                index_value="M-2",
                data={
                    "message_id": "M-2",
                    "person_id": " P-1 ",
                    "body": "Follow-up call.",
                },
            ),
            DatasetRow(
                dataset=messages,
                row_number=3,
                index_value="M-3",
                data={
                    "message_id": "M-3",
                    "person_id": "P-2",
                    "body": "WhatsApp check-in.",
                },
            ),
        ]
    )
    messages.row_count = 3
    messages.save(update_fields=["row_count"])
    relationship_response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "name": "Connection person",
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )
    relationship_key = relationship_response.json()["relationship"]["key"]

    add_column_response = api_client.post(
        f"/api/datasets/{people.key}/columns",
        data={
            "name": "connection_count",
            "column_type": {
                "type": "calculated",
                "calculation": "relationship_count",
                "relationship_key": relationship_key,
            },
        },
        content_type="application/json",
    )

    assert add_column_response.status_code == 200
    assert add_column_response.json()["dataset"]["headers"] == [
        "person_id",
        "name",
        "email",
        "connection_count",
    ]
    assert add_column_response.json()["dataset"]["column_schema"]["connection_count"] == {
        "type": "calculated",
        "calculation": "relationship_count",
        "relationship_key": relationship_key,
    }
    people.refresh_from_db()
    assert people.rows.filter(data__has_key="connection_count").exists() is False

    list_response = api_client.get(
        f"/api/datasets/{people.key}/rows?sort=connection_count&direction=desc"
    )

    assert list_response.status_code == 200
    rows = list_response.json()["rows"]
    assert [row["index_value"] for row in rows] == ["P-1", "P-2"]
    assert rows[0]["data"]["connection_count"] == "2"
    assert rows[1]["data"]["connection_count"] == "1"

    new_connection_response = api_client.post(
        f"/api/datasets/{messages.key}/rows",
        data={
            "data": {
                "message_id": "M-4",
                "person_id": "P-2",
                "body": "Phone call.",
            }
        },
        content_type="application/json",
    )
    assert new_connection_response.status_code == 200

    row_response = api_client.get(f"/api/datasets/{people.key}/rows/by-index?index_value=P-2")
    assert row_response.status_code == 200
    assert row_response.json()["row"]["data"]["connection_count"] == "2"

    create_person_response = api_client.post(
        f"/api/datasets/{people.key}/rows",
        data={
            "data": {
                "person_id": "P-3",
                "name": "Katherine Johnson",
                "email": "katherine@example.com",
                "connection_count": "99",
            }
        },
        content_type="application/json",
    )
    assert create_person_response.status_code == 200
    assert create_person_response.json()["row"]["data"]["connection_count"] == "0"
    assert "connection_count" not in people.rows.get(index_value="P-3").data

    export_response = api_client.get(f"/api/datasets/{people.key}/export.csv")
    assert export_response.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(export_response.content.decode())))
    assert csv_rows[0]["connection_count"] == "2"
    assert csv_rows[1]["connection_count"] == "2"
    assert csv_rows[2]["connection_count"] == "0"


def test_dataset_relationship_delete_rejects_calculated_column_dependency(api_client, profile):
    people, messages = create_crm_datasets(profile)
    relationship = DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Connection person",
        source_column="person_id",
        target_index_column=people.index_column,
        enforce_integrity=True,
    )
    people.headers = [*people.headers, "connection_count"]
    people.column_schema = {
        **people.column_schema,
        "connection_count": {
            "type": "calculated",
            "calculation": "relationship_count",
            "relationship_key": str(relationship.key),
        },
    }
    people.save(update_fields=["headers", "column_schema"])

    response = api_client.delete(f"/api/datasets/{messages.key}/relationships/{relationship.key}")

    assert response.status_code == 409
    assert "calculated column 'connection_count'" in response.json()["detail"]
    assert DatasetRelationship.objects.filter(pk=relationship.pk).exists()


def test_dataset_owner_can_create_relationship_count_column_from_settings(auth_client, profile):
    people, messages = create_crm_datasets(profile)
    relationship = DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Connection person",
        source_column="person_id",
        target_index_column=people.index_column,
        enforce_integrity=True,
    )

    response = auth_client.post(
        reverse(
            "dataset_create_relationship_count_column",
            args=[people.key, relationship.key],
        ),
        {"column_name": "connection_count"},
    )

    assert response.status_code == 302
    people.refresh_from_db()
    assert people.headers == ["person_id", "name", "email", "connection_count"]
    assert people.column_schema["connection_count"] == {
        "type": "calculated",
        "calculation": "relationship_count",
        "relationship_key": str(relationship.key),
    }
    assert people.rows.filter(data__has_key="connection_count").exists() is False

    settings_response = auth_client.get(reverse("dataset_settings", args=[people.key]))

    assert settings_response.status_code == 200
    content = settings_response.content.decode()
    assert "Count column · connection_count" in content
    assert "Count rows" not in content


def test_dataset_api_rejects_calculated_column_for_non_incoming_relationship(api_client, profile):
    people, messages = create_crm_datasets(profile)
    relationship = DatasetRelationship.objects.create(
        profile=profile,
        source_dataset=messages,
        target_dataset=people,
        name="Connection person",
        source_column="person_id",
        target_index_column=people.index_column,
        enforce_integrity=True,
    )

    response = api_client.post(
        f"/api/datasets/{messages.key}/columns",
        data={
            "name": "connection_count",
            "column_type": {
                "type": "calculated",
                "calculation": "relationship_count",
                "relationship_key": str(relationship.key),
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "incoming relationship for this dataset" in response.json()["detail"]


def test_dataset_relationship_api_blocks_target_row_delete_when_enforced(api_client, profile):
    people, messages = create_crm_datasets(profile)
    messages.rows.filter(index_value="M-1").update(
        data={
            "message_id": "M-1",
            "person_id": " P-1 ",
            "body": "Intro call completed.",
        }
    )
    create_response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    person_row = people.rows.get(index_value="P-1")

    delete_response = api_client.delete(f"/api/datasets/{people.key}/rows/{person_row.id}")

    assert delete_response.status_code == 409
    assert "referenced by relationship" in delete_response.json()["detail"]
    assert people.rows.filter(index_value="P-1").exists()


def test_dataset_relationship_api_blocks_target_index_change_when_enforced(api_client, profile):
    people, messages = create_crm_datasets(profile)
    create_response = api_client.post(
        f"/api/datasets/{messages.key}/relationships",
        data={
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": True,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    person_row = people.rows.get(index_value="P-1")

    patch_response = api_client.patch(
        f"/api/datasets/{people.key}/rows/{person_row.id}",
        data={
            "data": {
                "person_id": "P-2",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
            }
        },
        content_type="application/json",
    )

    assert patch_response.status_code == 409
    assert "referenced by relationship" in patch_response.json()["detail"]
    person_row.refresh_from_db()
    assert person_row.index_value == "P-1"


def test_dataset_relationship_settings_form_creates_and_detail_shows_relationship(
    auth_client,
    profile,
):
    people, messages = create_crm_datasets(profile)

    response = auth_client.post(
        reverse("dataset_create_relationship", args=[messages.key]),
        data={
            "name": "Message person",
            "source_column": "person_id",
            "target_dataset_key": str(people.key),
            "enforce_integrity": "on",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert DatasetRelationship.objects.filter(
        source_dataset=messages,
        target_dataset=people,
        source_column="person_id",
    ).exists()

    detail_response = auth_client.get(reverse("dataset_detail", args=[messages.key]))
    assert detail_response.status_code == 200
    content = detail_response.content.decode()
    details_match = re.search(
        r'<details\b[^>]*aria-labelledby="dataset-relationships-heading"[^>]*>',
        content,
    )
    assert details_match is not None
    assert not re.search(r"\sopen(?:[\s=>]|$)", details_match.group(0))
    assert "Show relationships" in content
    assert "Hide relationships" in content
    assert "Message person" in content
    assert f'href="{people.get_absolute_url()}"' in content
    assert "People</a>.person_id" in content
    assert "No incoming relationships." not in content

    incoming_response = auth_client.get(reverse("dataset_detail", args=[people.key]))
    incoming_content = incoming_response.content.decode()
    assert incoming_response.status_code == 200
    assert f'href="{messages.get_absolute_url()}"' in incoming_content
    assert "CRM Messages</a>.person_id" in incoming_content
    assert "No outgoing relationships." not in incoming_content
