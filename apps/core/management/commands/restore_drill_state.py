import hashlib
import json
import os
import sys
from pathlib import Path

from django.contrib.auth import authenticate, get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError

from apps.datasets.models import Dataset, DatasetAsset, DatasetRelationship, DatasetRow

DRILL_EMAIL = "restore-drill@example.invalid"
DRILL_PASSWORD = "rowset-restore-drill-only"
PUBLIC_ASSET = Path("/app/media/restore-drill/public.txt")
PRIVATE_PAYLOAD = b"rowset private restore drill asset\n"
PUBLIC_PAYLOAD = b"rowset public restore drill asset\n"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Command(BaseCommand):
    help = "Seed or verify the isolated backup/restore drill state."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("seed", "verify"))

    def handle(self, *args, **options):
        if os.environ.get("ROWSET_RESTORE_DRILL") != "1":
            raise CommandError("ROWSET_RESTORE_DRILL=1 is required")
        if options["action"] == "seed":
            self.stdout.write(json.dumps(self._seed(), sort_keys=True))
        else:
            self._verify(json.load(sys.stdin))
            self.stdout.write("Restore drill state verified.")

    def _seed(self) -> dict:
        user_model = get_user_model()
        if user_model.objects.filter(email=DRILL_EMAIL).exists():
            raise CommandError("Restore drill state already exists")
        user = user_model.objects.create_user(
            username="rowset-restore-drill",
            email=DRILL_EMAIL,
            password=DRILL_PASSWORD,
        )
        profile = user.profile
        people = Dataset.objects.create(
            profile=profile,
            name="Restore Drill People",
            headers=["person_id", "name"],
            index_column="person_id",
            row_count=1,
        )
        person = DatasetRow.objects.create(
            dataset=people,
            row_number=1,
            index_value="P-001",
            data={"person_id": "P-001", "name": "Restore Drill Person"},
        )
        messages = Dataset.objects.create(
            profile=profile,
            name="Restore Drill Messages",
            headers=["message_id", "person_id", "asset"],
            column_schema={"asset": {"type": "audio"}},
            index_column="message_id",
            row_count=1,
        )
        message = DatasetRow.objects.create(
            dataset=messages,
            row_number=1,
            index_value="M-001",
            data={"message_id": "M-001", "person_id": "P-001", "asset": ""},
        )
        relationship = DatasetRelationship.objects.create(
            profile=profile,
            source_dataset=messages,
            target_dataset=people,
            name="person",
            source_column="person_id",
            target_index_column="person_id",
        )
        asset = DatasetAsset(
            profile=profile,
            dataset=messages,
            row=message,
            column_name="asset",
            original_filename="drill.txt",
            content_type="application/octet-stream",
            byte_size=len(PRIVATE_PAYLOAD),
            checksum=_sha256(PRIVATE_PAYLOAD),
        )
        asset.file.save("drill.bin", ContentFile(PRIVATE_PAYLOAD), save=False)
        asset.save()
        if (
            not isinstance(asset.file.storage, FileSystemStorage)
            or not Path(asset.file.path).is_file()
        ):
            raise CommandError("Restore drill requires a local private-media asset")
        message.data["asset"] = asset.asset_ref
        message.save(update_fields=["data", "updated_at"])

        PUBLIC_ASSET.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_ASSET.write_bytes(PUBLIC_PAYLOAD)
        return {
            "user_id": user.id,
            "profile_key": profile.key,
            "people_key": str(people.key),
            "person_row_id": person.id,
            "messages_key": str(messages.key),
            "message_row_id": message.id,
            "relationship_key": str(relationship.key),
            "asset_key": str(asset.key),
            "private_checksum": _sha256(PRIVATE_PAYLOAD),
            "public_checksum": _sha256(PUBLIC_PAYLOAD),
            "counts": {
                "users": user_model.objects.count(),
                "datasets": Dataset.objects.filter(profile=profile).count(),
                "rows": DatasetRow.objects.filter(dataset__profile=profile).count(),
                "relationships": DatasetRelationship.objects.filter(profile=profile).count(),
                "assets": DatasetAsset.objects.filter(profile=profile).count(),
            },
        }

    def _verify(self, expected: dict) -> None:
        user_model = get_user_model()
        user = user_model.objects.get(id=expected["user_id"], email=DRILL_EMAIL)
        if user.profile.key != expected["profile_key"]:
            raise CommandError("Profile key changed during restore")
        if authenticate(username=user.username, password=DRILL_PASSWORD) is None:
            raise CommandError("Restored user cannot authenticate")

        people = Dataset.objects.get(key=expected["people_key"], profile=user.profile)
        messages = Dataset.objects.get(key=expected["messages_key"], profile=user.profile)
        person = people.rows.get(id=expected["person_row_id"], index_value="P-001")
        message = messages.rows.get(id=expected["message_row_id"], index_value="M-001")
        if message.data["person_id"] != person.index_value:
            raise CommandError("Restored relationship value changed")
        DatasetRelationship.objects.get(
            key=expected["relationship_key"],
            source_dataset=messages,
            target_dataset=people,
        )
        asset = DatasetAsset.objects.get(key=expected["asset_key"], row=message)
        with asset.file.open("rb") as asset_file:
            private_checksum = _sha256(asset_file.read())
        if private_checksum != expected["private_checksum"]:
            raise CommandError("Private asset checksum changed")
        if _sha256(PUBLIC_ASSET.read_bytes()) != expected["public_checksum"]:
            raise CommandError("Public media checksum changed")
        actual_counts = {
            "users": user_model.objects.count(),
            "datasets": Dataset.objects.filter(profile=user.profile).count(),
            "rows": DatasetRow.objects.filter(dataset__profile=user.profile).count(),
            "relationships": DatasetRelationship.objects.filter(profile=user.profile).count(),
            "assets": DatasetAsset.objects.filter(profile=user.profile).count(),
        }
        if actual_counts != expected["counts"]:
            raise CommandError(f"Restored object counts changed: {actual_counts}")
