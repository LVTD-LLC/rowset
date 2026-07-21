import base64

import pytest
from django.core.files.storage import storages
from django.urls import reverse

from apps.api.services import DatasetServiceError, attach_profile_dataset_image_asset
from apps.datasets.choices import DatasetColumnType
from apps.datasets.constants import MAX_DATASET_IMAGE_BYTES
from apps.datasets.models import (
    DATASET_ASSET_STORAGE_ALIAS,
    Dataset,
    DatasetAsset,
    DatasetAssetFileDeletion,
    DatasetRow,
    retry_dataset_asset_file_deletions,
)
from apps.datasets.services import (
    DatasetAudioError,
    DatasetImageError,
    decode_audio_base64,
    decode_image_base64,
    prepare_dataset_audio,
    prepare_dataset_image,
)
from apps.datasets.tests.dataset_test_helpers import (
    audio_base64,
    audio_bytes,
    create_ready_dataset,
    image_base64,
    image_bytes,
    palette_image_bytes,
)

pytestmark = pytest.mark.django_db


def test_prepare_dataset_image_rejects_encoded_payload_above_limit(monkeypatch):
    source_bytes = image_bytes()

    monkeypatch.setattr(
        "apps.datasets.services.MAX_DATASET_IMAGE_BYTES",
        len(source_bytes) + 1,
    )
    monkeypatch.setattr(
        "apps.datasets.services._encoded_image_bytes",
        lambda image, image_format: b"x" * (len(source_bytes) + 2),
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=source_bytes,
            filename="photo.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_decoded_payload_above_limit():
    image_base64 = base64.b64encode(b"x" * (MAX_DATASET_IMAGE_BYTES + 1)).decode()

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=decode_image_base64(image_base64),
            filename="large.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_malformed_image_data():
    image_base64 = base64.b64encode(b"not really an image").decode()

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=decode_image_base64(image_base64),
            filename="broken.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_content_type_mismatch():
    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=image_bytes(),
            filename="photo.jpg",
            content_type="image/jpeg",
        )


