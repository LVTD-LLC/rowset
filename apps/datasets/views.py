import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, ListView

from apps.api.services import (
    DatasetServiceError,
    create_profile_project,
    update_profile_dataset_project,
)
from apps.datasets.choices import DatasetColumnType, DatasetStatus
from apps.datasets.models import Dataset
from apps.datasets.services import (
    CSVParseError,
    column_definitions,
    normalize_column_schema,
    normalize_public_page_size,
    ordered_row_values,
    rows_to_csv_text,
    rows_to_parquet_bytes,
)

PUBLIC_ACCESS_SESSION_PREFIX = "public_dataset_access_"

DATASET_SORT_OPTIONS = (
    ("recent", "Recently updated"),
    ("name", "Name"),
    ("rows", "Rows"),
    ("project", "Project"),
)
DATASET_SORT_ORDERING = {
    "recent": ("-updated_at", "-created_at"),
    "name": ("name", "-updated_at"),
    "rows": ("-row_count", "name"),
    "project": ("project__name", "name"),
}


def _visible_project_dataset_count():
    return Count("datasets", filter=~Q(datasets__status=DatasetStatus.PREVIEWED))


def _delete_dataset(dataset: Dataset) -> None:
    if dataset.source_file:
        dataset.source_file.delete(save=False)
    dataset.delete()


def _dataset_export_filename(dataset: Dataset, extension: str) -> str:
    name = f"{dataset.name or 'dataset'}".strip().replace("/", "-") or "dataset"
    return f"{name}.{extension}"


class DatasetListView(LoginRequiredMixin, ListView):
    template_name = "datasets/dataset_list.html"
    context_object_name = "datasets"

    def get_search_query(self) -> str:
        return self.request.GET.get("q", "").strip()

    def get_selected_sort(self) -> str:
        selected_sort = self.request.GET.get("sort", "recent")
        if selected_sort not in DATASET_SORT_ORDERING:
            return "recent"
        return selected_sort

    def get_base_queryset(self):
        return self.request.user.profile.datasets.select_related("project").exclude(
            status=DatasetStatus.PREVIEWED
        )

    def get_queryset(self):
        queryset = self.get_base_queryset()
        search_query = self.get_search_query()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query)
                | Q(original_filename__icontains=search_query)
                | Q(project__name__icontains=search_query)
            )

        return queryset.order_by(*DATASET_SORT_ORDERING[self.get_selected_sort()])

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
            "total_projects": self.request.user.profile.projects.count(),
        }
        context["search_query"] = self.get_search_query()
        context["selected_sort"] = self.get_selected_sort()
        context["sort_options"] = DATASET_SORT_OPTIONS
        context["has_dataset_filters"] = bool(
            context["search_query"] or context["selected_sort"] != "recent"
        )
        return context


class ProjectListView(LoginRequiredMixin, ListView):
    template_name = "datasets/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        return self.request.user.profile.projects.annotate(
            dataset_count=_visible_project_dataset_count()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ungrouped_dataset_count"] = self.request.user.profile.datasets.filter(
            project__isnull=True,
        ).exclude(status=DatasetStatus.PREVIEWED).count()
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
            self.object.datasets.exclude(status=DatasetStatus.PREVIEWED).order_by("-updated_at"),
            100,
        )
        page_obj = paginator.get_page(self.request.GET.get("page"))
        context["page_obj"] = page_obj
        context["datasets"] = page_obj.object_list
        return context


class DatasetDetailView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_detail.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return self.request.user.profile.datasets.select_related("project").all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dataset = self.object
        sample_rows = dataset.rows.all()[:5]
        sample_row_values = [ordered_row_values(dataset.headers, row.data) for row in sample_rows]
        if not sample_row_values:
            sample_row_values = [
                ordered_row_values(dataset.headers, preview_row)
                for preview_row in dataset.preview_rows[:5]
            ]
        context["sample_row_values"] = sample_row_values
        context["public_url"] = self.request.build_absolute_uri(dataset.get_public_url())
        return context


class DatasetSettingsView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_settings.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return self.request.user.profile.datasets.select_related("project").all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["public_url"] = self.request.build_absolute_uri(self.object.get_public_url())
        context["project_choices"] = self.request.user.profile.projects.all()
        context["column_definitions"] = column_definitions(
            self.object.headers,
            self.object.column_schema,
        )
        context["column_type_choices"] = DatasetColumnType.choices
        return context


