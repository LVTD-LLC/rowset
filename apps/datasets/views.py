import hashlib
import json
import uuid
from urllib.parse import ParseResult, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, ListView

from apps.api.services import (
    DatasetServiceError,
    archive_profile_dataset,
    create_profile_dataset_relationship,
    create_profile_project,
    dataset_asset_content_field,
    delete_profile_dataset_relationship,
    get_profile_dataset,
    update_profile_dataset_column_types,
    update_profile_dataset_metadata,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
    update_profile_project,
    update_profile_project_metadata,
)
from apps.datasets.choices import DatasetColumnType, DatasetStatus
from apps.datasets.models import Dataset, DatasetAsset, DatasetRow, Project
from apps.datasets.services import (
    DATASET_ASSET_CACHE_CONTROL,
    DATASET_REFERENCE_TARGET,
    ROW_DEFAULT_SORT,
    ROW_FILTER_ABOVE,
    ROW_FILTER_BELOW,
    ROW_FILTER_CONTAINS,
    ROW_FILTER_IS,
    ROW_ORDERED_FILTER_TYPES,
    ROW_SORT_DESC,
    apply_dataset_row_query,
    column_definitions,
    dataset_asset_key_from_ref,
    dataset_row_filter_operators,
    default_dataset_row_filter_operator,
    image_columns_from_schema,
    iter_export_row_data,
    normalize_dataset_row_filter_operator,
    normalize_dataset_row_sort,
    normalize_dataset_row_sort_direction,
    normalize_public_page_size,
    ordered_row_values,
    rows_to_csv_text,
    rows_to_jsonl_text,
    rows_to_parquet_bytes,
    rows_to_sqlite_bytes,
    rows_to_xlsx_bytes,
)

PUBLIC_ACCESS_SESSION_PREFIX = "public_dataset_access_"
PUBLIC_PREVIEW_ROBOTS_POLICY = "noindex, nofollow, noarchive"

DATASET_SORT_OPTIONS = (
    ("recent", "Recently updated"),
    ("created", "Recently created"),
    ("name", "Name"),
    ("rows", "Rows"),
    ("project", "Project"),
)
ARCHIVED_DATASET_SORT_OPTIONS = (
    ("archived", "Recently archived"),
    ("name", "Name"),
    ("rows", "Rows"),
    ("project", "Project"),
)
PROJECT_GROUP_ORDERING = (F("project__name").asc(nulls_last=True), "project_id")
DATASET_SORT_ORDERING = {
    "recent": ("-updated_at", "-created_at", "-id"),
    "created": ("-created_at", "-id"),
    "name": ("name", "id"),
    "rows": ("-row_count", "name", "id"),
    "project": (*PROJECT_GROUP_ORDERING, "name", "id"),
}
ARCHIVED_DATASET_SORT_ORDERING = {
    "archived": ("-archived_at", "-updated_at", "-id"),
    "name": ("name", "id"),
    "rows": ("-row_count", "name", "id"),
    "project": (*PROJECT_GROUP_ORDERING, "name", "id"),
}
DATASET_LIST_PAGE_SIZE = 100
DATASET_VIEW_MODE_OPTIONS = (
    ("raw", "Raw rows"),
    ("grouped", "Grouped by project"),
)
DATASET_VIEW_MODE_GROUPED = "grouped"
DATASET_VIEW_MODE_RAW = "raw"
DATASET_DETAIL_ROW_PAGE_SIZE = 100
DATASET_CHANGES_PAGE_SIZE = 25
ROW_SEARCH_PARAM = "row_q"
ROW_SORT_PARAM = "row_sort"
ROW_SORT_DIRECTION_PARAM = "row_dir"
ROW_FILTER_PARAM_PREFIX = "filter_"
ROW_FILTER_OPERATOR_PARAM_PREFIX = "filter_op_"
DATASET_EXPORT_FORMATS = {
    "csv": ("text/csv; charset=utf-8", rows_to_csv_text),
    "jsonl": ("application/x-ndjson; charset=utf-8", rows_to_jsonl_text),
    "parquet": ("application/vnd.apache.parquet", rows_to_parquet_bytes),
    "sqlite": ("application/vnd.sqlite3", rows_to_sqlite_bytes),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        rows_to_xlsx_bytes,
    ),
}
ROWSET_CANONICAL_HOST = "rowset.lvtd.dev"
ROWSET_LINK_SCHEMES = {"http", "https"}


def _host_without_port(host: str) -> str:
    return host.split(":", 1)[0].lower()


def _rowset_link_hosts(request=None) -> set[str]:
    hosts = {ROWSET_CANONICAL_HOST}
    site_host = urlparse(settings.SITE_URL).hostname
    if site_host:
        hosts.add(site_host.lower())
    if request is not None:
        request_host = _host_without_port(request.get_host())
        if request_host:
            hosts.add(request_host)
    return hosts


def _normalized_rowset_href(value: str, request=None) -> tuple[str, ParseResult] | None:
    raw_value = value.strip()
    if not raw_value or raw_value.startswith("//"):
        return None

    if raw_value.startswith("/"):
        parsed = urlparse(raw_value)
        if parsed.scheme or parsed.netloc:
            return None
        return raw_value, parsed

    href = raw_value if "://" in raw_value else f"https://{raw_value}"
    parsed = urlparse(href)
    if parsed.scheme not in ROWSET_LINK_SCHEMES or not parsed.hostname:
        return None
    if parsed.hostname.lower() not in _rowset_link_hosts(request):
        return None
    return href, parsed


def _rowset_dataset_path_match(path: str) -> tuple[str, bool, list[str]] | None:
    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "datasets":
        return path_parts[1], False, path_parts[2:]
    if len(path_parts) >= 3 and path_parts[0:2] == ["share", "datasets"]:
        return path_parts[2], True, path_parts[3:]
    return None


def _rowset_link_row_id(remaining_parts: list[str]) -> tuple[bool, int | None]:
    if not remaining_parts:
        return True, None
    if len(remaining_parts) != 2 or remaining_parts[0] != "rows":
        return False, None
    try:
        return True, int(remaining_parts[1])
    except ValueError:
        return False, None


def _parse_rowset_dataset_link(value: str, request=None) -> dict[str, object] | None:
    normalized_href = _normalized_rowset_href(value, request)
    if normalized_href is None:
        return None
    href, parsed = normalized_href

    path_match = _rowset_dataset_path_match(parsed.path)
    if path_match is None:
        return None
    dataset_key, is_public, remaining_parts = path_match

    try:
        uuid.UUID(dataset_key)
    except ValueError:
        return None

    is_valid_row_path, row_id = _rowset_link_row_id(remaining_parts)
    if not is_valid_row_path:
        return None

    return {
        "href": href,
        "dataset_key": dataset_key,
        "is_public": is_public,
        "row_id": row_id,
    }


def _generic_rowset_link(parsed_link: dict[str, object]) -> dict[str, str]:
    is_row = parsed_link["row_id"] is not None
    if is_row:
        link_text = "Rowset row"
        detail = "Shared row" if parsed_link["is_public"] else ""
    else:
        link_text = "Rowset dataset"
        detail = "Shared dataset" if parsed_link["is_public"] else ""
    return {
        "rowset_link_url": str(parsed_link["href"]),
        "rowset_link_text": link_text,
        "rowset_link_detail": detail,
        "rowset_link_label": f"Open {link_text.lower()}",
    }


def _plain_rowset_url_link(parsed_link: dict[str, object]) -> dict[str, str]:
    return {
        "plain_link_url": str(parsed_link["href"]),
        "plain_link_label": "Open Rowset URL",
    }


