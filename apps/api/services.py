from apps.core.models import Profile
from apps.datasets.models import Dataset


def serialize_user_info(profile: Profile) -> dict:
    """Return safe user/profile details for API and MCP consumers."""
    user = profile.user
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name(),
        "date_joined": user.date_joined,
        "profile": {
            "id": profile.id,
            "state": profile.state,
            "has_active_subscription": profile.has_active_subscription,
        },
    }


def serialize_dataset_summary(dataset: Dataset) -> dict:
    """Return machine-friendly dataset metadata without row payloads."""
    return {
        "key": str(dataset.key),
        "name": dataset.name,
        "original_filename": dataset.original_filename,
        "file_type": dataset.file_type,
        "status": dataset.status,
        "headers": dataset.headers,
        "index_column": dataset.index_column,
        "index_generated": dataset.index_generated,
        "row_count": dataset.row_count,
        "public_enabled": dataset.public_enabled,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "confirmed_at": dataset.confirmed_at,
        "processed_at": dataset.processed_at,
    }


def serialize_profile_datasets(profile: Profile, limit: int = 100, offset: int = 0) -> dict:
    """Return a bounded page of datasets owned by the authenticated profile."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    queryset = profile.datasets.only(
        "key",
        "name",
        "original_filename",
        "file_type",
        "status",
        "headers",
        "index_column",
        "index_generated",
        "row_count",
        "public_enabled",
        "created_at",
        "updated_at",
        "confirmed_at",
        "processed_at",
    )
    total_count = queryset.count()
    datasets = list(queryset[offset : offset + limit])
    return {
        "count": len(datasets),
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(datasets) < total_count,
        "datasets": [serialize_dataset_summary(dataset) for dataset in datasets],
    }