@login_required
@require_POST
def project_create(request):
    try:
        result = create_profile_project(
            request.user.profile,
            name=request.POST.get("name", ""),
            description=request.POST.get("description", ""),
        )
    except DatasetServiceError as exc:
        messages.error(request, exc.message)
        return redirect("project_list")

    messages.success(request, "Project created.")
    return redirect("project_detail", project_key=result["project"]["key"])


@login_required
@require_POST
def dataset_update_public_settings(request, dataset_key):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )

    dataset.public_enabled = request.POST.get("public_enabled") == "on"
    dataset.public_page_size = normalize_public_page_size(request.POST.get("public_page_size"))

    password = request.POST.get("public_password", "")
    clear_password = request.POST.get("clear_public_password") == "on"
    if clear_password:
        dataset.public_password_hash = ""
    elif password:
        dataset.public_password_hash = make_password(password)

    dataset.save(
        update_fields=[
            "public_enabled",
            "public_page_size",
            "public_password_hash",
            "updated_at",
        ]
    )
    messages.success(request, "Public sharing settings updated.")
    return redirect(dataset.get_settings_url())


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
def dataset_update_column_settings(request, dataset_key):
    column_names = request.POST.getlist("column_name")
    column_types = request.POST.getlist("column_type")

    with transaction.atomic():
        dataset = get_object_or_404(
            Dataset.objects.select_for_update(),
            key=dataset_key,
            profile=request.user.profile,
        )

        if len(column_names) != len(column_types):
            messages.error(request, "Column type settings were incomplete.")
            return redirect(dataset.get_settings_url())

        if dataset.status == DatasetStatus.PROCESSING:
            messages.error(
                request,
                "Column types cannot be updated while the dataset is processing.",
            )
            return redirect(dataset.get_settings_url())

        try:
            dataset.column_schema = normalize_column_schema(
                dataset.headers,
                dict(zip(column_names, column_types, strict=True)),
                fallback_schema=dataset.column_schema,
                reject_unknown=True,
            )
        except CSVParseError as exc:
            messages.error(request, str(exc))
            return redirect(dataset.get_settings_url())

        dataset.save(update_fields=["column_schema", "updated_at"])

    messages.success(request, "Column types updated.")
    return redirect(dataset.get_settings_url())


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

    rows = list(dataset.rows.all())
    if export_format == "csv":
        response = HttpResponse(
            rows_to_csv_text(dataset.headers, rows),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = content_disposition_header(
            True,
            _dataset_export_filename(dataset, "csv"),
        )
        return response

    if export_format == "parquet":
        response = HttpResponse(
            rows_to_parquet_bytes(dataset.headers, rows),
            content_type="application/vnd.apache.parquet",
        )
        response["Content-Disposition"] = content_disposition_header(
            True,
            _dataset_export_filename(dataset, "parquet"),
        )
        return response

    raise Http404("Unsupported export format.")


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


@require_http_methods(["GET", "POST"])
def public_dataset(request, public_key):
    dataset = get_object_or_404(
        Dataset,
        public_key=public_key,
        public_enabled=True,
        status=DatasetStatus.READY,
    )

    session_key = _public_access_session_key(dataset)
    password_error = ""
    has_access = not dataset.is_public_password_protected or request.session.get(
        session_key
    ) == _public_access_session_value(dataset)

    if request.method == "POST" and dataset.is_public_password_protected:
        password = request.POST.get("password", "")
        if dataset.public_password_matches(password):
            request.session[session_key] = _public_access_session_value(dataset)
            return redirect(dataset.get_public_url())
        password_error = "That password did not work. Please try again."

    page_obj = None
    public_row_values = []
    if has_access:
        paginator = Paginator(dataset.rows.all(), dataset.public_page_size)
        page_obj = paginator.get_page(request.GET.get("page"))
        public_row_values = [
            ordered_row_values(dataset.headers, row.data)
            for row in page_obj.object_list
        ]

    return render(
        request,
        "datasets/public_dataset.html",
        {
            "dataset": dataset,
            "has_access": has_access,
            "password_error": password_error,
            "page_obj": page_obj,
            "public_row_values": public_row_values,
        },
    )