def _owned_rowset_link(
    parsed_link: dict[str, object],
    profile,
    link_cache: dict[tuple[object, bool, str, int | None], dict[str, str] | None],
) -> dict[str, str] | None:
    cache_key = (
        profile.pk,
        bool(parsed_link["is_public"]),
        str(parsed_link["dataset_key"]),
        parsed_link["row_id"],
    )
    if cache_key in link_cache:
        return link_cache[cache_key]

    dataset_lookup = {"profile": profile}
    if parsed_link["is_public"]:
        dataset_lookup["public_key"] = parsed_link["dataset_key"]
        dataset_lookup["public_enabled"] = True
        dataset_lookup["status"] = DatasetStatus.READY
        dataset_lookup["archived_at__isnull"] = True
    else:
        dataset_lookup["key"] = parsed_link["dataset_key"]

    dataset = (
        Dataset.objects.only(
            "id",
            "key",
            "public_key",
            "name",
            "status",
            "archived_at",
            "public_enabled",
        )
        .filter(**dataset_lookup)
        .first()
    )
    if dataset is None:
        link_cache[cache_key] = None
        return None

    row_id = parsed_link["row_id"]
    target_url = dataset.get_absolute_url()
    target_label = dataset.name
    target_detail = "Archived" if dataset.archived_at else dataset.get_status_display()
    aria_label = f"Open Rowset dataset {dataset.name}"
    if row_id is not None:
        target_row = dataset.rows.only("id", "dataset_id", "row_number").filter(id=row_id).first()
        if target_row is None:
            link_cache[cache_key] = None
            return None
        target_url = target_row.get_absolute_url()
        target_label = f"{dataset.name} row {target_row.row_number}"
        target_detail = "Row"
        aria_label = f"Open Rowset row {target_row.row_number} in {dataset.name}"

    link = {
        "rowset_link_url": target_url,
        "rowset_link_text": target_label,
        "rowset_link_detail": target_detail,
        "rowset_link_label": aria_label,
    }
    link_cache[cache_key] = link
    return link


def _rowset_link_for_value(
    value: str,
    *,
    request=None,
    profile=None,
    public_context: bool = False,
    link_cache: dict[tuple[object, bool, str, int | None], dict[str, str] | None] | None = None,
) -> dict[str, str]:
    parsed_link = _parse_rowset_dataset_link(value, request)
    if parsed_link is None:
        return {}
    if public_context:
        return _generic_rowset_link(parsed_link)

    if profile is not None:
        if link_cache is None:
            link_cache = {}
        link = _owned_rowset_link(parsed_link, profile, link_cache)
        if link is not None:
            return link

    return _plain_rowset_url_link(parsed_link)


def _cell_value(value: object) -> str:
    return "" if value is None else str(value)


def _mutation_change_display(value, *, values_recorded: bool, legacy_placeholder: str) -> dict:
    value = "" if value is None else str(value)
    if values_recorded:
        return {
            "text": "Blank" if value == "" else value,
            "is_blank": value == "",
            "is_unrecorded": False,
        }
    if value == legacy_placeholder:
        return {
            "text": "Not recorded",
            "is_blank": False,
            "is_unrecorded": True,
        }
    if value in ("", "Blank"):
        return {
            "text": "Blank",
            "is_blank": True,
            "is_unrecorded": False,
        }
    return {
        "text": "Not recorded",
        "is_blank": False,
        "is_unrecorded": True,
    }


def _mutation_history_item(mutation) -> dict:
    metadata = mutation.metadata or {}
    values_recorded = metadata.get("value_changes_recorded") is True
    field_changes = []
    for change in metadata.get("field_changes") or []:
        if not isinstance(change, dict):
            continue
        field_changes.append(
            {
                "field": str(change.get("field", "")),
                "before": _mutation_change_display(
                    change.get("before", ""),
                    values_recorded=values_recorded,
                    legacy_placeholder="Previous value",
                ),
                "after": _mutation_change_display(
                    change.get("after", ""),
                    values_recorded=values_recorded,
                    legacy_placeholder="New value",
                ),
            }
        )
    changed_fields = metadata.get("changed_fields") or []
    return {
        "summary_id": f"dataset-change-{mutation.id}-summary",
        "summary": mutation.summary,
        "actor_label": mutation.actor_label,
        "created_at": mutation.created_at,
        "mutation_type_display": mutation.get_mutation_type_display(),
        "field_changes": field_changes,
        "changed_fields": changed_fields,
        "has_change_details": bool(field_changes or changed_fields),
    }


def _visible_project_dataset_count():
    return Count(
        "datasets",
        filter=Q(datasets__archived_at__isnull=True) & ~Q(datasets__status=DatasetStatus.PREVIEWED),
    )


def _delete_dataset(dataset: Dataset) -> None:
    if dataset.source_file:
        dataset.source_file.delete(save=False)
    dataset.delete()


def _owned_dataset_queryset(profile):
    return profile.datasets.select_related(
        "project",
        "created_by_agent_api_key",
        "updated_by_agent_api_key",
    ).all()


def _dataset_export_filename(dataset: Dataset, extension: str) -> str:
    name = f"{dataset.name or 'dataset'}".strip().replace("/", "-") or "dataset"
    return f"{name}.{extension}"


def _dataset_export_response(dataset: Dataset, export_format: str) -> HttpResponse:
    try:
        content_type, serializer = DATASET_EXPORT_FORMATS[export_format]
    except KeyError as exc:
        raise Http404("Unsupported export format.") from exc

    response = HttpResponse(
        serializer(dataset.headers, iter_export_row_data(dataset)),
        content_type=content_type,
    )
    response["Content-Disposition"] = content_disposition_header(
        True,
        _dataset_export_filename(dataset, export_format),
    )
    return response


