from datetime import datetime

from ninja import Schema
from pydantic import Field

from apps.api.services import MAX_API_DATASET_CREATE_ROWS
from apps.core.choices import AgentApiKeyAccessLevel
from apps.datasets.constants import (
    MAX_DATASET_DESCRIPTION_LENGTH,
    MAX_DATASET_INSTRUCTIONS_LENGTH,
)
from apps.datasets.types import (
    ColumnSchema,
    ColumnTypeSpec,
    DatasetRowInput,
    JsonObject,
)

ColumnTypeIn = ColumnTypeSpec
COLUMN_TYPE_DESCRIPTION = (
    "Semantic column type string or metadata object. Metadata supports type, "
    "description, image columns, choice columns with choices, reference columns with "
    'target "dataset" or "project", and calculated relationship_count columns with '
    "relationship_key."
)


class SubmitFeedbackIn(Schema):
    feedback: str = Field(..., min_length=1, max_length=2000)
    page: str = Field("", max_length=255)
    context: JsonObject | None = None


class SubmitFeedbackOut(Schema):
    success: bool
    message: str
    row_url: str = ""


class FeedbackRecordOut(Schema):
    uuid: str
    source: str
    created_at: str


class AgentFeedbackSubmitOut(Schema):
    status: str
    message: str
    feedback: FeedbackRecordOut
    dataset: str = ""
    row: int | None = None
    row_url: str = ""


class ProfileSettingsOut(Schema):
    has_pro_subscription: bool


class UserSettingsOut(Schema):
    profile: ProfileSettingsOut


class UserProfileOut(Schema):
    id: int
    state: str
    has_active_subscription: bool


class UserInfoOut(Schema):
    id: int
    email: str
    username: str
    first_name: str
    last_name: str
    full_name: str
    date_joined: datetime
    profile: UserProfileOut


class AgentApiKeyCreateIn(Schema):
    name: str = Field(..., min_length=1, max_length=80)
    access_level: str = AgentApiKeyAccessLevel.READ_WRITE


class AgentApiKeyOut(Schema):
    uuid: str
    name: str
    key_prefix: str
    access_level: str
    access_level_label: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class AgentApiKeyCreateOut(Schema):
    status: str
    message: str
    agent_api_key: AgentApiKeyOut
    api_key: str


class ProjectReferenceOut(Schema):
    key: str
    name: str
    description: str


class ProjectSummaryOut(ProjectReferenceOut):
    metadata: JsonObject
    dataset_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ProjectSectionReferenceOut(Schema):
    key: str
    name: str
    description: str


class ProjectSectionSummaryOut(ProjectSectionReferenceOut):
    project: ProjectReferenceOut | None = None
    metadata: JsonObject
    dataset_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ProjectSectionListOut(Schema):
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    sections: list[ProjectSectionSummaryOut]


class ProjectSectionCreateIn(Schema):
    name: str
    description: str | None = None
    metadata: JsonObject | None = None


class ProjectSectionUpdateIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ProjectSectionCreateOut(Schema):
    status: str
    message: str
    section: ProjectSectionSummaryOut


class ProjectSectionUpdateOut(Schema):
    status: str
    message: str
    section: ProjectSectionSummaryOut


class ProjectSectionArchiveOut(Schema):
    status: str
    message: str
    section: ProjectSectionSummaryOut


class ProjectListOut(Schema):
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    projects: list[ProjectSummaryOut]


class ProjectCreateIn(Schema):
    name: str
    description: str | None = None
    metadata: JsonObject | None = None


class ProjectUpdateIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ProjectCreateOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class ProjectUpdateOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class ProjectArchiveOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class ProjectMetadataPatchIn(Schema):
    metadata: JsonObject


class ProjectMetadataOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class DatasetSummaryOut(Schema):
    key: str
    name: str
    description: str
    instructions: str
    metadata: JsonObject
    project: ProjectReferenceOut | None = None
    section: ProjectSectionReferenceOut | None = None
    headers: list[str]
    column_schema: ColumnSchema
    index_column: str
    index_generated: bool
    row_count: int
    public_enabled: bool
    public_key: str
    public_url: str | None = None
    public_page_size: int
    public_password_protected: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class DatasetListOut(Schema):
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    datasets: list[DatasetSummaryOut]


