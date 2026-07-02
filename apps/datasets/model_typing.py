from collections.abc import Iterator
from typing import Protocol, cast

from apps.core.models import AgentApiKey
from apps.datasets.models import Dataset, DatasetAsset, DatasetMutation, DatasetRow


def _django_attr(model: object, name: str) -> object:
    return getattr(model, name)


class DatasetManager(Protocol):
    def get(self, **filters: object) -> Dataset: ...


class DatasetMutationQuerySet(Protocol):
    def exists(self) -> bool: ...


class DatasetMutationManager(Protocol):
    def create(self, **fields: object) -> DatasetMutation: ...

    def filter(self, **filters: object) -> DatasetMutationQuerySet: ...


class DatasetRowNumberQuerySet(Protocol):
    def first(self) -> int | None: ...

    def iterator(self, *, chunk_size: int | None = None) -> Iterator[int]: ...


class DatasetRowQuerySet(Protocol):
    def __iter__(self) -> Iterator[DatasetRow]: ...

    def count(self) -> int: ...

    def delete(self) -> tuple[int, dict[str, int]]: ...

    def exclude(self, **filters: object) -> DatasetRowQuerySet: ...

    def exists(self) -> bool: ...

    def filter(self, **filters: object) -> DatasetRowQuerySet: ...

    def get(self, **filters: object) -> DatasetRow: ...

    def order_by(self, *fields: str) -> DatasetRowQuerySet: ...

    def prefetch_related(self, *lookups: str) -> DatasetRowQuerySet: ...

    def select_related(self, *fields: str) -> DatasetRowQuerySet: ...

    def values_list(self, *fields: str, flat: bool = False) -> DatasetRowNumberQuerySet: ...

    def all(self) -> DatasetRowQuerySet: ...


class DatasetRowManager(Protocol):
    def bulk_create(
        self,
        objs: list[DatasetRow],
        batch_size: int | None = None,
    ) -> list[DatasetRow]: ...

    def create(self, **fields: object) -> DatasetRow: ...

    def filter(self, **filters: object) -> DatasetRowQuerySet: ...

    def select_related(self, *fields: str) -> DatasetRowQuerySet: ...


class DatasetAssetQuerySet(Protocol):
    def delete(self) -> tuple[int, dict[str, int]]: ...


class DatasetAssetManager(Protocol):
    def filter(self, **filters: object) -> DatasetAssetQuerySet: ...


class DatasetRowIdentity(Protocol):
    id: int


class DatasetRowMutationDatasetFields(Protocol):
    id: int
    headers: list[str]
    column_schema: dict[str, object] | None
    index_column: str
    index_generated: bool
    row_count: int
    rows: DatasetRowQuerySet
    updated_by_agent_api_key: AgentApiKey | None


class DatasetImportTaskFields(Protocol):
    id: int
    key: object
    column_schema: dict[str, object] | None
    file_type: str
    headers: list[str]
    index_column: str
    index_generated: bool
    parse_error: str
    processed_at: object | None
    row_count: int
    rows: DatasetRowQuerySet
    source_file: object
    source_text: str
    status: str


class DatasetRowMutationFields(Protocol):
    id: int
    row_number: int
    index_value: str
    data: dict[str, str] | None
    updated_by_agent_api_key: AgentApiKey | None


class DatasetRowTaskFields(Protocol):
    dataset: Dataset
    dataset_id: int


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
DatasetRowDoesNotExist = cast(type[Exception], _django_attr(DatasetRow, "DoesNotExist"))


def dataset_objects() -> DatasetManager:
    return cast(DatasetManager, _django_attr(Dataset, "objects"))


def dataset_mutation_objects() -> DatasetMutationManager:
    return cast(DatasetMutationManager, _django_attr(DatasetMutation, "objects"))


def dataset_row_objects() -> DatasetRowManager:
    return cast(DatasetRowManager, _django_attr(DatasetRow, "objects"))


def dataset_asset_objects() -> DatasetAssetManager:
    return cast(DatasetAssetManager, _django_attr(DatasetAsset, "objects"))


def dataset_row_id(row: object) -> int:
    return cast(DatasetRowIdentity, row).id


def dataset_row_mutation_dataset_fields(dataset: Dataset) -> DatasetRowMutationDatasetFields:
    return cast(DatasetRowMutationDatasetFields, dataset)


def dataset_row_mutation_fields(row: DatasetRow) -> DatasetRowMutationFields:
    return cast(DatasetRowMutationFields, row)


def dataset_import_task_fields(dataset: Dataset) -> DatasetImportTaskFields:
    return cast(DatasetImportTaskFields, dataset)


def dataset_row_task_fields(row: DatasetRow) -> DatasetRowTaskFields:
    return cast(DatasetRowTaskFields, row)


def dataset_public_preview_fields(dataset: Dataset) -> DatasetPublicPreviewFields:
    return cast(DatasetPublicPreviewFields, dataset)


def dataset_vector_search_fields(dataset: Dataset) -> DatasetVectorSearchFields:
    return cast(DatasetVectorSearchFields, dataset)


def dataset_row_vector_search_fields(row: object) -> DatasetRowVectorSearchFields:
    return cast(DatasetRowVectorSearchFields, row)
