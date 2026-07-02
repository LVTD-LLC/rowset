from typing import Protocol, cast

from apps.core.models import AgentApiKey
from apps.datasets.models import Dataset, DatasetMutation


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class DatasetManager(Protocol):
    def get(self, **filters: object) -> Dataset: ...


class DatasetMutationManager(Protocol):
    def create(self, **fields: object) -> DatasetMutation: ...


class DatasetRowIdentity(Protocol):
    id: int


class DatasetPublicPreviewFields(Protocol):
    public_password_hash: str
    public_enabled: bool
    public_page_size: int
    status: str
    updated_by_agent_api_key: AgentApiKey | None
    is_public_password_protected: bool


class DatasetVectorSearchFields(Protocol):
    id: int
    profile_id: int
    key: object
    name: str
    status: str
    archived_at: object | None
    headers: list[str]
    column_schema: dict[str, dict[str, object]]
    index_column: str


class DatasetRowVectorSearchFields(Protocol):
    id: int
    row_number: int
    index_value: str
    data: dict[str, object] | None


DatasetDoesNotExist = cast(type[Exception], _django_attr(Dataset, "DoesNotExist"))


def dataset_objects() -> DatasetManager:
    return cast(DatasetManager, _django_attr(Dataset, "objects"))


def dataset_mutation_objects() -> DatasetMutationManager:
    return cast(DatasetMutationManager, _django_attr(DatasetMutation, "objects"))


def dataset_row_id(row: object) -> int:
    return cast(DatasetRowIdentity, row).id


def dataset_public_preview_fields(dataset: Dataset) -> DatasetPublicPreviewFields:
    return cast(DatasetPublicPreviewFields, dataset)


def dataset_vector_search_fields(dataset: Dataset) -> DatasetVectorSearchFields:
    return cast(DatasetVectorSearchFields, dataset)


def dataset_row_vector_search_fields(row: object) -> DatasetRowVectorSearchFields:
    return cast(DatasetRowVectorSearchFields, row)