def _dataset_asset_file_response(
    asset: DatasetAsset,
    variant: str,
    *,
    include_body: bool = True,
) -> HttpResponse:
    try:
        field = dataset_asset_content_field(asset, variant)
    except DatasetServiceError as exc:
        raise Http404(exc.message) from exc
    if not field or not field.name:
        raise Http404("Dataset asset file not found.")
    normalized_variant = str(variant or "original").strip().lower()
    content_type = (
        "image/jpeg"
        if normalized_variant == "thumbnail" and asset.thumbnail
        else asset.content_type
    )
    if include_body:
        with field.open("rb") as asset_file:
            response = HttpResponse(asset_file.read(), content_type=content_type)
    else:
        response = HttpResponse(content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(
        False,
        asset.original_filename or f"{asset.key}",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = DATASET_ASSET_CACHE_CONTROL
    patch_vary_headers(response, ["Authorization", "Cookie"])
    return response


def _dataset_asset_content_url(
    asset: DatasetAsset,
    *,
    public_context: bool = False,
    variant: str = "thumbnail",
) -> str:
    if public_context:
        url = reverse(
            "public_dataset_asset_content",
            kwargs={"public_key": asset.dataset.public_key, "asset_key": asset.key},
        )
    else:
        url = reverse(
            "dataset_asset_content",
            kwargs={"dataset_key": asset.dataset.key, "asset_key": asset.key},
        )
    return f"{url}?variant={variant}"


def _image_asset_cell_payload(
    asset: DatasetAsset,
    *,
    public_context: bool = False,
) -> dict[str, str | bool]:
    dimensions = ""
    if asset.width and asset.height:
        dimensions = f"{asset.width} x {asset.height}"
    label = asset.original_filename or "Image"
    return {
        "is_image": True,
        "value": label,
        "image_url": _dataset_asset_content_url(
            asset,
            public_context=public_context,
            variant="thumbnail",
        ),
        "image_full_url": _dataset_asset_content_url(
            asset,
            public_context=public_context,
            variant="original",
        ),
        "image_alt": label,
        "image_detail": dimensions,
    }


def _image_asset_lookup(
    dataset: Dataset,
    rows: list[DatasetRow],
) -> dict[tuple[int, str], DatasetAsset]:
    row_ids = [row.id for row in rows if row.id]
    if not row_ids:
        return {}
    return {
        (asset.row_id, asset.column_name): asset
        for asset in DatasetAsset.objects.filter(dataset=dataset, row_id__in=row_ids)
    }


def _row_cells(
    headers: list[str],
    row_data: dict[str, object],
    column_schema: dict | None = None,
    relationship_links: dict[str, dict[str, str]] | None = None,
    reference_lookup: dict[tuple[str, str], dict[str, str]] | None = None,
    *,
    row_id: int | None = None,
    image_assets: dict[tuple[int, str], DatasetAsset] | None = None,
    request=None,
    profile=None,
    public_context: bool = False,
    link_cache: dict[tuple[object, bool, str, int | None], dict[str, str] | None] | None = None,
) -> list[dict[str, object]]:
    ordered_keys = [*headers, *[key for key in row_data if key not in headers]]
    descriptions = {
        column["name"]: column["description"]
        for column in column_definitions(headers, column_schema or {})
    }
    relationship_links = relationship_links or {}
    reference_lookup = reference_lookup or {}
    image_assets = image_assets or {}
    image_columns = set(image_columns_from_schema(headers, column_schema))
    cells = []
    for header in ordered_keys:
        value = _cell_value(row_data.get(header, ""))
        cell = {
            "header": header,
            "description": descriptions.get(header, ""),
            "value": value,
        }
        asset_key = dataset_asset_key_from_ref(value) if header in image_columns else ""
        asset = image_assets.get((row_id, header)) if row_id is not None and asset_key else None
        if asset and str(asset.key) == asset_key:
            cell.update(_image_asset_cell_payload(asset, public_context=public_context))
        elif asset_key:
            cell["is_missing_image"] = True
            cell["value"] = "Image unavailable"
        relationship_link = relationship_links.get(header)
        if cell.get("is_image") or cell.get("is_missing_image"):
            pass
        elif relationship_link and cell["value"]:
            cell["relationship_url"] = relationship_link["url"]
            cell["relationship_label"] = relationship_link["label"]
        elif cell["value"] and (
            reference_link := reference_lookup.get((header, cell["value"].strip()))
        ):
            cell.update(reference_link)
        elif cell["value"]:
            cell.update(
                _rowset_link_for_value(
                    cell["value"],
                    request=request,
                    profile=profile,
                    public_context=public_context,
                    link_cache=link_cache,
                )
            )
        cells.append(cell)
    return cells


def _row_table_cells(
    headers: list[str],
    row_data: dict[str, object],
    *,
    column_schema: dict | None = None,
    reference_lookup: dict[tuple[str, str], dict[str, str]] | None = None,
    image_assets: dict[tuple[int, str], DatasetAsset] | None = None,
    row_url: str = "",
    row_id: int | None = None,
    row_number: int | None = None,
    request=None,
    profile=None,
    public_context: bool = False,
    link_cache: dict[tuple[object, bool, str, int | None], dict[str, str] | None] | None = None,
) -> list[dict[str, object]]:
    reference_lookup = reference_lookup or {}
    image_assets = image_assets or {}
    image_columns = set(image_columns_from_schema(headers, column_schema))
    cells = []
    row_detail_primary_assigned = False
    for index, header in enumerate(headers):
        display_value = _cell_value(row_data.get(header, ""))
        cell = {
            "value": display_value,
            "is_first": index == 0,
        }
        asset_key = dataset_asset_key_from_ref(display_value) if header in image_columns else ""
        asset = image_assets.get((row_id, header)) if row_id is not None and asset_key else None
        if asset and str(asset.key) == asset_key:
            cell.update(_image_asset_cell_payload(asset, public_context=public_context))
        elif asset_key:
            cell["is_missing_image"] = True
            cell["value"] = "Image unavailable"
        elif display_value and (
            reference_link := reference_lookup.get((header, display_value.strip()))
        ):
            cell.update(reference_link)
        elif display_value:
            cell.update(
                _rowset_link_for_value(
                    display_value,
                    request=request,
                    profile=profile,
                    public_context=public_context,
                    link_cache=link_cache,
                )
            )
        is_cell_link = bool(
            cell.get("rowset_link_url")
            or cell.get("plain_link_url")
            or cell.get("reference_url")
            or cell.get("image_full_url")
        )
        if row_url and (not is_cell_link or not row_detail_primary_assigned):
            cell["row_url"] = row_url
            cell["row_detail_label"] = f"View row {row_number} details"
            if not row_detail_primary_assigned:
                cell["is_row_detail_primary"] = True
                row_detail_primary_assigned = True
        cells.append(cell)
    return cells


def _row_relationship_links(
    dataset: Dataset,
    row_data: dict[str, object],
) -> dict[str, dict[str, str]]:
    links = {}
    if not row_data:
        return links

    relationship_candidates = []
    target_index_values_by_dataset = {}
    relationships = list(
        dataset.outgoing_relationships.select_related("target_dataset").order_by(
            "source_column",
            "name",
            "id",
        )
    )
    for relationship in relationships:
        if (
            relationship.target_dataset.status != DatasetStatus.READY
            or relationship.target_dataset.archived_at is not None
        ):
            continue
        target_index_value = str(row_data.get(relationship.source_column, "") or "").strip()
        if not target_index_value:
            continue
        relationship_candidates.append((relationship, target_index_value))
        target_index_values_by_dataset.setdefault(relationship.target_dataset_id, set()).add(
            target_index_value
        )

    target_row_query = Q()
    for target_dataset_id, target_index_values in target_index_values_by_dataset.items():
        target_row_query |= Q(
            dataset_id=target_dataset_id,
            index_value__in=target_index_values,
        )
    target_rows = (
        DatasetRow.objects.only("id", "dataset_id", "row_number", "index_value").filter(
            target_row_query
        )
        if target_row_query
        else []
    )
    target_rows_by_key = {
        (target_row.dataset_id, target_row.index_value): target_row for target_row in target_rows
    }

    for relationship, target_index_value in relationship_candidates:
        if relationship.source_column in links:
            continue
        target_row = target_rows_by_key.get((relationship.target_dataset_id, target_index_value))
        if target_row is None:
            continue
        links[relationship.source_column] = {
            "url": reverse(
                "dataset_row_detail",
                kwargs={
                    "dataset_key": relationship.target_dataset.key,
                    "row_id": target_row.id,
                },
            ),
            "label": (
                f"View related {relationship.target_dataset.name} row "
                f"{target_row.row_number} via {relationship.name}"
            ),
        }
    return links


def _dataset_reference_columns(column_definition_list: list[dict]) -> set[str]:
    return {
        column["name"]
        for column in column_definition_list
        if column.get("type") == DatasetColumnType.REFERENCE
        and column.get("target") == DATASET_REFERENCE_TARGET
    }


def _dataset_reference_lookup(
    profile,
    reference_columns: set[str],
    row_data_items: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, str]]:
    if not reference_columns:
        return {}

    raw_values_by_column: dict[str, set[str]] = {column: set() for column in reference_columns}
    for row_data in row_data_items:
        if not row_data:
            continue
        for column in reference_columns:
            raw_value = str(row_data.get(column, "") or "").strip()
            if raw_value:
                raw_values_by_column[column].add(raw_value)

    lookup = {}
    for column, raw_values in raw_values_by_column.items():
        for raw_value in raw_values:
            try:
                target_dataset = get_profile_dataset(profile, raw_value)
            except DatasetServiceError:
                continue
            lookup[(column, raw_value)] = {
                "rowset_link_url": target_dataset.get_absolute_url(),
                "rowset_link_text": target_dataset.name,
                "rowset_link_detail": (
                    "Archived dataset"
                    if target_dataset.archived_at
                    else target_dataset.get_status_display()
                ),
                "rowset_link_label": f"Open Rowset dataset {target_dataset.name}",
            }
    return lookup


def _querystring_for_page(request, page_number: int) -> str:
    query_params = request.GET.copy()
    query_params["page"] = page_number
    return f"?{query_params.urlencode()}"


def _column_filter_input_type(column_type: str) -> str:
    return {
        DatasetColumnType.BOOLEAN: "select",
        DatasetColumnType.CHOICE: "select",
        DatasetColumnType.CURRENCY: "number",
        DatasetColumnType.DATE: "date",
        DatasetColumnType.DATETIME: "datetime-local",
        DatasetColumnType.INTEGER: "number",
        DatasetColumnType.NUMBER: "number",
    }.get(column_type, "search")


def _column_filter_operator_options(column_type: str, selected_operator: str):
    labels = {
        ROW_FILTER_ABOVE: "Above",
        ROW_FILTER_BELOW: "Below",
        ROW_FILTER_CONTAINS: "Contains",
        ROW_FILTER_IS: "Is",
    }
    return [
        {
            "label": labels[operator],
            "value": operator,
            "selected": selected_operator == operator,
        }
        for operator in dataset_row_filter_operators(column_type)
    ]


def _column_sort_labels(column_type: str) -> tuple[str, str]:
    if column_type in {
        DatasetColumnType.CURRENCY,
        DatasetColumnType.INTEGER,
        DatasetColumnType.NUMBER,
    }:
        return "Ascending", "Descending"
    if column_type == DatasetColumnType.DATE:
        return "Oldest first", "Newest first"
    if column_type == DatasetColumnType.DATETIME:
        return "Earliest first", "Latest first"
    return "A to Z", "Z to A"


def _column_has_ordered_filter(column_type: str) -> bool:
    return column_type in ROW_ORDERED_FILTER_TYPES


def _column_filter_placeholder(column_type: str) -> str:
    if column_type == DatasetColumnType.DATE:
        return "Date"
    if column_type == DatasetColumnType.DATETIME:
        return "Date/time"
    return "Number"


def _row_filter_fields(
    dataset: Dataset,
    request,
    *,
    include_column_descriptions: bool = True,
    columns: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    fields = []
    if columns is None:
        columns = column_definitions(dataset.headers, dataset.column_schema)
    for index, column in enumerate(columns):
        column_type = column["type"]
        param_name = f"{ROW_FILTER_PARAM_PREFIX}{index}"
        operator_param_name = f"{ROW_FILTER_OPERATOR_PARAM_PREFIX}{index}"
        selected_operator = normalize_dataset_row_filter_operator(
            column_type,
            request.GET.get(operator_param_name),
        )
        default_operator = default_dataset_row_filter_operator(column_type)
        ascending_label, descending_label = _column_sort_labels(column_type)
        fields.append(
            {
                "index": index,
                "header": column["name"],
                "type": column_type,
                "type_label": column["type_label"],
                "description": (
                    column["description"] if include_column_descriptions else ""
                ),
                "param_name": param_name,
                "value": request.GET.get(param_name, "").strip(),
                "operator": selected_operator,
                "default_operator": default_operator,
                "operator_param_name": operator_param_name,
                "operator_options": _column_filter_operator_options(
                    column_type,
                    selected_operator,
                ),
                "sort_value": f"col_{index}",
                "sort_ascending_label": ascending_label,
                "sort_descending_label": descending_label,
                "input_type": _column_filter_input_type(column_type),
                "is_boolean": column_type == DatasetColumnType.BOOLEAN,
                "is_choice": column_type == DatasetColumnType.CHOICE,
                "is_number": column_type
                in {DatasetColumnType.INTEGER, DatasetColumnType.NUMBER},
                "is_currency": column_type == DatasetColumnType.CURRENCY,
                "is_numeric_filter": column_type
                in {
                    DatasetColumnType.CURRENCY,
                    DatasetColumnType.INTEGER,
                    DatasetColumnType.NUMBER,
                },
                "is_ordered_filter": _column_has_ordered_filter(column_type),
                "filter_placeholder": _column_filter_placeholder(column_type),
                "choices": column.get("choices", []),
                "operator_label": (
                    "Contains"
                    if default_operator == ROW_FILTER_CONTAINS
                    else "Is"
                ),
            }
        )
    return fields


def _row_sort_options(dataset: Dataset, selected_sort: str) -> list[dict[str, object]]:
    options = [
        {
            "label": "Original order",
            "value": ROW_DEFAULT_SORT,
            "selected": selected_sort == ROW_DEFAULT_SORT,
        }
    ]
    options.extend(
        {
            "label": header,
            "value": f"col_{index}",
            "selected": selected_sort == f"col_{index}",
        }
        for index, header in enumerate(dataset.headers)
    )
    return options


def _selected_row_sort(request, dataset: Dataset) -> str:
    return normalize_dataset_row_sort(dataset.headers, request.GET.get(ROW_SORT_PARAM))


def _selected_row_sort_direction(request) -> str:
    return normalize_dataset_row_sort_direction(request.GET.get(ROW_SORT_DIRECTION_PARAM))


def _dataset_row_query_context(
    request,
    dataset: Dataset,
    queryset,
    *,
    include_column_descriptions: bool = True,
    columns: list[dict[str, object]] | None = None,
):
    search_query = request.GET.get(ROW_SEARCH_PARAM, "").strip()
    selected_sort = _selected_row_sort(request, dataset)
    sort_direction = _selected_row_sort_direction(request)
    filter_fields = _row_filter_fields(
        dataset,
        request,
        include_column_descriptions=include_column_descriptions,
        columns=columns,
    )
    filters = {
        str(field["header"]): str(field["value"])
        for field in filter_fields
        if str(field["value"]).strip()
    }
    filter_operators = {
        str(field["header"]): str(field["operator"])
        for field in filter_fields
        if str(field["value"]).strip()
    }

    queryset, row_query = apply_dataset_row_query(
        queryset,
        dataset,
        query=search_query,
        filters=filters,
        filter_operators=filter_operators,
        sort=selected_sort,
        direction=sort_direction,
    )
    for field in filter_fields:
        field["is_active_filter"] = field["header"] in row_query["filters"]
        field["is_active_sort"] = row_query["sort"] == field["sort_value"]
    return queryset, {
        "row_search_query": row_query["query"],
        "row_filter_fields": filter_fields,
        "row_sort_options": _row_sort_options(dataset, row_query["sort"]),
        "row_selected_sort": row_query["sort"],
        "row_default_sort": ROW_DEFAULT_SORT,
        "row_sort_desc": ROW_SORT_DESC,
        "row_sort_direction": row_query["direction"],
        "row_sort_direction_options": [
            {
                "label": "Ascending",
                "value": "asc",
                "selected": row_query["direction"] != ROW_SORT_DESC,
            },
            {
                "label": "Descending",
                "value": ROW_SORT_DESC,
                "selected": row_query["direction"] == ROW_SORT_DESC,
            },
        ],
        "has_row_filters": row_query["has_filters"],
        "row_filters_reset_url": request.path,
    }


def _dataset_relationship_context(dataset: Dataset) -> dict:
    outgoing = dataset.outgoing_relationships.select_related("target_dataset").order_by(
        "name",
        "id",
    )
    incoming = dataset.incoming_relationships.select_related("source_dataset").order_by(
        "source_dataset__name",
        "name",
        "id",
    )
    return {
        "outgoing_relationships": outgoing,
        "incoming_relationships": incoming,
    }


class DatasetListView(LoginRequiredMixin, ListView):
    template_name = "datasets/dataset_list.html"
    context_object_name = "datasets"
    paginate_by = DATASET_LIST_PAGE_SIZE
    archived_at_isnull = True
    sort_options = DATASET_SORT_OPTIONS
    sort_ordering = DATASET_SORT_ORDERING
    default_sort = "recent"
    view_mode_options = DATASET_VIEW_MODE_OPTIONS
    default_view_mode = DATASET_VIEW_MODE_RAW
    dataset_list_url_name = "dataset_list"
    dataset_list_is_archived = False
    dataset_list_eyebrow = "Datasets"
    dataset_list_title = "API-backed datasets"
    dataset_list_description = "Browse datasets created and managed through Rowset API or MCP."
    dataset_table_caption = "Datasets"
    dataset_table_date_heading = "Updated"
    dataset_stats_heading = "Dataset stats"
    dataset_stats_dataset_label = "Datasets"
    dataset_stats_rows_label = "Rows stored"
    dataset_stats_projects_label = "Projects"
    dataset_stats_public_preview_label = "Public previews"
    dataset_search_label = "Search datasets"
    dataset_search_placeholder = "Name, source file, or project"
    dataset_empty_title = "No datasets yet"
    dataset_empty_body = (
        "Ask your connected agent to create a dataset from the source file or table it can access."
    )
    dataset_filtered_empty_title = "No matching datasets"
    dataset_filtered_empty_body = (
        "Adjust the search or sort controls to return to the full dataset list."
    )

    def get_search_query(self) -> str:
        return self.request.GET.get("q", "").strip()

    def get_selected_sort(self) -> str:
        selected_sort = self.request.GET.get("sort", self.default_sort)
        if selected_sort not in self.sort_ordering:
            return self.default_sort
        return selected_sort

    def get_selected_view_mode(self) -> str:
        selected_view_mode = self.request.GET.get("view", self.default_view_mode)
        valid_view_modes = {value for value, _label in self.view_mode_options}
        if selected_view_mode not in valid_view_modes:
            return self.default_view_mode
        return selected_view_mode

    def get_grouped_ordering(self) -> tuple[str, ...]:
        selected_sort = self.get_selected_sort()
        dataset_ordering = self.sort_ordering[selected_sort]
        if selected_sort == "project":
            dataset_ordering = self.sort_ordering["name"]
        return (*PROJECT_GROUP_ORDERING, *dataset_ordering)

    def get_dataset_date_heading(self) -> str:
        if self.get_selected_sort() == "created":
            return "Created"
        return self.dataset_table_date_heading

    def get_base_queryset(self):
        if not hasattr(self, "_base_queryset"):
            self._base_queryset = (
                self.request.user.profile.datasets.select_related(
                    "project",
                    "created_by_agent_api_key",
                    "updated_by_agent_api_key",
                )
                .filter(archived_at__isnull=self.archived_at_isnull)
                .exclude(status=DatasetStatus.PREVIEWED)
            )
        return self._base_queryset

    def get_queryset(self):
        queryset = self.get_base_queryset()
        search_query = self.get_search_query()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query)
                | Q(original_filename__icontains=search_query)
                | Q(project__name__icontains=search_query)
            )

        if self.get_selected_view_mode() == DATASET_VIEW_MODE_GROUPED:
            return queryset.order_by(*self.get_grouped_ordering())

        return queryset.order_by(*self.sort_ordering[self.get_selected_sort()])

    def get_total_projects(self, base_queryset):
        return self.request.user.profile.projects.filter(archived_at__isnull=True).count()

    def get_dataset_group_totals(self, groups_by_key):
        if not groups_by_key:
            return {}

        project_ids = [group_key for group_key in groups_by_key if group_key is not None]
        if project_ids and None in groups_by_key:
            totals_queryset = self.object_list.filter(
                Q(project_id__in=project_ids) | Q(project__isnull=True)
            )
        elif project_ids:
            totals_queryset = self.object_list.filter(project_id__in=project_ids)
        else:
            totals_queryset = self.object_list.filter(project__isnull=True)

        return {
            item["project_id"]: item
            for item in totals_queryset.order_by()
            .values("project_id")
            .annotate(dataset_count=Count("id"), row_count=Sum("row_count"))
        }

    def get_dataset_groups(self, datasets):
        groups_by_key = {}
        for dataset in datasets:
            project = dataset.project
            group_key = project.pk if project else None
            if group_key not in groups_by_key:
                groups_by_key[group_key] = {
                    "project": project,
                    "label": project.name if project else "No project",
                    "description": project.description if project else "",
                    "datasets": [],
                    "dataset_count": 0,
                    "row_count": 0,
                }
            group = groups_by_key[group_key]
            group["datasets"].append(dataset)
            group["dataset_count"] += 1
            group["row_count"] += dataset.row_count

        totals_by_key = self.get_dataset_group_totals(groups_by_key)
        for group_key, group in groups_by_key.items():
            totals = totals_by_key.get(group_key)
            if totals:
                group["dataset_count"] = totals["dataset_count"] or 0
                group["row_count"] = totals["row_count"] or 0
        return list(groups_by_key.values())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_queryset = self.get_base_queryset()
        summary = base_queryset.aggregate(
            total_datasets=Count("id"),
            total_rows=Sum("row_count"),
            public_preview_count=Count("id", filter=Q(public_enabled=True)),
        )
        context["dataset_stats"] = {
            "total_datasets": summary["total_datasets"] or 0,
            "total_rows": summary["total_rows"] or 0,
            "public_preview_count": summary["public_preview_count"] or 0,
            "total_projects": self.get_total_projects(base_queryset),
        }
        context["search_query"] = self.get_search_query()
        context["selected_sort"] = self.get_selected_sort()
        context["sort_options"] = self.sort_options
        context["selected_view_mode"] = self.get_selected_view_mode()
        context["view_mode_options"] = self.view_mode_options
        context["dataset_groups"] = (
            self.get_dataset_groups(context["datasets"])
            if context["selected_view_mode"] == DATASET_VIEW_MODE_GROUPED
            else []
        )
        context["has_dataset_filters"] = bool(
            context["search_query"]
            or context["selected_sort"] != self.default_sort
            or context["selected_view_mode"] != self.default_view_mode
        )
        context["dataset_list_reset_url"] = reverse(self.dataset_list_url_name)
        context["dataset_list_is_archived"] = self.dataset_list_is_archived
        context["dataset_list_eyebrow"] = self.dataset_list_eyebrow
        context["dataset_list_title"] = self.dataset_list_title
        context["dataset_list_description"] = self.dataset_list_description
        context["dataset_table_caption"] = self.dataset_table_caption
        context["dataset_table_date_heading"] = self.get_dataset_date_heading()
        context["dataset_stats_heading"] = self.dataset_stats_heading
        context["dataset_stats_dataset_label"] = self.dataset_stats_dataset_label
        context["dataset_stats_rows_label"] = self.dataset_stats_rows_label
        context["dataset_stats_projects_label"] = self.dataset_stats_projects_label
        context["dataset_stats_public_preview_label"] = self.dataset_stats_public_preview_label
        context["dataset_search_label"] = self.dataset_search_label
        context["dataset_search_placeholder"] = self.dataset_search_placeholder
        context["dataset_empty_title"] = self.dataset_empty_title
        context["dataset_empty_body"] = self.dataset_empty_body
        context["dataset_filtered_empty_title"] = self.dataset_filtered_empty_title
        context["dataset_filtered_empty_body"] = self.dataset_filtered_empty_body
        page_obj = context.get("page_obj")
        if page_obj and page_obj.has_previous():
            context["previous_dataset_page_url"] = _querystring_for_page(
                self.request,
                page_obj.previous_page_number(),
            )
        if page_obj and page_obj.has_next():
            context["next_dataset_page_url"] = _querystring_for_page(
                self.request,
                page_obj.next_page_number(),
            )
        return context


