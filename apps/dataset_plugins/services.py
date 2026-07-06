from typing import Any

from django.db import transaction

from apps.api.services import DatasetServiceError, get_profile_dataset
from apps.core.models import AgentApiKey, Profile
from apps.dataset_plugins.models import DatasetPluginActivation
from apps.dataset_plugins.registry import (
    DatasetPluginSpec,
    get_dataset_plugin,
    iter_dataset_plugins,
    serialize_dataset_plugin,
)
from apps.datasets.choices import DatasetStatus
from apps.datasets.models import Dataset

PLUGIN_CONFIG_COLUMNS_KEY = "columns"


def _normalized_header_key(value: object) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def _header_lookup(dataset: Dataset) -> dict[str, str]:
    return {_normalized_header_key(header): header for header in dataset.headers}


def _configured_header(
    dataset: Dataset,
    raw_header: object,
) -> str:
    header = str(raw_header or "").strip()
    if not header:
        return ""
    if header in dataset.headers:
        return header
    normalized_match = _header_lookup(dataset).get(_normalized_header_key(header), "")
    if normalized_match:
        return normalized_match
    raise DatasetServiceError(400, f"Column '{header}' is not in this dataset.")


def _autodetect_role_header(dataset: Dataset, aliases: tuple[str, ...]) -> str:
    lookup = _header_lookup(dataset)
    for alias in aliases:
        header = lookup.get(_normalized_header_key(alias))
        if header:
            return header
    return ""


def _validate_ready_dataset(dataset: Dataset) -> None:
    if dataset.archived_at is not None:
        raise DatasetServiceError(409, "Archived datasets cannot use dataset plugins.")
    if dataset.status != DatasetStatus.READY:
        raise DatasetServiceError(409, "Dataset plugins are available after a dataset is ready.")


