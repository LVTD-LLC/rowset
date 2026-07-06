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
    dataset_plugin_marketplace_context,
    disable_profile_dataset_plugin,
    enable_profile_dataset_plugin,
    get_profile_dataset_plugin_activation,
    install_profile_dataset_plugin,
    profile_can_use_dataset_plugins,
    uninstall_profile_dataset_plugin,
)


def _require_dataset_plugins_staff(request) -> None:
    if not profile_can_use_dataset_plugins(request.user.profile):
        raise Http404("Dataset plugin not found.")


def _plugin_config_from_post(plugin_slug: str, post_data) -> dict:
    try:
        spec = get_dataset_plugin(plugin_slug)
    except ValueError:
        return {"columns": {}}
    if spec is None:
        return {"columns": {}}
    columns = {}
    for role in spec.column_roles:
        value = post_data.get(f"column__{role.key}", "").strip()
        if value:
            columns[role.key] = value
    return {"columns": columns}


@login_required
def plugin_marketplace(request):
    _require_dataset_plugins_staff(request)
    return render(
        request,
        "plugins/plugin_marketplace.html",
        {"plugin_rows": dataset_plugin_marketplace_context(request.user.profile)},
    )


@login_required
@require_POST
def plugin_install(request, plugin_slug):
    _require_dataset_plugins_staff(request)
    try:
        installation, created = install_profile_dataset_plugin(request.user.profile, plugin_slug)
        spec = get_dataset_plugin(installation.plugin_slug)
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        name = spec.name if spec else installation.plugin_slug
        if created:
            messages.success(request, f"{name} installed.")
        else:
            messages.info(request, f"{name} is already installed.")
    return redirect("plugin_marketplace")


@login_required
@require_POST
def plugin_uninstall(request, plugin_slug):
    _require_dataset_plugins_staff(request)
    try:
        removed = uninstall_profile_dataset_plugin(request.user.profile, plugin_slug)
    except DatasetServiceError as exc:
        if exc.status_code == 404:
            raise Http404(exc.message) from exc
        messages.error(request, exc.message)
    else:
        spec = get_dataset_plugin(plugin_slug)
        name = spec.name if spec else plugin_slug
        if removed:
            messages.success(request, f"{name} removed from this account.")
        else:
            messages.info(request, f"{name} was not installed.")
    return redirect("plugin_marketplace")


@login_required
@require_POST
def dataset_enable_plugin(request, dataset_key, plugin_slug):
    _require_dataset_plugins_staff(request)
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
    _require_dataset_plugins_staff(request)
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
    _require_dataset_plugins_staff(request)
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
