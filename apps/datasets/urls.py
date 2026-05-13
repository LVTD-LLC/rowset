from django.urls import path

from apps.datasets import views

urlpatterns = [
    path("datasets/", views.DatasetListView.as_view(), name="dataset_list"),
    path("datasets/upload/preview/", views.dataset_upload_preview, name="dataset_upload_preview"),
    path("datasets/<uuid:dataset_key>/", views.DatasetDetailView.as_view(), name="dataset_detail"),
    path(
        "datasets/<uuid:dataset_key>/confirm/",
        views.dataset_confirm_import,
        name="dataset_confirm_import",
    ),
    path("datasets/<uuid:dataset_key>/status/", views.dataset_status, name="dataset_status"),
]