class DatasetGroupItemsOut(Schema):
    count: int
    total_count: int
    datasets: list[DatasetSummaryOut]


class ProjectDatasetGroupOut(Schema):
    label: str
    section: ProjectSectionReferenceOut | None = None
    dataset_count: int
    datasets: DatasetGroupItemsOut


class ProjectDetailOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut
    sections: list[ProjectSectionSummaryOut]
    dataset_groups: list[ProjectDatasetGroupOut]
    datasets: DatasetListOut


class DatasetCreateIn(Schema):
    name: str
    description: str | None = Field(default=None, max_length=MAX_DATASET_DESCRIPTION_LENGTH)
    instructions: str | None = Field(default=None, max_length=MAX_DATASET_INSTRUCTIONS_LENGTH)
    metadata: JsonObject | None = None
    headers: list[str] | None = None
    rows: list[DatasetRowInput] = Field(
        default_factory=list,
        max_length=MAX_API_DATASET_CREATE_ROWS,
    )
    index_column: str | None = None
    column_types: dict[str, ColumnTypeIn] | None = Field(
        default=None,
        description=COLUMN_TYPE_DESCRIPTION,
    )
    project_key: str | None = None
    section_key: str | None = None


class DatasetCreateOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetColumnTypesPatchIn(Schema):
    column_types: dict[str, ColumnTypeIn] = Field(
        ...,
        description=COLUMN_TYPE_DESCRIPTION,
    )


class DatasetColumnTypesOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetMetadataPatchIn(Schema):
    description: str | None = Field(default=None, max_length=MAX_DATASET_DESCRIPTION_LENGTH)
    instructions: str | None = Field(default=None, max_length=MAX_DATASET_INSTRUCTIONS_LENGTH)
    metadata: JsonObject | None = None


class DatasetMetadataOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetColumnAddIn(Schema):
    name: str
    default_value: object = ""
    column_type: ColumnTypeIn | None = Field(
        default=None,
        description=COLUMN_TYPE_DESCRIPTION,
    )


class DatasetColumnRenameIn(Schema):
    old_name: str
    new_name: str


class DatasetColumnDropIn(Schema):
    name: str


class DatasetColumnReorderIn(Schema):
    headers: list[str]


class DatasetColumnMutationOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetPublicPreviewPatchIn(Schema):
    public_enabled: bool | None = None
    public_page_size: int | None = Field(default=None, ge=1, le=100)
    public_password: str | None = None
    clear_public_password: bool = False


class DatasetPublicPreviewOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetProjectPatchIn(Schema):
    project_key: str | None = None
    section_key: str | None = None


class DatasetProjectOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetRelationshipDatasetOut(Schema):
    key: str
    name: str
    index_column: str


class DatasetRelationshipOut(Schema):
    key: str
    name: str
    source_dataset: DatasetRelationshipDatasetOut
    source_column: str
    target_dataset: DatasetRelationshipDatasetOut
    target_index_column: str
    enforce_integrity: bool
    created_at: datetime
    updated_at: datetime


class DatasetRelationshipCreateIn(Schema):
    source_column: str
    target_dataset_key: str
    name: str | None = None
    enforce_integrity: bool = True


class DatasetRelationshipCreateOut(Schema):
    status: str
    message: str
    relationship: DatasetRelationshipOut


class DatasetRelationshipListOut(Schema):
    dataset: str
    relationships: list[DatasetRelationshipOut]


class DatasetRelationshipContextOut(Schema):
    outgoing: list[DatasetRelationshipOut]
    incoming: list[DatasetRelationshipOut]


class DatasetDetailOut(DatasetSummaryOut):
    relationships: DatasetRelationshipContextOut
    dataset_references: dict[str, dict[str, JsonObject]]
    project_references: dict[str, dict[str, JsonObject]]


class DatasetRelationshipDeleteOut(Schema):
    status: str
    message: str
    relationship: DatasetRelationshipOut


class DatasetArchiveOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetRowIn(Schema):
    data: DatasetRowInput


class DatasetRowPatchIn(Schema):
    data: DatasetRowInput


