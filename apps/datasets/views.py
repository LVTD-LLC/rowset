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
    CSVParseError,
    dataset_name_from_filename,
    preview_csv_file,
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
    if not filename.lower().endswith(".csv"):
        return JsonResponse(
            {"ok": False, "error": "For now, FileBridge only accepts CSV files."},
            status=400,
        )

    if uploaded_file.size > MAX_CSV_UPLOAD_BYTES:
        return JsonResponse(
            {
                "ok": False,
                "error": "CSV files must be 10 MB or smaller for now.",
            },
            status=400,
        )

    try:
        preview = preview_csv_file(uploaded_file)
    except CSVParseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    dataset = Dataset.objects.create(
        profile=request.user.profile,
        name=dataset_name_from_filename(filename),
        original_filename=filename,
        source_file=uploaded_file,
        source_text=preview.text,
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

    dataset.status = DatasetStatus.PROCESSING
    dataset.confirmed_at = timezone.now()
    dataset.parse_error = ""
    dataset.save(update_fields=["status", "confirmed_at", "parse_error", "updated_at"])
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
