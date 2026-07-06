from django.urls import path

from apps.datasets import views

urlpatterns = [
    path("search/", views.command_palette_search, name="command_palette_search"),
    path("projects/create/", views.project_create, name="project_create"),
    path("projects/<uuid:project_key>/", views.ProjectDetailView.as_view(), name="project_detail"),
    path(
        "projects/<uuid:project_key>/settings/",
        views.ProjectSettingsView.as_view(),
        name="project_settings",
    ),
    path("projects/<uuid:project_key>/update/", views.project_update, name="project_update"),
    path(
        "projects/<uuid:project_key>/metadata/",
        views.project_update_metadata,
        name="project_update_metadata",
    ),
    path(
        "projects/<uuid:project_key>/sections/create/",
        views.project_section_create,
        name="project_section_create",
    ),
    path(
        "projects/<uuid:project_key>/sections/<uuid:section_key>/delete/",
        views.project_section_delete,
        name="project_section_delete",
    ),
    path("projects/<uuid:project_key>/delete/", views.project_delete, name="project_delete"),
    path(
        "datasets/archived/",
        views.ArchivedDatasetListView.as_view(),
        name="archived_dataset_list",
    ),
    path("datasets/<uuid:dataset_key>/", views.DatasetDetailView.as_view(), name="dataset_detail"),
    path(
        "datasets/<uuid:dataset_key>/changes/",
        views.DatasetChangesView.as_view(),
        name="dataset_changes",
    ),
    path(
        "datasets/<uuid:dataset_key>/rows/create/",
        views.DatasetRowCreateView.as_view(),
        name="dataset_row_create",
    ),
    path(
        "datasets/<uuid:dataset_key>/rows/actions/",
        views.dataset_rows_bulk_action,
        name="dataset_rows_bulk_action",
    ),
    path(
        "datasets/<uuid:dataset_key>/rows/<int:row_id>/",
        views.DatasetRowDetailView.as_view(),
        name="dataset_row_detail",
    ),
    path(
        "datasets/<uuid:dataset_key>/archive/",
        views.dataset_archive,
        name="dataset_archive",
    ),
    path("datasets/<uuid:dataset_key>/delete/", views.dataset_delete, name="dataset_delete"),
    path(
        "datasets/<uuid:dataset_key>/export/<str:export_format>/",
        views.dataset_export,
        name="dataset_export",
    ),
    path(
        "datasets/<uuid:dataset_key>/assets/<uuid:asset_key>/content/",
        views.dataset_asset_content,
        name="dataset_asset_content",
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
        "datasets/<uuid:dataset_key>/settings/relationships/",
        views.dataset_create_relationship,
        name="dataset_create_relationship",
    ),
    path(
        "datasets/<uuid:dataset_key>/settings/relationships/<uuid:relationship_key>/delete/",
        views.dataset_delete_relationship,
        name="dataset_delete_relationship",
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
    path(
        "share/datasets/<uuid:public_key>/assets/<uuid:asset_key>/content/",
        views.public_dataset_asset_content,
        name="public_dataset_asset_content",
    ),
]
