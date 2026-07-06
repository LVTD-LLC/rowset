from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.api.services import DatasetServiceError
from apps.dataset_plugins.registry import get_dataset_plugin
from apps.dataset_plugins.rendering import dataset_plugin_view_context
from apps.dataset_plugins.services import (
    disable_profile_dataset_plugin,
    enable_profile_dataset_plugin,
    get_profile_dataset_plugin_activation,
)


def _plugin_config_from_post(plugin_slug: str, post_data) -> dict:
    spec = get_dataset_plugin(plugin_slug)
    if spec is None:
        return {"columns": {}}
    columns = {}
    for role in spec.column_roles:
        value = post_data.get(f"column__{role.key}", "").strip()
        if value:
            columns[role.key] = value
    return {"columns": columns}


@login_required
@require_POST
def dataset_enable_plugin(request, dataset_key, plugin_slug):
    try:
        result = enable_profile_dataset_plugin(
            request.user.profile,
            str(dataset_key),
            plugin_slug,
            config=_plugin_config_from_post(plugin_slug, request.POST),
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, result["message"])
    return redirect(f"{reverse('dataset_settings', kwargs={'dataset_key': dataset_key})}#plugins")


@login_required
@require_POST
def dataset_disable_plugin(request, dataset_key, plugin_slug):
    try:
        result = disable_profile_dataset_plugin(
            request.user.profile,
            str(dataset_key),
            plugin_slug,
        )
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        messages.success(request, result["message"])
    return redirect(f"{reverse('dataset_settings', kwargs={'dataset_key': dataset_key})}#plugins")


@login_required
def dataset_plugin_detail(request, dataset_key, plugin_slug):
    try:
        activation = get_profile_dataset_plugin_activation(
            request.user.profile,
            str(dataset_key),
            plugin_slug,
        )
        spec = get_dataset_plugin(plugin_slug)
        if spec is None:
            raise DatasetServiceError(404, "Dataset plugin not found.")
        context = dataset_plugin_view_context(activation)
    except DatasetServiceError as exc:
        raise Http404(exc.message) from exc

    return render(request, spec.view_template_name, context)