def test_prepare_dataset_image_rejects_images_over_pixel_limit(monkeypatch):
    monkeypatch.setattr("apps.datasets.services.MAX_DATASET_IMAGE_PIXELS", 5)

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=image_bytes(),
            filename="photo.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_zero_dimension_image(monkeypatch):
    class FakeImage:
        format = "PNG"
        size = (0, 1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def load(self):
            return None

    fake_image = FakeImage()
    monkeypatch.setattr("apps.datasets.services.Image.open", lambda data: fake_image)
    monkeypatch.setattr(
        "apps.datasets.services.ImageOps.exif_transpose",
        lambda image: image,
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=b"fake",
            filename="zero.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_rejects_exif_transposed_image_over_pixel_limit(monkeypatch):
    class FakeImage:
        format = "PNG"

        def __init__(self, size):
            self.size = size

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def load(self):
            return None

    opened_image = FakeImage((1, 1))
    transposed_image = FakeImage((3, 3))
    monkeypatch.setattr("apps.datasets.services.MAX_DATASET_IMAGE_PIXELS", 5)
    monkeypatch.setattr("apps.datasets.services.Image.open", lambda data: opened_image)
    monkeypatch.setattr(
        "apps.datasets.services.ImageOps.exif_transpose",
        lambda image: transposed_image,
    )

    with pytest.raises(DatasetImageError):
        prepare_dataset_image(
            image_bytes=b"fake",
            filename="rotated.png",
            content_type="image/png",
        )


def test_prepare_dataset_image_accepts_palette_png():
    prepared = prepare_dataset_image(
        image_bytes=palette_image_bytes(),
        filename="palette.png",
        content_type="image/png",
    )

    assert prepared.content_type == "image/png"
    assert prepared.width == 3
    assert prepared.height == 2
    assert prepared.image_bytes.startswith(b"\x89PNG")


def test_prepare_dataset_image_skips_larger_thumbnail_for_tiny_png():
    prepared = prepare_dataset_image(
        image_bytes=image_bytes(),
        filename="tiny.png",
        content_type="image/png",
    )

    assert prepared.thumbnail_bytes is None


def test_prepare_dataset_audio_accepts_wav_data_uri():
    prepared = prepare_dataset_audio(
        audio_bytes=decode_audio_base64(f"data:audio/wav;base64,{audio_base64()}"),
        filename="intro",
        content_type="audio/wav",
    )

    assert prepared.filename == "intro.wav"
    assert prepared.content_type == "audio/wav"
    assert prepared.audio_bytes.startswith(b"RIFF")
    assert prepared.byte_size == len(prepared.audio_bytes)
    assert len(prepared.checksum) == 64


def test_prepare_dataset_audio_rejects_payload_above_limit(monkeypatch):
    monkeypatch.setattr(
        "apps.datasets.services.MAX_DATASET_AUDIO_BYTES",
        len(audio_bytes()) - 1,
    )

    with pytest.raises(DatasetAudioError):
        prepare_dataset_audio(
            audio_bytes=audio_bytes(),
            filename="large.wav",
            content_type="audio/wav",
        )


def test_prepare_dataset_audio_rejects_malformed_audio_data():
    with pytest.raises(DatasetAudioError):
        prepare_dataset_audio(
            audio_bytes=decode_audio_base64(base64.b64encode(b"not really audio").decode()),
            filename="broken.wav",
            content_type="audio/wav",
        )


def test_prepare_dataset_audio_rejects_content_type_mismatch():
    with pytest.raises(DatasetAudioError):
        prepare_dataset_audio(
            audio_bytes=audio_bytes(),
            filename="clip.mp3",
            content_type="audio/mpeg",
        )


def test_image_attach_records_failed_rollback_file_cleanup(profile, monkeypatch):
    dataset = Dataset.objects.create(
        profile=profile,
        name="Image cleanup",
        headers=["sku", "photo"],
        column_schema={"photo": {"type": DatasetColumnType.IMAGE}},
        index_column="sku",
        row_count=1,
    )
    DatasetRow.objects.create(
        dataset=dataset,
        row_number=1,
        index_value="A-1",
        data={"sku": "A-1", "photo": ""},
    )
    storage = storages[DATASET_ASSET_STORAGE_ALIAS]
    saved_names = []
    deleted_names = []

    class PreparedImage:
        filename = "photo.png"
        content_type = "image/png"
        image_bytes = b"original"
        thumbnail_bytes = b"thumbnail"
        byte_size = len(image_bytes)
        width = 3
        height = 2
        checksum = "a" * 64

    def fail_thumbnail_save(name: str, content, *args, **kwargs) -> str:
        saved_names.append(name)
        if name.endswith("thumbnail.jpg"):
            raise OSError("thumbnail upload failed")
        return name

    def fail_delete(name: str) -> None:
        deleted_names.append(name)
        raise OSError("delete failed")

    monkeypatch.setattr(
        "apps.api.services.prepare_dataset_image",
        lambda **kwargs: PreparedImage(),
    )
    monkeypatch.setattr(storage, "save", fail_thumbnail_save)
    monkeypatch.setattr(storage, "delete", fail_delete)

    with pytest.raises(DatasetServiceError) as exc_info:
        attach_profile_dataset_image_asset(
            profile,
            str(dataset.key),
            column_name="photo",
            image_base64=image_base64(),
            index_value="A-1",
        )

    assert exc_info.value.status_code == 500
    assert len(saved_names) == 2
    assert deleted_names == [saved_names[0]]
    deletion = DatasetAssetFileDeletion.objects.get(file_name=saved_names[0])
    assert deletion.storage_alias == DATASET_ASSET_STORAGE_ALIAS
    assert deletion.attempts == 1
    assert "delete failed" in deletion.last_error
    assert DatasetAsset.objects.filter(dataset=dataset).count() == 0


def test_dataset_asset_delete_records_failed_file_cleanup(
    profile,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    dataset = create_ready_dataset(profile)
    row = dataset.rows.first()
    asset = DatasetAsset.objects.create(
        profile=profile,
        dataset=dataset,
        row=row,
        column_name="photo",
        file="dataset-assets/test/original.png",
        thumbnail="dataset-assets/test/thumbnail.jpg",
        content_type="image/png",
        byte_size=10,
        width=3,
        height=2,
        checksum="a" * 64,
    )
    storage = storages[DATASET_ASSET_STORAGE_ALIAS]
    deleted_names = []

    def fail_original_delete(name: str) -> None:
        deleted_names.append(name)
        if name == asset.file.name:
            raise OSError("r2 timeout")

    monkeypatch.setattr(storage, "delete", fail_original_delete)

    with django_capture_on_commit_callbacks(execute=True):
        asset.delete()

    assert deleted_names == [asset.file.name, asset.thumbnail.name]
    deletion = DatasetAssetFileDeletion.objects.get(file_name=asset.file.name)
    assert deletion.storage_alias == DATASET_ASSET_STORAGE_ALIAS
    assert deletion.attempts == 1
    assert deletion.deleted_at is None
    assert "r2 timeout" in deletion.last_error
    assert not DatasetAssetFileDeletion.objects.filter(file_name=asset.thumbnail.name).exists()

    retry_deleted_names = []
    monkeypatch.setattr(storage, "delete", retry_deleted_names.append)

    result = retry_dataset_asset_file_deletions()

    assert result == {"attempted": 1, "deleted": 1, "failed": 0}
    assert retry_deleted_names == [asset.file.name]
    deletion.refresh_from_db()
    assert deletion.deleted_at is not None
    assert deletion.last_error == ""


def test_dataset_api_attaches_image_asset_and_serves_content(api_client, profile, monkeypatch):
    create_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Product photos",
            "headers": ["sku", "name", "photo"],
            "index_column": "sku",
            "column_types": {
                "photo": {
                    "type": "image",
                    "description": "Primary product photo",
                }
            },
            "rows": [{"sku": "A-1", "name": "Adapter", "photo": ""}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    assert create_response.json()["dataset"]["public_enabled"] is False
    assert create_response.json()["dataset"]["public_url"] is None
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    attach_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows/by-index/image?index_value=A-1",
        data={
            "column_name": "photo",
            "filename": "adapter.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )

    assert attach_response.status_code == 200
    payload = attach_response.json()
    asset_payload = payload["asset"]
    asset = DatasetAsset.objects.get(key=asset_payload["key"], dataset=dataset)
    row = dataset.rows.get(index_value="A-1")
    row.refresh_from_db()
    assert payload["row"]["data"]["photo"] == asset.asset_ref
    assert row.data["photo"] == asset.asset_ref
    assert asset_payload["ref"] == asset.asset_ref
    assert asset_payload["content_type"] == "image/png"
    assert asset_payload["width"] == 3
    assert asset_payload["height"] == 2
    assert asset_payload["has_thumbnail"] is False
    assert asset_payload["thumbnail_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=thumbnail"
    )
    assert asset_payload["content_url_auth_required"] is True
    assert asset_payload["public_enabled"] is False
    assert asset_payload["public_content_url"] is None
    assert asset_payload["public_thumbnail_url"] is None
    assert asset_payload["content_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
    )
    assert asset.file.name.endswith("/original.png")
    assert asset.thumbnail.name == ""
    assert payload["row"]["assets"][0]["ref"] == asset.asset_ref
    assert payload["row"]["assets"][0]["column"] == "photo"

    def fail_head_file_open(*args, **kwargs):
        raise AssertionError("HEAD requests should not read image asset bytes.")

    def fail_public_head_work(*args, **kwargs):
        raise AssertionError("Public preview HEAD should not build row display state.")

    metadata_response = api_client.get(f"/api/datasets/{dataset.key}/assets/{asset.key}")
    assert metadata_response.status_code == 200
    assert metadata_response.json()["asset"]["ref"] == asset.asset_ref
    assert metadata_response.json()["asset"]["has_thumbnail"] is False
    assert metadata_response.json()["asset"]["thumbnail_url"].endswith(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=thumbnail"
    )
    assert metadata_response.json()["asset"]["public_content_url"] is None

    unauthenticated_head_response = api_client.head(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original",
        HTTP_AUTHORIZATION="",
    )
    assert unauthenticated_head_response.status_code == 401

    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            storages[DATASET_ASSET_STORAGE_ALIAS],
            "open",
            fail_head_file_open,
        )
        original_head_response = api_client.head(
            f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
        )
    assert original_head_response.status_code == 200
    assert original_head_response["Content-Type"] == "image/png"

    list_response = api_client.get(f"/api/datasets/{dataset.key}/rows")
    assert list_response.status_code == 200
    assert list_response.json()["rows"][0]["assets"][0]["ref"] == asset.asset_ref

    row_response = api_client.get(f"/api/datasets/{dataset.key}/rows/by-index?index_value=A-1")
    assert row_response.status_code == 200
    assert row_response.json()["row"]["assets"][0]["ref"] == asset.asset_ref

    original_response = api_client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
    )
    assert original_response.status_code == 200
    assert original_response["Content-Type"] == "image/png"
    assert original_response["X-Content-Type-Options"] == "nosniff"
    assert original_response["Cache-Control"] == "private, max-age=86400, immutable"
    assert original_response.content.startswith(b"\x89PNG")

    thumbnail_response = api_client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=thumbnail"
    )
    assert thumbnail_response.status_code == 200
    assert thumbnail_response["Content-Type"] == "image/png"
    assert thumbnail_response["Cache-Control"] == "private, max-age=86400, immutable"
    assert thumbnail_response.content.startswith(b"\x89PNG")

    api_client.force_login(profile.user)
    dataset_detail = api_client.get(dataset.get_absolute_url())
    detail_content = dataset_detail.content.decode()
    assert dataset_detail.status_code == 200
    assert "adapter.png" in detail_content
    assert reverse("dataset_asset_content", args=[dataset.key, asset.key]) in detail_content

    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    public_metadata_response = api_client.get(f"/api/datasets/{dataset.key}/assets/{asset.key}")
    public_asset_payload = public_metadata_response.json()["asset"]
    assert public_asset_payload["public_enabled"] is True
    assert public_asset_payload["public_content_url"].endswith(
        f"/share/datasets/{dataset.public_key}/assets/{asset.key}/content/?variant=original"
    )
    assert public_asset_payload["public_thumbnail_url"].endswith(
        f"/share/datasets/{dataset.public_key}/assets/{asset.key}/content/?variant=thumbnail"
    )
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            "apps.datasets.views._dataset_row_query_context",
            fail_public_head_work,
        )
        public_head_response = api_client.head(dataset.get_public_url())
    assert public_head_response.status_code == 200
    public_response = api_client.get(dataset.get_public_url())
    public_content = public_response.content.decode()
    assert public_response.status_code == 200
    assert "adapter.png" in public_content
    assert (
        reverse("public_dataset_asset_content", args=[dataset.public_key, asset.key])
        in public_content
    )
    public_asset_response = api_client.get(
        f"{reverse('public_dataset_asset_content', args=[dataset.public_key, asset.key])}"
        "?variant=thumbnail"
    )
    assert public_asset_response.status_code == 200
    assert public_asset_response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            storages[DATASET_ASSET_STORAGE_ALIAS],
            "open",
            fail_head_file_open,
        )
        public_asset_head_response = api_client.head(
            f"{reverse('public_dataset_asset_content', args=[dataset.public_key, asset.key])}"
            "?variant=thumbnail"
        )
    assert public_asset_head_response.status_code == 200
    assert public_asset_head_response["Content-Type"] == "image/png"

    public_row_response = api_client.get(
        reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
    )
    assert public_row_response.status_code == 200
    assert "adapter.png" in public_row_response.content.decode()
    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            "apps.datasets.views._row_cells",
            fail_public_head_work,
        )
        public_row_head_response = api_client.head(
            reverse("public_dataset_row_detail", args=[dataset.public_key, row.id])
        )
    assert public_row_head_response.status_code == 200

    password_response = api_client.patch(
        f"/api/datasets/{dataset.key}/public-preview",
        data={"public_enabled": True, "public_password": "secret-table"},
        content_type="application/json",
    )
    assert password_response.status_code == 200
    password_metadata_response = api_client.get(f"/api/datasets/{dataset.key}/assets/{asset.key}")
    password_asset_payload = password_metadata_response.json()["asset"]
    assert password_asset_payload["public_enabled"] is True
    assert password_asset_payload["public_password_protected"] is True
    assert password_asset_payload["public_content_url"] is None
    assert password_asset_payload["public_thumbnail_url"] is None