class ArchivedDatasetListView(DatasetListView):
    archived_at_isnull = False
    sort_options = ARCHIVED_DATASET_SORT_OPTIONS
    sort_ordering = ARCHIVED_DATASET_SORT_ORDERING
    default_sort = "archived"
    dataset_list_url_name = "archived_dataset_list"
    dataset_list_is_archived = True
    dataset_list_eyebrow = "Archive"
    dataset_list_title = "Archived datasets"
    dataset_list_description = (
        "Review datasets archived through Rowset API or MCP without restoring them to normal "
        "dataset and project lists."
    )
    dataset_table_caption = "Archived datasets"
    dataset_table_date_heading = "Archived"
    dataset_stats_heading = "Archived dataset stats"
    dataset_stats_dataset_label = "Archived datasets"
    dataset_stats_rows_label = "Archived rows"
    dataset_stats_projects_label = "Archived projects"
    dataset_stats_public_preview_label = "Archived public previews"
    dataset_search_label = "Search archived datasets"
    dataset_search_placeholder = "Archived name, source file, or project"
    dataset_empty_title = "No archived datasets"
    dataset_empty_body = (
        "Archived datasets will appear here after an agent or API client archives one."
    )
    dataset_filtered_empty_title = "No matching archived datasets"
    dataset_filtered_empty_body = (
        "Adjust the search or sort controls to return to the full archived dataset list."
    )

    def get_total_projects(self, base_queryset):
        return (
            base_queryset.filter(project__isnull=False)
            .values("project_id")
            .distinct()
            .count()
        )