class DatasetAssetOut(Schema):
    key: str
    ref: str
    dataset: str
    row_id: int
    row_number: int
    index_value: str
    column: str
    original_filename: str
    content_type: str
    byte_size: int
    width: int | None = None
    height: int | None = None
    checksum: str
    status: str
    has_thumbnail: bool
    content_url: str
    thumbnail_url: str
    content_url_auth_required: bool
    public_enabled: bool
    public_password_protected: bool
    public_content_url: str | None = None
    public_thumbnail_url: str | None = None
    created_at: datetime
    updated_at: datetime


class DatasetRowOut(Schema):
    id: int
    row_number: int
    index_value: str
    data: dict[str, str]
    assets: list[DatasetAssetOut] = Field(default_factory=list)


class DatasetImageAttachIn(Schema):
    column_name: str = Field(..., min_length=1)
    image_base64: str = Field(
        ...,
        min_length=1,
        description=(
            "JPEG, PNG, or WebP image bytes encoded as base64. For a local file, "
            "read the file bytes in the agent environment and pass the base64 string; "
            "hosted Rowset MCP cannot read local file paths."
        ),
    )
    filename: str | None = None
    content_type: str | None = None


class DatasetImageAttachOut(Schema):
    status: str
    message: str
    dataset: str
    row: DatasetRowOut
    asset: DatasetAssetOut


class DatasetAssetApiOut(Schema):
    status: str
    message: str
    asset: DatasetAssetOut


class DatasetRowsOut(Schema):
    dataset: str
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    query: str
    filters: dict[str, str] = Field(default_factory=dict)
    sort: str
    direction: str
    rows: list[DatasetRowOut]


class DatasetSearchIn(Schema):
    query: str = Field(..., min_length=1, max_length=1000)
    filters: dict[str, object] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class DatasetSearchResultOut(Schema):
    rank: int
    score: float
    row: DatasetRowOut
    match: dict[str, object]


class DatasetSearchOut(Schema):
    dataset: str
    query: str
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int
    count: int
    results: list[DatasetSearchResultOut]


class ProfileRowSearchIn(Schema):
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language or keyword search text.",
    )
    filters: dict[str, object] | None = Field(
        default=None,
        description="Optional row field filters. Datasets missing these headers are excluded.",
    )
    filter_operators: dict[str, object] | None = Field(
        default=None,
        description=(
            "Optional row filter operators keyed by header, such as contains, is, above, or below."
        ),
    )
    dataset_key: str | None = Field(
        default=None,
        description="Optional dataset key/public key/URL.",
    )
    project_key: str | None = Field(
        default=None,
        description="Optional project key to restrict searched datasets.",
    )
    section_key: str | None = Field(
        default=None,
        description="Optional project section key to restrict searched datasets.",
    )
    archived: bool | None = Field(
        default=False,
        description=(
            "False searches active datasets, true searches archived datasets, null searches both."
        ),
    )
    sort: str | None = Field(default="rank", description="rank, dataset, or row_number.")
    direction: str | None = Field(
        default=None,
        description="asc or desc. Defaults to desc when sort is rank, asc otherwise.",
    )
    limit: int = Field(default=10, ge=1, le=50)


class ProfileRowSearchDatasetOut(Schema):
    key: str
    name: str
    project: ProjectReferenceOut | None = None
    section: ProjectSectionReferenceOut | None = None
    headers: list[str]
    index_column: str
    row_count: int
    public_enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None


class ProfileRowSearchResultOut(Schema):
    rank: int
    score: float
    dataset: ProfileRowSearchDatasetOut
    row: DatasetRowOut
    match: dict[str, object]


class ProfileRowSearchOut(Schema):
    query: str
    filters: dict[str, str] = Field(default_factory=dict)
    filter_operators: dict[str, str] = Field(default_factory=dict)
    dataset_filters: dict[str, object] = Field(default_factory=dict)
    sort: str
    direction: str
    limit: int
    count: int
    results: list[ProfileRowSearchResultOut]


class DatasetApiOut(Schema):
    status: str
    message: str
    dataset: str | None = None
    row: DatasetRowOut | None = None


class DatasetRelationshipResolveOut(Schema):
    status: str
    message: str
    relationship: DatasetRelationshipOut
    source_row: DatasetRowOut
    target_index_value: str
    target_row: DatasetRowOut | None = None