def test_dataset_api_attaches_audio_asset_and_serves_content(api_client, profile, monkeypatch):
    create_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Interview clips",
            "headers": ["clip_id", "title", "audio"],
            "index_column": "clip_id",
            "column_types": {
                "audio": {
                    "type": "audio",
                    "description": "Original interview clip",
                }
            },
            "rows": [{"clip_id": "C-1", "title": "Intro", "audio": ""}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    attach_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows/by-index/audio?index_value=C-1",
        data={
            "column_name": "audio",
            "filename": "intro.wav",
            "content_type": "audio/wav",
            "audio_base64": audio_base64(),
        },
        content_type="application/json",
    )

    assert attach_response.status_code == 200
    payload = attach_response.json()
    asset_payload = payload["asset"]
    asset = DatasetAsset.objects.get(key=asset_payload["key"], dataset=dataset)
    row = dataset.rows.get(index_value="C-1")
    row.refresh_from_db()
    assert payload["message"] == "Audio attached."
    assert payload["row"]["data"]["audio"] == asset.asset_ref
    assert row.data["audio"] == asset.asset_ref
    assert asset_payload["ref"] == asset.asset_ref
    assert asset_payload["content_type"] == "audio/wav"
    assert asset_payload["width"] is None
    assert asset_payload["height"] is None
    assert asset_payload["has_thumbnail"] is False
    assert asset.file.name.endswith("/original.wav")
    assert asset.thumbnail.name == ""
    assert payload["row"]["assets"][0]["ref"] == asset.asset_ref
    assert payload["row"]["assets"][0]["column"] == "audio"

    def fail_head_file_open(*args, **kwargs):
        raise AssertionError("HEAD requests should not read audio asset bytes.")

    with monkeypatch.context() as head_monkeypatch:
        head_monkeypatch.setattr(
            storages[DATASET_ASSET_STORAGE_ALIAS],
            "open",
            fail_head_file_open,
        )
        head_response = api_client.head(
            f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
        )
    assert head_response.status_code == 200
    assert head_response["Content-Type"] == "audio/wav"

    content_response = api_client.get(
        f"/api/datasets/{dataset.key}/assets/{asset.key}/content?variant=original"
    )
    assert content_response.status_code == 200
    assert content_response["Content-Type"] == "audio/wav"
    assert content_response["X-Content-Type-Options"] == "nosniff"
    assert content_response["Cache-Control"] == "private, max-age=86400, immutable"
    assert content_response.content.startswith(b"RIFF")

    api_client.force_login(profile.user)
    dataset_detail = api_client.get(dataset.get_absolute_url())
    detail_content = dataset_detail.content.decode()
    assert dataset_detail.status_code == 200
    assert "intro.wav" in detail_content
    assert "<audio" in detail_content
    assert reverse("dataset_asset_content", args=[dataset.key, asset.key]) in detail_content

    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])
    public_response = api_client.get(dataset.get_public_url())
    public_content = public_response.content.decode()
    assert public_response.status_code == 200
    assert "intro.wav" in public_content
    assert "<audio" in public_content
    assert (
        reverse("public_dataset_asset_content", args=[dataset.public_key, asset.key])
        in public_content
    )