class ProjectListView(LoginRequiredMixin, ListView):
    template_name = "datasets/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        return self.request.user.profile.projects.filter(archived_at__isnull=True).annotate(
            dataset_count=_visible_project_dataset_count(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ungrouped_dataset_count"] = (
            self.request.user.profile.datasets.filter(
                project__isnull=True,
                archived_at__isnull=True,
            )
            .exclude(status=DatasetStatus.PREVIEWED)
            .count()
        )
        return context


class ProjectDetailView(LoginRequiredMixin, DetailView):
    template_name = "datasets/project_detail.html"
    context_object_name = "project"
    slug_url_kwarg = "project_key"
    slug_field = "key"

    def get_queryset(self):
        return self.request.user.profile.projects.filter(archived_at__isnull=True).annotate(
            dataset_count=_visible_project_dataset_count(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = Paginator(
            self.object.datasets.select_related(
                "created_by_agent_api_key",
                "updated_by_agent_api_key",
            )
            .filter(archived_at__isnull=True)
            .exclude(status=DatasetStatus.PREVIEWED)
            .order_by("-updated_at"),
            100,
        )
        page_obj = paginator.get_page(self.request.GET.get("page"))
        context["page_obj"] = page_obj
        context["datasets"] = page_obj.object_list
        context.setdefault("project_edit_mode", self.request.GET.get("edit") == "1")
        context.setdefault(
            "project_form_values",
            {
                "name": self.object.name,
                "description": self.object.description,
            },
        )
        context["metadata_json"] = json.dumps(
            self.object.metadata or {},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form_values = {
            "name": request.POST.get("name", ""),
            "description": request.POST.get("description", ""),
        }
        try:
            update_profile_project(
                request.user.profile,
                str(self.object.key),
                name=form_values["name"],
                description=form_values["description"],
            )
        except DatasetServiceError as exc:
            if exc.status_code == 404:
                raise Http404(exc.message) from exc
            context = self.get_context_data(
                object=self.object,
                project_edit_mode=True,
                project_form_values=form_values,
                project_form_error=exc.message,
            )
            return self.render_to_response(context)

        messages.success(request, "Project updated.")
        return redirect(self.object.get_absolute_url())


class DatasetDetailView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_detail.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return _owned_dataset_queryset(self.request.user.profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dataset = self.object
        base_row_queryset = dataset.rows.select_related("updated_by_agent_api_key")
        has_imported_rows = dataset.row_count > 0
        column_definition_list = column_definitions(
            dataset.headers,
            dataset.column_schema,
        )
        row_queryset, row_query_context = _dataset_row_query_context(
            self.request,
            dataset,
            base_row_queryset,
            columns=column_definition_list,
        )
        row_paginator = Paginator(row_queryset, DATASET_DETAIL_ROW_PAGE_SIZE)
        row_page_obj = row_paginator.get_page(self.request.GET.get("page"))
        rowset_link_cache = {}
        reference_columns = _dataset_reference_columns(column_definition_list)
        row_objects = list(row_page_obj.object_list)
        reference_lookup = _dataset_reference_lookup(
            self.request.user.profile,
            reference_columns,
            [row.data for row in row_objects],
        )
        image_asset_lookup = _image_asset_lookup(dataset, row_objects)
        rows_with_values = []
        for row in row_objects:
            row_url = reverse(
                "dataset_row_detail",
                kwargs={"dataset_key": dataset.key, "row_id": row.id},
            )
            cells = _row_table_cells(
                dataset.headers,
                row.data,
                column_schema=dataset.column_schema,
                reference_lookup=reference_lookup,
                image_assets=image_asset_lookup,
                row_url=row_url,
                row_id=row.id,
                row_number=row.row_number,
                request=self.request,
                profile=self.request.user.profile,
                link_cache=rowset_link_cache,
            )
            rows_with_values.append(
                {
                    "values": ordered_row_values(dataset.headers, row.data),
                    "cells": cells,
                    "has_accessible_row_link": any(
                        cell.get("is_row_detail_primary") for cell in cells
                    ),
                    "actor_label": row.updated_by_actor_label,
                    "row_number": row.row_number,
                    "url": row_url,
                }
            )
        if not has_imported_rows:
            rows_with_values = []
            preview_rows = dataset.preview_rows[:DATASET_DETAIL_ROW_PAGE_SIZE]
            reference_lookup = _dataset_reference_lookup(
                self.request.user.profile,
                reference_columns,
                preview_rows,
            )
            for row_number, preview_row in enumerate(
                preview_rows,
                start=1,
            ):
                cells = _row_table_cells(
                    dataset.headers,
                    preview_row,
                    column_schema=dataset.column_schema,
                    reference_lookup=reference_lookup,
                    request=self.request,
                    profile=self.request.user.profile,
                    link_cache=rowset_link_cache,
                )
                rows_with_values.append(
                    {
                        "values": ordered_row_values(dataset.headers, preview_row),
                        "cells": cells,
                        "has_accessible_row_link": False,
                        "actor_label": "",
                        "row_number": row_number,
                        "url": "",
                    }
                )
        context.update(row_query_context if has_imported_rows else {})
        context["rows_with_values"] = rows_with_values
        context["column_definitions"] = column_definition_list
        context["rows_heading"] = "Rows" if has_imported_rows else "Sample rows"
        context["rows_show_actor"] = has_imported_rows
        context["row_show_column_controls"] = has_imported_rows
        context["hide_column_filter_section"] = True
        context["rows_colspan"] = len(dataset.headers) + int(has_imported_rows)
        context["rows_empty_message"] = (
            "No rows match these filters."
            if context.get("has_row_filters")
            else "No rows are available yet."
        )
        context["row_page_obj"] = row_page_obj
        if row_page_obj.has_previous():
            context["previous_row_page_url"] = _querystring_for_page(
                self.request,
                row_page_obj.previous_page_number(),
            )
        if row_page_obj.has_next():
            context["next_row_page_url"] = _querystring_for_page(
                self.request,
                row_page_obj.next_page_number(),
            )
        context["public_url"] = self.request.build_absolute_uri(dataset.get_public_url())
        context["metadata_json"] = json.dumps(
            dataset.metadata or {},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        context.update(_dataset_relationship_context(dataset))
        return context


class DatasetChangesView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_changes.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return _owned_dataset_queryset(self.request.user.profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mutation_paginator = Paginator(self.object.mutations.all(), DATASET_CHANGES_PAGE_SIZE)
        mutation_page_obj = mutation_paginator.get_page(self.request.GET.get("page"))
        context["mutation_page_obj"] = mutation_page_obj
        context["mutation_history"] = [
            _mutation_history_item(mutation) for mutation in mutation_page_obj.object_list
        ]
        if mutation_page_obj.has_previous():
            context["previous_mutation_page_url"] = _querystring_for_page(
                self.request,
                mutation_page_obj.previous_page_number(),
            )
        if mutation_page_obj.has_next():
            context["next_mutation_page_url"] = _querystring_for_page(
                self.request,
                mutation_page_obj.next_page_number(),
            )
        return context


class DatasetRowDetailView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_row_detail.html"
    context_object_name = "dataset_row"
    pk_url_kwarg = "row_id"

    def get_queryset(self):
        return DatasetRow.objects.select_related(
            "created_by_agent_api_key",
            "updated_by_agent_api_key",
            "dataset",
            "dataset__project",
            "dataset__created_by_agent_api_key",
            "dataset__updated_by_agent_api_key",
        ).filter(
            dataset__key=self.kwargs["dataset_key"],
            dataset__profile=self.request.user.profile,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        row = self.object
        dataset = row.dataset
        column_definition_list = column_definitions(dataset.headers, dataset.column_schema)
        reference_lookup = _dataset_reference_lookup(
            self.request.user.profile,
            _dataset_reference_columns(column_definition_list),
            [row.data],
        )
        context["dataset"] = dataset
        context["row_cells"] = _row_cells(
            dataset.headers,
            row.data,
            dataset.column_schema,
            relationship_links=_row_relationship_links(dataset, row.data),
            reference_lookup=reference_lookup,
            row_id=row.id,
            image_assets=_image_asset_lookup(dataset, [row]),
            request=self.request,
            profile=self.request.user.profile,
            link_cache={},
        )
        return context


class DatasetSettingsView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_settings.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return _owned_dataset_queryset(self.request.user.profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["public_url"] = self.request.build_absolute_uri(self.object.get_public_url())
        context["project_choices"] = self.request.user.profile.projects.filter(
            archived_at__isnull=True
        )
        context["relationship_target_dataset_choices"] = (
            _owned_dataset_queryset(self.request.user.profile)
            .filter(status=DatasetStatus.READY)
            .exclude(pk=self.object.pk)
            .order_by("name", "-created_at")
        )
        context["column_definitions"] = column_definitions(
            self.object.headers,
            self.object.column_schema,
        )
        context["column_type_choices"] = DatasetColumnType.choices
        context["metadata_json"] = json.dumps(
            self.object.metadata or {},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        context.update(_dataset_relationship_context(self.object))
        return context


@login_required
@require_POST
def project_create(request):
    raw_metadata = request.POST.get("metadata", "").strip()
    if raw_metadata:
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            messages.error(request, "Project metadata must be valid JSON.")
            return redirect("project_list")
    else:
        metadata = {}

    try:
        result = create_profile_project(
            request.user.profile,
            name=request.POST.get("name", ""),
            description=request.POST.get("description", ""),
            metadata=metadata,
        )
    except DatasetServiceError as exc:
        messages.error(request, exc.message)
        return redirect("project_list")

    messages.success(request, "Project created.")
    return redirect("project_detail", project_key=result["project"]["key"])


@login_required
@require_POST
def project_update(request, project_key):
    updates = {}
    if "name" in request.POST:
        updates["name"] = request.POST["name"]
    if "description" in request.POST:
        updates["description"] = request.POST["description"]

    try:
        update_profile_project(
            request.user.profile,
            str(project_key),
            **updates,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Project updated.")

    return redirect("project_detail", project_key=project_key)


@login_required
@require_POST
def project_update_metadata(request, project_key):
    raw_metadata = request.POST.get("metadata", "").strip()
    if raw_metadata:
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            messages.error(request, "Project metadata must be valid JSON.")
            return redirect("project_detail", project_key=project_key)
    else:
        metadata = {}

    try:
        result = update_profile_project_metadata(
            request.user.profile,
            str(project_key),
            metadata=metadata,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        if result["message"] == "No project metadata changes detected.":
            messages.info(request, result["message"])
        else:
            messages.success(request, result["message"])

    return redirect("project_detail", project_key=project_key)


@login_required
@require_POST
def project_delete(request, project_key):
    try:
        profile = request.user.profile
    except ObjectDoesNotExist:
        return HttpResponse("Project not found.", status=404)

    project = get_object_or_404(
        Project,
        key=project_key,
        profile=profile,
    )
    project_name = project.name
    project.delete()
    messages.success(request, f"Deleted {project_name}. Assigned datasets are now ungrouped.")
    return redirect("project_list")


@login_required
@require_POST
def dataset_update_public_settings(request, dataset_key):
    clear_public_password = request.POST.get("clear_public_password") == "on"
    public_password = None
    if not clear_public_password:
        public_password = request.POST.get("public_password") or None
    try:
        update_profile_dataset_public_preview(
            request.user.profile,
            str(dataset_key),
            public_enabled=request.POST.get("public_enabled") == "on",
            public_page_size=normalize_public_page_size(request.POST.get("public_page_size")),
            public_password=public_password,
            clear_public_password=clear_public_password,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Public sharing settings updated.")

    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_update_project(request, dataset_key):
    project_key = request.POST.get("project_key") or None
    try:
        update_profile_dataset_project(request.user.profile, str(dataset_key), project_key)
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Project assignment updated.")

    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_create_relationship(request, dataset_key):
    try:
        create_profile_dataset_relationship(
            request.user.profile,
            str(dataset_key),
            source_column=request.POST.get("source_column", ""),
            target_dataset_key=request.POST.get("target_dataset_key", ""),
            name=request.POST.get("name", ""),
            enforce_integrity=request.POST.get("enforce_integrity") == "on",
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Dataset relationship created.")

    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_delete_relationship(request, dataset_key, relationship_key):
    try:
        delete_profile_dataset_relationship(
            request.user.profile,
            str(dataset_key),
            str(relationship_key),
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Dataset relationship deleted.")

    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_update_metadata(request, dataset_key):
    raw_metadata = request.POST.get("metadata", "").strip()
    if raw_metadata:
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            messages.error(request, "Dataset metadata must be valid JSON.")
            return redirect("dataset_settings", dataset_key=dataset_key)
    else:
        metadata = {}

    try:
        update_profile_dataset_metadata(
            request.user.profile,
            str(dataset_key),
            description=request.POST.get("description", ""),
            instructions=request.POST.get("instructions", ""),
            metadata=metadata,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, "Dataset metadata updated.")

    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_update_column_settings(request, dataset_key):
    column_names = request.POST.getlist("column_name")
    column_types = request.POST.getlist("column_type")
    column_descriptions = request.POST.getlist("column_description")

    has_description_fields = "column_description" in request.POST
    if len(column_names) != len(column_types) or (
        has_description_fields and len(column_names) != len(column_descriptions)
    ):
        messages.error(request, "Column schema settings were incomplete.")
        return redirect("dataset_settings", dataset_key=dataset_key)

    column_schema = {}
    if has_description_fields:
        for column_name, column_type, column_description in zip(
            column_names,
            column_types,
            column_descriptions,
            strict=True,
        ):
            column_schema[column_name] = {
                "type": column_type,
                "description": column_description,
            }
    else:
        # Keep accepting legacy/programmatic POSTs that submit only type values.
        column_schema = dict(zip(column_names, column_types, strict=True))

    try:
        update_profile_dataset_column_types(
            request.user.profile,
            str(dataset_key),
            column_schema,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
        return redirect("dataset_settings", dataset_key=dataset_key)

    messages.success(request, "Column schema updated.")
    return redirect("dataset_settings", dataset_key=dataset_key)


@login_required
@require_POST
def dataset_archive(request, dataset_key):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )
    if dataset.status != DatasetStatus.READY:
        messages.error(request, "Only ready datasets can be archived from the dataset page.")
        return redirect("dataset_detail", dataset_key=dataset_key)

    try:
        result = archive_profile_dataset(request.user.profile, str(dataset_key))
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
        return redirect("dataset_detail", dataset_key=dataset_key)

    if result["message"] == "Dataset was already archived.":
        messages.info(request, result["message"])
    else:
        messages.success(request, result["message"])
    return redirect("dataset_list")


@login_required
@require_POST
def dataset_delete(request, dataset_key):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )
    dataset_name = dataset.name
    _delete_dataset(dataset)
    messages.success(request, f"Deleted {dataset_name}.")

    next_url = request.POST.get("next")
    if next_url in {"home", "settings"}:
        return redirect("home")
    return redirect("dataset_list")


@login_required
def dataset_export(request, dataset_key, export_format):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )
    if dataset.status != DatasetStatus.READY:
        raise Http404("Dataset exports are available after import completes.")

    return _dataset_export_response(dataset, export_format)


@login_required
@require_http_methods(["GET", "HEAD"])
def dataset_asset_content(request, dataset_key, asset_key):
    asset = get_object_or_404(
        DatasetAsset.objects.select_related("dataset"),
        key=asset_key,
        dataset__key=dataset_key,
        dataset__profile=request.user.profile,
    )
    return _dataset_asset_file_response(
        asset,
        request.GET.get("variant", "original"),
        include_body=request.method != "HEAD",
    )


@login_required
def dataset_status(request, dataset_key):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )
    return JsonResponse(
        {
            "status": dataset.status,
            "row_count": dataset.row_count,
            "parse_error": dataset.parse_error,
        }
    )


def _public_access_session_key(dataset: Dataset) -> str:
    return f"{PUBLIC_ACCESS_SESSION_PREFIX}{dataset.public_key}"


def _public_access_session_value(dataset: Dataset) -> str:
    return hashlib.sha256(dataset.public_password_hash.encode()).hexdigest()


def _has_public_dataset_access(request, dataset: Dataset) -> bool:
    return not dataset.is_public_password_protected or request.session.get(
        _public_access_session_key(dataset)
    ) == _public_access_session_value(dataset)


def _handle_public_password_access(
    request,
    dataset: Dataset,
    success_url: str,
) -> tuple[bool, str, HttpResponse | None]:
    password_error = ""
    if request.method == "POST" and dataset.is_public_password_protected:
        password = request.POST.get("password", "")
        if dataset.public_password_matches(password):
            session_key = _public_access_session_key(dataset)
            request.session[session_key] = _public_access_session_value(dataset)
            return True, password_error, redirect(success_url)
        password_error = "That password did not work. Please try again."

    return _has_public_dataset_access(request, dataset), password_error, None


@require_http_methods(["GET", "HEAD", "POST"])
def public_dataset(request, public_key):
    dataset = get_object_or_404(
        Dataset,
        public_key=public_key,
        public_enabled=True,
        status=DatasetStatus.READY,
        archived_at__isnull=True,
    )

    has_access, password_error, password_response = _handle_public_password_access(
        request,
        dataset,
        dataset.get_public_url(),
    )
    if password_response is not None:
        return password_response

    if request.method == "HEAD":
        response = HttpResponse()
        response["X-Robots-Tag"] = PUBLIC_PREVIEW_ROBOTS_POLICY
        return response

    page_obj = None
    public_rows_with_values = []
    if has_access:
        row_queryset, row_query_context = _dataset_row_query_context(
            request,
            dataset,
            dataset.rows.all(),
            include_column_descriptions=False,
        )
        paginator = Paginator(row_queryset, dataset.public_page_size)
        page_obj = paginator.get_page(request.GET.get("page"))
        public_row_objects = list(page_obj.object_list)
        image_asset_lookup = _image_asset_lookup(dataset, public_row_objects)
        for row in public_row_objects:
            row_url = reverse(
                "public_dataset_row_detail",
                kwargs={"public_key": dataset.public_key, "row_id": row.id},
            )
            cells = _row_table_cells(
                dataset.headers,
                row.data,
                column_schema=dataset.column_schema,
                image_assets=image_asset_lookup,
                row_url=row_url,
                row_id=row.id,
                row_number=row.row_number,
                request=request,
                public_context=True,
            )
            public_rows_with_values.append(
                {
                    "values": ordered_row_values(dataset.headers, row.data),
                    "cells": cells,
                    "has_accessible_row_link": any(
                        cell.get("is_row_detail_primary") for cell in cells
                    ),
                    "row_number": row.row_number,
                    "url": row_url,
                }
            )
    else:
        row_query_context = {}

    response = render(
        request,
        "datasets/public_dataset.html",
        {
            "dataset": dataset,
            "has_access": has_access,
            "password_error": password_error,
            "public_preview_robots_policy": PUBLIC_PREVIEW_ROBOTS_POLICY,
            "page_obj": page_obj,
            "public_rows_with_values": public_rows_with_values,
            "public_empty_message": (
                "No rows match these filters."
                if row_query_context.get("has_row_filters")
                else "No rows are available in this preview."
            ),
            "previous_page_url": (
                _querystring_for_page(request, page_obj.previous_page_number())
                if page_obj and page_obj.has_previous()
                else ""
            ),
            "next_page_url": (
                _querystring_for_page(request, page_obj.next_page_number())
                if page_obj and page_obj.has_next()
                else ""
            ),
            **row_query_context,
        },
    )
    response["X-Robots-Tag"] = PUBLIC_PREVIEW_ROBOTS_POLICY
    return response


@require_http_methods(["GET", "HEAD", "POST"])
def public_dataset_row_detail(request, public_key, row_id):
    dataset = get_object_or_404(
        Dataset,
        public_key=public_key,
        public_enabled=True,
        status=DatasetStatus.READY,
        archived_at__isnull=True,
    )
    row_url = reverse(
        "public_dataset_row_detail",
        kwargs={"public_key": dataset.public_key, "row_id": row_id},
    )
    has_access, password_error, password_response = _handle_public_password_access(
        request,
        dataset,
        row_url,
    )
    if password_response is not None:
        return password_response

    if request.method == "HEAD":
        if has_access:
            get_object_or_404(
                DatasetRow.objects.only("id"),
                dataset=dataset,
                id=row_id,
            )
        response = HttpResponse()
        response["X-Robots-Tag"] = PUBLIC_PREVIEW_ROBOTS_POLICY
        return response

    dataset_row = None
    row_cells = []
    if has_access:
        dataset_row = get_object_or_404(
            DatasetRow,
            dataset=dataset,
            id=row_id,
        )
        row_cells = _row_cells(
            dataset.headers,
            dataset_row.data,
            dataset.column_schema,
            row_id=dataset_row.id,
            image_assets=_image_asset_lookup(dataset, [dataset_row]),
            request=request,
            public_context=True,
        )

    response = render(
        request,
        "datasets/public_dataset_row_detail.html",
        {
            "dataset": dataset,
            "dataset_row": dataset_row,
            "has_access": has_access,
            "password_error": password_error,
            "public_preview_robots_policy": PUBLIC_PREVIEW_ROBOTS_POLICY,
            "row_cells": row_cells,
        },
    )
    response["X-Robots-Tag"] = PUBLIC_PREVIEW_ROBOTS_POLICY
    return response


@require_http_methods(["GET", "HEAD"])
def public_dataset_asset_content(request, public_key, asset_key):
    dataset = get_object_or_404(
        Dataset,
        public_key=public_key,
        public_enabled=True,
        status=DatasetStatus.READY,
        archived_at__isnull=True,
    )
    if not _has_public_dataset_access(request, dataset):
        raise Http404("Dataset asset not found.")
    asset = get_object_or_404(
        DatasetAsset.objects.select_related("dataset"),
        key=asset_key,
        dataset=dataset,
    )
    response = _dataset_asset_file_response(
        asset,
        request.GET.get("variant", "original"),
        include_body=request.method != "HEAD",
    )
    response["X-Robots-Tag"] = PUBLIC_PREVIEW_ROBOTS_POLICY
    return response
