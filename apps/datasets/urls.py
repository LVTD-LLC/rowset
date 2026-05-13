from django.urls import path

from apps.datasets import views

urlpatterns = [
    path("datasets/", views.DatasetListView.as_view(), name="dataset_list"),
    path("datasets/upload/preview/", views.dataset_upload_preview, name="dataset_upload_preview"),
    path("datasets/<uuid:dataset_key>/", views.DatasetDetailView.as_view(), name="dataset_detail"),
    path(
        "datasets/<uuid:dataset_key>/settings/",
        views.DatasetSettingsView.as_view(),
        name="dataset_settings",
    ),
    path(
        "datasets/<uuid:dataset_key>/settings/public/",
        views.dataset_update_public_settings,
        name="dataset_update_public_settings",
    ),
    path(
        "datasets/<uuid:dataset_key>/confirm/",
        views.dataset_confirm_import,
        name="dataset_confirm_import",
    ),
    path("datasets/<uuid:dataset_key>/status/", views.dataset_status, name="dataset_status"),
    path("share/datasets/<uuid:public_key>/", views.public_dataset, name="public_dataset"),
]