def test_dataset_api_rejects_direct_image_values_and_clears_asset(api_client, profile):
    create_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Receipts",
            "headers": ["receipt_id", "image"],
            "index_column": "receipt_id",
            "column_types": {"image": "image"},
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    invalid_create = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"receipt_id": "R-1", "image": "https://example.com/receipt.png"}},
        content_type="application/json",
    )
    assert invalid_create.status_code == 400
    assert invalid_create.json()["detail"] == (
        "Column 'image' is an image column. Leave it blank and attach an image asset."
    )

    create_row = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"receipt_id": "R-1", "image": ""}},
        content_type="application/json",
    )
    assert create_row.status_code == 200
    row_id = create_row.json()["row"]["id"]

    attach_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows/{row_id}/image",
        data={
            "column_name": "image",
            "filename": "receipt.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )
    assert attach_response.status_code == 200
    asset = DatasetAsset.objects.get(key=attach_response.json()["asset"]["key"])

    idempotent_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"image": asset.asset_ref}},
        content_type="application/json",
    )
    assert idempotent_patch.status_code == 200
    assert idempotent_patch.json()["row"]["data"]["image"] == asset.asset_ref
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    invalid_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"image": "asset:00000000-0000-0000-0000-000000000000"}},
        content_type="application/json",
    )
    assert invalid_patch.status_code == 400
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    invalid_clear = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"receipt_id": "", "image": ""}},
        content_type="application/json",
    )
    assert invalid_clear.status_code == 400
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    clear_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"image": ""}},
        content_type="application/json",
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["row"]["data"]["image"] == ""
    assert not DatasetAsset.objects.filter(pk=asset.pk).exists()