def _normalize_plugin_config(
    dataset: Dataset,
    spec: DatasetPluginSpec,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise DatasetServiceError(400, "Dataset plugin config must be a JSON object.")

    raw_columns = config.get(PLUGIN_CONFIG_COLUMNS_KEY, {})
    if raw_columns is None:
        raw_columns = {}
    if not isinstance(raw_columns, dict):
        raise DatasetServiceError(400, "Dataset plugin config columns must be a JSON object.")

    unknown_roles = sorted(set(raw_columns) - {role.key for role in spec.column_roles})
    if unknown_roles:
        joined = ", ".join(unknown_roles)
        raise DatasetServiceError(400, f"Unknown dataset plugin column roles: {joined}.")

    columns = {}
    for role in spec.column_roles:
        configured = _configured_header(dataset, raw_columns.get(role.key))
        header = configured or _autodetect_role_header(dataset, (role.key, *role.aliases))
        if not header:
            if role.required:
                raise DatasetServiceError(
                    400,
                    f"Plugin '{spec.name}' requires a column for {role.label}.",
                )
            continue
        columns[role.key] = header

    return {PLUGIN_CONFIG_COLUMNS_KEY: columns}


def _get_plugin_or_raise(plugin_slug: str) -> DatasetPluginSpec:
    try:
        spec = get_dataset_plugin(plugin_slug)
    except ValueError as exc:
        raise DatasetServiceError(404, "Dataset plugin not found.") from exc
    if spec is None:
        raise DatasetServiceError(404, "Dataset plugin not found.")
    return spec


def serialize_dataset_plugin_activation(
    activation: DatasetPluginActivation,
    *,
    plugin: DatasetPluginSpec | None = None,
) -> dict[str, Any]:
    spec = plugin or _get_plugin_or_raise(activation.plugin_slug)
    return {
        "id": activation.id,
        "dataset": str(activation.dataset.key),
        "plugin_slug": activation.plugin_slug,
        "plugin": serialize_dataset_plugin(spec),
        "enabled": activation.enabled,
        "config": activation.config or {},
        "view_url": activation.get_absolute_url(),
        "created_at": activation.created_at,
        "updated_at": activation.updated_at,
    }


def list_available_dataset_plugins(profile: Profile | None = None) -> dict[str, Any]:
    return {"plugins": [serialize_dataset_plugin(plugin) for plugin in iter_dataset_plugins()]}


def list_profile_dataset_plugin_activations(profile: Profile, dataset_key: str) -> dict[str, Any]:
    dataset = get_profile_dataset(profile, dataset_key)
    activations = (
        DatasetPluginActivation.objects.select_related("dataset")
        .filter(profile=profile, dataset=dataset)
        .order_by("plugin_slug", "id")
    )
    return {
        "dataset": str(dataset.key),
        "available_plugins": list_available_dataset_plugins(profile)["plugins"],
        "activations": [
            serialize_dataset_plugin_activation(activation) for activation in activations
        ],
    }


def dataset_plugin_settings_context(dataset: Dataset) -> list[dict[str, Any]]:
    activations = {
        activation.plugin_slug: activation
        for activation in DatasetPluginActivation.objects.select_related("dataset").filter(
            profile=dataset.profile,
            dataset=dataset,
        )
    }
    entries = []
    for spec in iter_dataset_plugins():
        activation = activations.get(spec.slug)
        selected_columns = {}
        validation_error = ""
        try:
            selected_columns = _normalize_plugin_config(
                dataset,
                spec,
                activation.config if activation else None,
            )[PLUGIN_CONFIG_COLUMNS_KEY]
        except DatasetServiceError as exc:
            selected_columns = (
                (activation.config or {}).get(PLUGIN_CONFIG_COLUMNS_KEY, {}) if activation else {}
            )
            validation_error = exc.message if activation else ""

        entries.append(
            {
                "plugin": serialize_dataset_plugin(spec),
                "activation": (
                    serialize_dataset_plugin_activation(activation, plugin=spec)
                    if activation
                    else None
                ),
                "enabled": bool(activation and activation.enabled),
                "roles": [
                    {
                        **role_payload,
                        "selected_column": selected_columns.get(role_payload["key"], ""),
                    }
                    for role_payload in serialize_dataset_plugin(spec)["column_roles"]
                ],
                "validation_error": validation_error,
            }
        )
    return entries


def enabled_dataset_plugin_links(dataset: Dataset) -> list[dict[str, Any]]:
    activations = (
        DatasetPluginActivation.objects.select_related("dataset")
        .filter(profile=dataset.profile, dataset=dataset, enabled=True)
        .order_by("plugin_slug", "id")
    )
    links = []
    for activation in activations:
        try:
            links.append(serialize_dataset_plugin_activation(activation))
        except DatasetServiceError:
            continue
    return links


def enable_profile_dataset_plugin(
    profile: Profile,
    dataset_key: str,
    plugin_slug: str,
    config: dict[str, Any] | None = None,
    agent_api_key: AgentApiKey | None = None,
) -> dict[str, Any]:
    spec = _get_plugin_or_raise(plugin_slug)
    with transaction.atomic():
        dataset = get_profile_dataset(profile, dataset_key)
        dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
        _validate_ready_dataset(dataset)
        normalized_config = _normalize_plugin_config(dataset, spec, config)
        activation, created = DatasetPluginActivation.objects.select_for_update().get_or_create(
            profile=profile,
            dataset=dataset,
            plugin_slug=spec.slug,
            defaults={
                "enabled": True,
                "config": normalized_config,
                "created_by_agent_api_key": agent_api_key,
                "updated_by_agent_api_key": agent_api_key,
            },
        )
        if not created:
            activation.enabled = True
            activation.config = normalized_config
            activation.updated_by_agent_api_key = agent_api_key
            activation.save(
                update_fields=[
                    "enabled",
                    "config",
                    "updated_by_agent_api_key",
                    "updated_at",
                ]
            )

    return {
        "status": "success",
        "message": f"{spec.name} plugin enabled.",
        "activation": serialize_dataset_plugin_activation(activation, plugin=spec),
    }


def disable_profile_dataset_plugin(
    profile: Profile,
    dataset_key: str,
    plugin_slug: str,
    agent_api_key: AgentApiKey | None = None,
) -> dict[str, Any]:
    spec = _get_plugin_or_raise(plugin_slug)
    with transaction.atomic():
        dataset = get_profile_dataset(profile, dataset_key)
        activation = (
            DatasetPluginActivation.objects.select_for_update()
            .select_related("dataset")
            .filter(profile=profile, dataset=dataset, plugin_slug=spec.slug)
            .first()
        )
        if activation is None:
            raise DatasetServiceError(404, "Dataset plugin activation not found.")
        activation.enabled = False
        activation.updated_by_agent_api_key = agent_api_key
        activation.save(update_fields=["enabled", "updated_by_agent_api_key", "updated_at"])

    return {
        "status": "success",
        "message": f"{spec.name} plugin disabled.",
        "activation": serialize_dataset_plugin_activation(activation, plugin=spec),
    }


def get_profile_dataset_plugin_activation(
    profile: Profile,
    dataset_key: str,
    plugin_slug: str,
    *,
    require_enabled: bool = True,
) -> DatasetPluginActivation:
    spec = _get_plugin_or_raise(plugin_slug)
    dataset = get_profile_dataset(profile, dataset_key)
    activation = (
        DatasetPluginActivation.objects.select_related("dataset")
        .filter(profile=profile, dataset=dataset, plugin_slug=spec.slug)
        .first()
    )
    if activation is None or (require_enabled and not activation.enabled):
        raise DatasetServiceError(404, "Dataset plugin activation not found.")
    return activation
