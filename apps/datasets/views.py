import hashlib
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, ListView

from apps.api.services import (
    DatasetServiceError,
    archive_profile_dataset,
    create_profile_dataset_relationship,
    create_profile_project,
    delete_profile_dataset_relationship,
    update_profile_dataset_column_types,
    update_profile_dataset_metadata,
    update_profile_dataset_project,
    update_profile_dataset_public_preview,
    update_profile_project,
    update_profile_project_metadata,
)
from apps.datasets.choices import DatasetColumnType, DatasetStatus
from apps.datasets.models import Dataset, DatasetRow
from apps.datasets.services import (
    ROW_DEFAULT_SORT,
    ROW_FILTER_ABOVE,
    ROW_FILTER_BELOW,
    ROW_FILTER_CONTAINS,
    ROW_FILTER_IS,
    ROW_SORT_DESC,
    apply_dataset_row_query,
    column_definitions,
    dataset_row_filter_operators,
    default_dataset_row_filter_operator,
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

DATASET_SORT_OPTIONS = (
    ("recent", "Recently updated"),
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
DATASET_SORT_ORDERING = {
    "recent": ("-updated_at", "-created_at", "-id"),
    "name": ("name", "id"),
    "rows": ("-row_count", "name", "id"),
    "project": ("project__name", "name", "id"),
}
ARCHIVED_DATASET_SORT_ORDERING = {
    "archived": ("-archived_at", "-updated_at", "-id"),
    "name": ("name", "id"),
    "rows": ("-row_count", "name", "id"),
    "project": ("project__name", "name", "id"),
}
DATASET_LIST_PAGE_SIZE = 100
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
    return {
        "summary": mutation.summary,
        "actor_label": mutation.actor_label,
        "created_at": mutation.created_at,
        "mutation_type_display": mutation.get_mutation_type_display(),
        "field_changes": field_changes,
        "changed_fields": metadata.get("changed_fields") or [],
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


def _row_cells(
    headers: list[str],
    row_data: dict[str, object],
    column_schema: dict | None = None,
    relationship_links: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    ordered_keys = [*headers, *[key for key in row_data if key not in headers]]
    descriptions = {
        column["name"]: column["description"]
        for column in column_definitions(headers, column_schema or {})
    }
    relationship_links = relationship_links or {}
    cells = []
    for header in ordered_keys:
        value = row_data.get(header, "")
        cell = {
            "header": header,
            "description": descriptions.get(header, ""),
            "value": "" if value is None else str(value),
        }
        relationship_link = relationship_links.get(header)
        if relationship_link and cell["value"]:
            cell["relationship_url"] = relationship_link["url"]
            cell["relationship_label"] = relationship_link["label"]
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

        return queryset.order_by(*self.sort_ordering[self.get_selected_sort()])

    def get_total_projects(self, base_queryset):
        return self.request.user.profile.projects.count()

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
        context["has_dataset_filters"] = bool(
            context["search_query"] or context["selected_sort"] != self.default_sort
        )
        context["dataset_list_reset_url"] = reverse(self.dataset_list_url_name)
        context["dataset_list_is_archived"] = self.dataset_list_is_archived
        context["dataset_list_eyebrow"] = self.dataset_list_eyebrow
        context["dataset_list_title"] = self.dataset_list_title
        context["dataset_list_description"] = self.dataset_list_description
        context["dataset_table_caption"] = self.dataset_table_caption
        context["dataset_table_date_heading"] = self.dataset_table_date_heading
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
        context["dataset_groups"] = self.get_dataset_groups(context["datasets"])
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
        return self.request.user.profile.projects.annotate(
            dataset_count=_visible_project_dataset_count()
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
        return self.request.user.profile.projects.annotate(
            dataset_count=_visible_project_dataset_count()
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
        rows_with_values = [
            {
                "values": ordered_row_values(dataset.headers, row.data),
                "actor_label": row.updated_by_actor_label,
                "row_number": row.row_number,
                "url": reverse(
                    "dataset_row_detail",
                    kwargs={"dataset_key": dataset.key, "row_id": row.id},
                ),
            }
            for row in row_page_obj.object_list
        ]
        if not has_imported_rows:
            rows_with_values = [
                {
                    "values": ordered_row_values(dataset.headers, preview_row),
                    "actor_label": "",
                    "row_number": row_number,
                    "url": "",
                }
                for row_number, preview_row in enumerate(
                    dataset.preview_rows[:DATASET_DETAIL_ROW_PAGE_SIZE],
                    start=1,
                )
            ]
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
        context["dataset"] = dataset
        context["row_cells"] = _row_cells(
            dataset.headers,
            row.data,
            dataset.column_schema,
            relationship_links=_row_relationship_links(dataset, row.data),
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
        context["project_choices"] = self.request.user.profile.projects.all()
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


@require_http_methods(["GET", "POST"])
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
        public_rows_with_values = [
            {
                "values": ordered_row_values(dataset.headers, row.data),
                "row_number": row.row_number,
                "url": reverse(
                    "public_dataset_row_detail",
                    kwargs={"public_key": dataset.public_key, "row_id": row.id},
                ),
            }
            for row in page_obj.object_list
        ]
    else:
        row_query_context = {}

    return render(
        request,
        "datasets/public_dataset.html",
        {
            "dataset": dataset,
            "has_access": has_access,
            "password_error": password_error,
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


@require_http_methods(["GET", "POST"])
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

    dataset_row = None
    row_cells = []
    if has_access:
        dataset_row = get_object_or_404(
            DatasetRow,
            dataset=dataset,
            id=row_id,
        )
        row_cells = _row_cells(dataset.headers, dataset_row.data)

    return render(
        request,
        "datasets/public_dataset_row_detail.html",
        {
            "dataset": dataset,
            "dataset_row": dataset_row,
            "has_access": has_access,
            "password_error": password_error,
            "row_cells": row_cells,
        },
    )