def test_dataset_api_rejects_direct_audio_values_and_clears_asset(api_client, profile):
    create_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Clips",
            "headers": ["clip_id", "audio"],
            "index_column": "clip_id",
            "column_types": {"audio": "audio"},
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)

    invalid_create = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"clip_id": "C-1", "audio": "https://example.com/intro.wav"}},
        content_type="application/json",
    )
    assert invalid_create.status_code == 400
    assert invalid_create.json()["detail"] == (
        "Column 'audio' is an audio column. Leave it blank and attach an audio asset."
    )

    create_row = api_client.post(
        f"/api/datasets/{dataset.key}/rows",
        data={"data": {"clip_id": "C-1", "audio": ""}},
        content_type="application/json",
    )
    assert create_row.status_code == 200
    row_id = create_row.json()["row"]["id"]

    attach_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows/{row_id}/audio",
        data={
            "column_name": "audio",
            "filename": "intro.wav",
            "content_type": "audio/wav",
            "audio_base64": audio_base64(),
        },
        content_type="application/json",
    )
    assert attach_response.status_code == 200
    asset = DatasetAsset.objects.get(key=attach_response.json()["asset"]["key"])

    idempotent_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"audio": asset.asset_ref}},
        content_type="application/json",
    )
    assert idempotent_patch.status_code == 200
    assert idempotent_patch.json()["row"]["data"]["audio"] == asset.asset_ref
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    invalid_patch = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"audio": "asset:00000000-0000-0000-0000-000000000000"}},
        content_type="application/json",
    )
    assert invalid_patch.status_code == 400
    assert DatasetAsset.objects.filter(pk=asset.pk).exists()

    clear_response = api_client.patch(
        f"/api/datasets/{dataset.key}/rows/{row_id}",
        data={"data": {"audio": ""}},
        content_type="application/json",
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["row"]["data"]["audio"] == ""
    assert not DatasetAsset.objects.filter(pk=asset.pk).exists()


def test_dataset_api_renames_and_drops_image_column_assets(api_client, profile):
    create_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Catalog images",
            "headers": ["sku", "photo"],
            "index_column": "sku",
            "column_types": {"photo": "image"},
            "rows": [{"sku": "A-1", "photo": ""}],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    dataset = Dataset.objects.get(key=create_response.json()["dataset"]["key"], profile=profile)
    row = dataset.rows.get(index_value="A-1")

    attach_response = api_client.post(
        f"/api/datasets/{dataset.key}/rows/{row.id}/image",
        data={
            "column_name": "photo",
            "filename": "adapter.png",
            "content_type": "image/png",
            "image_base64": image_base64(),
        },
        content_type="application/json",
    )
    assert attach_response.status_code == 200
    asset = DatasetAsset.objects.get(key=attach_response.json()["asset"]["key"])

    rename_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/rename",
        data={"old_name": "photo", "new_name": "hero_image"},
        content_type="application/json",
    )
    assert rename_response.status_code == 200
    asset.refresh_from_db()
    row.refresh_from_db()
    assert asset.column_name == "hero_image"
    assert row.data["hero_image"] == asset.asset_ref
    assert "photo" not in row.data

    drop_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns/drop",
        data={"name": "hero_image"},
        content_type="application/json",
    )
    assert drop_response.status_code == 200
    assert not DatasetAsset.objects.filter(pk=asset.pk).exists()


