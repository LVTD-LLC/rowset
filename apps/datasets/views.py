import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, ListView
from django_q.tasks import async_task

from apps.datasets.choices import DatasetStatus
from apps.datasets.constants import MAX_CSV_UPLOAD_BYTES
from apps.datasets.models import Dataset
from apps.datasets.services import (
    GENERATED_INDEX_CHOICE,
    GOOGLE_SHEETS_FILE_TYPE,
    CSVParseError,
    dataset_name_from_filename,
    iter_indexed_rows,
    normalize_public_page_size,
    prepare_index_config,
    preview_google_sheet_url,
    preview_uploaded_table,
    source_text_from_file,
)

PUBLIC_ACCESS_SESSION_PREFIX = "public_dataset_access_"


class DatasetListView(LoginRequiredMixin, ListView):
    template_name = "datasets/dataset_list.html"
    context_object_name = "datasets"

    def get_queryset(self):
        return self.request.user.profile.datasets.all()


class DatasetDetailView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_detail.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return self.request.user.profile.datasets.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dataset = self.object
        context["sample_rows"] = dataset.rows.all()[:5]
        context["api_key"] = self.request.user.profile.key
        context["api_base_url"] = self.request.build_absolute_uri("/api").rstrip("/")
        context["public_url"] = self.request.build_absolute_uri(dataset.get_public_url())
        return context


class DatasetSettingsView(LoginRequiredMixin, DetailView):
    template_name = "datasets/dataset_settings.html"
    context_object_name = "dataset"
    slug_url_kwarg = "dataset_key"
    slug_field = "key"

    def get_queryset(self):
        return self.request.user.profile.datasets.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["public_url"] = self.request.build_absolute_uri(self.object.get_public_url())
        return context


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
def dataset_upload_preview(request):
    uploaded_file = request.FILES.get("file")
    google_sheets_url = request.POST.get("google_sheets_url", "").strip()

    if google_sheets_url:
        return _dataset_google_sheets_preview(request, google_sheets_url)

    if not uploaded_file:
        return JsonResponse(
            {
                "ok": False,
                "error": "Please choose a CSV/Parquet file or paste a Google Sheets link.",
            },
            status=400,
        )

    filename = uploaded_file.name or "dataset.csv"
    if uploaded_file.size > MAX_CSV_UPLOAD_BYTES:
        return JsonResponse(
            {
                "ok": False,
                "error": "Dataset files must be 10 MB or smaller for now.",
            },
            status=400,
        )

    try:
        preview = preview_uploaded_table(uploaded_file, filename)
    except CSVParseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    if len(preview.source_text.encode("utf-8")) > MAX_CSV_UPLOAD_BYTES:
        return JsonResponse(
            {
                "ok": False,
                "error": "Parsed dataset content must be 10 MB or smaller for now.",
            },
            status=400,
        )

    dataset = Dataset.objects.create(
        profile=request.user.profile,
        name=dataset_name_from_filename(filename),
        original_filename=filename,
        file_type=preview.file_type,
        source_file=uploaded_file,
        source_text=preview.source_text,
        headers=preview.headers,
        preview_rows=preview.preview_rows,
        row_count=preview.row_count,
        status=DatasetStatus.PREVIEWED,
    )
    return _dataset_preview_response(dataset)


def _dataset_google_sheets_preview(request, google_sheets_url: str):
    try:
        preview = preview_google_sheet_url(google_sheets_url)
    except CSVParseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    if len(preview.source_text.encode("utf-8")) > MAX_CSV_UPLOAD_BYTES:
        return JsonResponse(
            {
                "ok": False,
                "error": "Google Sheets exports must be 10 MB or smaller for now.",
            },
            status=400,
        )

    dataset = Dataset.objects.create(
        profile=request.user.profile,
        name="Google Sheet",
        original_filename="Google Sheets import",
        file_type=GOOGLE_SHEETS_FILE_TYPE,
        source_url=google_sheets_url,
        source_text=preview.source_text,
        headers=preview.headers,
        preview_rows=preview.preview_rows,
        row_count=preview.row_count,
        status=DatasetStatus.PREVIEWED,
    )

    return _dataset_preview_response(dataset)


def _dataset_preview_response(dataset: Dataset):
    return JsonResponse(
        {
            "ok": True,
            "dataset": {
                "key": str(dataset.key),
                "name": dataset.name,
                "filename": dataset.original_filename,
                "status": dataset.status,
                "headers": dataset.headers,
                "preview_rows": dataset.preview_rows,
                "row_count": dataset.row_count,
                "generated_index_choice": GENERATED_INDEX_CHOICE,
                "confirm_url": reverse(
                    "dataset_confirm_import",
                    kwargs={"dataset_key": dataset.key},
                ),
                "detail_url": dataset.get_absolute_url(),
            },
        }
    )


@login_required
@require_POST
def dataset_confirm_import(request, dataset_key):
    dataset = get_object_or_404(
        Dataset,
        key=dataset_key,
        profile=request.user.profile,
    )

    if dataset.status in {DatasetStatus.READY, DatasetStatus.PROCESSING}:
        return redirect(dataset.get_absolute_url())

    selected_index = request.POST.get("index_column", "")
    try:
        index_column, index_generated, headers = prepare_index_config(
            dataset.headers,
            selected_index,
        )
        # Validate uniqueness before queueing the import so users get immediate feedback.
        source_text = dataset.source_text
        if not source_text and dataset.source_file:
            source_text = source_text_from_file(dataset.source_file, dataset.file_type)
        if not source_text:
            raise CSVParseError(
                "Could not find stored dataset content. Please upload the dataset again."
            )
        validated_rows = list(
            iter_indexed_rows(
                file_type=dataset.file_type,
                source_text=source_text,
                headers=headers,
                index_column=index_column,
                index_generated=index_generated,
            )
        )
    except CSVParseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    dataset.status = DatasetStatus.PROCESSING
    dataset.confirmed_at = timezone.now()
    dataset.parse_error = ""
    dataset.index_column = index_column
    dataset.index_generated = index_generated
    dataset.headers = headers
    dataset.preview_rows = [
        {header: str(row.data.get(header, "")) for header in headers} for row in validated_rows[:5]
    ]
    dataset.save(
        update_fields=[
            "status",
            "confirmed_at",
            "parse_error",
            "index_column",
            "index_generated",
            "headers",
            "preview_rows",
            "updated_at",
        ]
    )
    async_task(
        "apps.datasets.tasks.import_dataset_rows",
        dataset.id,
        group="Import dataset",
    )
    return redirect(dataset.get_absolute_url())


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
    if has_access:
        paginator = Paginator(dataset.rows.all(), dataset.public_page_size)
        page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "datasets/public_dataset.html",
        {
            "dataset": dataset,
            "has_access": has_access,
            "password_error": password_error,
            "page_obj": page_obj,
        },
    )
