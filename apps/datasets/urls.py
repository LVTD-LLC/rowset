from django.urls import path

from apps.datasets import views

urlpatterns = [
    path("projects/", views.ProjectListView.as_view(), name="project_list"),
    path("projects/create/", views.project_create, name="project_create"),
    path("projects/<uuid:project_key>/", views.ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<uuid:project_key>/update/", views.project_update, name="project_update"),
    path("datasets/", views.DatasetListView.as_view(), name="dataset_list"),
    path("datasets/<uuid:dataset_key>/", views.DatasetDetailView.as_view(), name="dataset_detail"),
    path(
        "datasets/<uuid:dataset_key>/changes/",
        views.DatasetChangesView.as_view(),
        name="dataset_changes",
    ),
    path(
        "datasets/<uuid:dataset_key>/rows/<int:row_id>/",
        views.DatasetRowDetailView.as_view(),
        name="dataset_row_detail",
    ),
    path("datasets/<uuid:dataset_key>/delete/", views.dataset_delete, name="dataset_delete"),
    path(
        "datasets/<uuid:dataset_key>/export/<str:export_format>/",
        views.dataset_export,
        name="dataset_export",
    ),
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
        "datasets/<uuid:dataset_key>/settings/project/",
        views.dataset_update_project,
        name="dataset_update_project",
    ),
    path(
        "datasets/<uuid:dataset_key>/settings/metadata/",
        views.dataset_update_metadata,
        name="dataset_update_metadata",
    ),
    path(
        "datasets/<uuid:dataset_key>/settings/columns/",
        views.dataset_update_column_settings,
        name="dataset_update_column_settings",
    ),
    path("datasets/<uuid:dataset_key>/status/", views.dataset_status, name="dataset_status"),
    path("share/datasets/<uuid:public_key>/", views.public_dataset, name="public_dataset"),
    path(
        "share/datasets/<uuid:public_key>/rows/<int:row_id>/",
        views.public_dataset_row_detail,
        name="public_dataset_row_detail",
    ),
]