def test_dataset_api_rejects_image_index_and_nonblank_image_defaults(api_client, profile):
    image_index_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Invalid image index",
            "headers": ["photo", "name"],
            "index_column": "photo",
            "column_types": {"photo": "image"},
        },
        content_type="application/json",
    )
    assert image_index_response.status_code == 400
    assert image_index_response.json()["detail"] == (
        "Image columns cannot be used as the dataset index."
    )

    dataset = create_ready_dataset(profile)
    invalid_default_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
        data={
            "name": "photo",
            "default_value": "https://example.com/photo.png",
            "column_type": "image",
        },
        content_type="application/json",
    )
    assert invalid_default_response.status_code == 400
    assert invalid_default_response.json()["detail"] == (
        "Column 'photo' is an image column. Leave it blank and attach an image asset."
    )

    audio_index_response = api_client.post(
        "/api/datasets",
        data={
            "name": "Invalid audio index",
            "headers": ["clip", "name"],
            "index_column": "clip",
            "column_types": {"clip": "audio"},
        },
        content_type="application/json",
    )
    assert audio_index_response.status_code == 400
    assert audio_index_response.json()["detail"] == (
        "Audio columns cannot be used as the dataset index."
    )

    invalid_audio_default_response = api_client.post(
        f"/api/datasets/{dataset.key}/columns",
        data={
            "name": "clip",
            "default_value": "https://example.com/clip.wav",
            "column_type": "audio",
        },
        content_type="application/json",
    )
    assert invalid_audio_default_response.status_code == 400
    assert invalid_audio_default_response.json()["detail"] == (
        "Column 'clip' is an audio column. Leave it blank and attach an audio asset."
    )


def test_dataset_api_rejects_image_type_for_unowned_existing_asset_ref(api_client, profile):
    dataset = create_ready_dataset(profile)
    dataset.headers = ["name", "email", "photo"]
    dataset.save(update_fields=["headers", "updated_at"])
    row = dataset.rows.get(index_value="ada@example.com")
    row.data = {
        **row.data,
        "photo": "asset:00000000-0000-0000-0000-000000000000",
    }
    row.save(update_fields=["data", "updated_at"])

    response = api_client.patch(
        f"/api/datasets/{dataset.key}/column-types",
        data={"column_types": {"photo": "image"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Column 'photo' references an image asset that does not exist."
    )
