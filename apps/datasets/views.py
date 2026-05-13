from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView
from django_q.tasks import async_task

from apps.datasets.choices import DatasetStatus
from apps.datasets.constants import MAX_CSV_UPLOAD_BYTES
from apps.datasets.models import Dataset
from apps.datasets.services import (
    GENERATED_INDEX_CHOICE,
    CSVParseError,
    dataset_name_from_filename,
    iter_indexed_rows,
    prepare_index_config,
    preview_uploaded_table,
    source_text_from_file,
)


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
        return context


@login_required
@require_POST
def dataset_upload_preview(request):
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"ok": False, "error": "Please choose a CSV file."}, status=400)

    filename = uploaded_file.name or "dataset.csv"
    if uploaded_file.size > MAX_CSV_UPLOAD_BYTES:
        return JsonResponse(
            {
                "ok": False,
                "error": "CSV files must be 10 MB or smaller for now.",
            },
            status=400,
        )

    try:
        preview = preview_uploaded_table(uploaded_file, filename)
    except CSVParseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

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
        source_text = dataset.source_text or source_text_from_file(
            dataset.source_file,
            dataset.file_type,
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
        {header: str(row.data.get(header, "")) for header in headers}
        for row in validated_rows[:5]
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
        group="Import CSV dataset",
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
