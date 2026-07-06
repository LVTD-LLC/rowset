import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatasetPluginColumnRole:
    key: str
    label: str
    description: str
    required: bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DatasetPluginSpec:
    slug: str
    name: str
    description: str
    column_roles: tuple[DatasetPluginColumnRole, ...]
    view_template_name: str
    supports_public: bool = False


_PLUGIN_REGISTRY: dict[str, DatasetPluginSpec] = {}


def normalize_plugin_slug(slug: str) -> str:
    normalized = str(slug or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", normalized):
        raise ValueError(
            "Dataset plugin slugs must contain letters, numbers, dashes, or underscores."
        )
    return normalized


def register_dataset_plugin(spec: DatasetPluginSpec) -> DatasetPluginSpec:
    slug = normalize_plugin_slug(spec.slug)
    if slug != spec.slug:
        raise ValueError("Dataset plugin spec slug must already be normalized.")
    if slug in _PLUGIN_REGISTRY:
        existing = _PLUGIN_REGISTRY[slug]
        if existing == spec:
            return spec
        raise ValueError(f"Dataset plugin '{slug}' is already registered.")
    _PLUGIN_REGISTRY[slug] = spec
    return spec


def get_dataset_plugin(slug: str) -> DatasetPluginSpec | None:
    return _PLUGIN_REGISTRY.get(normalize_plugin_slug(slug))


def iter_dataset_plugins() -> list[DatasetPluginSpec]:
    return sorted(_PLUGIN_REGISTRY.values(), key=lambda plugin: plugin.name.lower())


def serialize_dataset_plugin_role(role: DatasetPluginColumnRole) -> dict[str, Any]:
    return {
        "key": role.key,
        "label": role.label,
        "description": role.description,
        "required": role.required,
        "aliases": list(role.aliases),
    }


def serialize_dataset_plugin(spec: DatasetPluginSpec) -> dict[str, Any]:
    return {
        "slug": spec.slug,
        "name": spec.name,
        "description": spec.description,
        "supports_public": spec.supports_public,
        "column_roles": [serialize_dataset_plugin_role(role) for role in spec.column_roles],
    }
