from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import Field

from apps.api.services import MAX_API_DATASET_CREATE_ROWS
from apps.blog.choices import BlogPostStatus
from apps.core.choices import AgentApiKeyAccessLevel
from apps.datasets.constants import (
    MAX_DATASET_DESCRIPTION_LENGTH,
    MAX_DATASET_INSTRUCTIONS_LENGTH,
)

ColumnTypeIn = str | dict[str, Any]
COLUMN_TYPE_DESCRIPTION = (
    "Semantic column type string or metadata object. Metadata supports type, "
    "description, image columns, choice columns with choices, and reference columns with "
    'target "dataset".'
)


class SubmitFeedbackIn(Schema):
    feedback: str = Field(..., min_length=1, max_length=2000)
    page: str = Field("", max_length=255)


class SubmitFeedbackOut(Schema):
    success: bool
    message: str


class BlogPostIn(Schema):
    title: str
    description: str = ""
    slug: str
    tags: str = ""
    content: str
    icon: str | None = None  # URL or base64 string
    image: str | None = None  # URL or base64 string
    status: BlogPostStatus = BlogPostStatus.DRAFT


class BlogPostUpdateIn(Schema):
    title: str | None = None
    description: str | None = None
    slug: str | None = None
    tags: str | None = None
    content: str | None = None
    status: BlogPostStatus | None = None


class BlogPostItemOut(Schema):
    id: int
    title: str
    description: str
    slug: str
    tags: str
    content: str
    status: BlogPostStatus


class BlogPostListOut(Schema):
    blog_posts: list[BlogPostItemOut]


class BlogPostOut(Schema):
    status: str  # API response status: 'success' or 'failure'
    message: str


class BlogPostDetailOut(Schema):
    status: str
    message: str
    blog_post: BlogPostItemOut | None = None


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
    metadata: dict[str, Any]
    dataset_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


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
    metadata: dict[str, Any] | None = None


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
    metadata: dict[str, Any]


class ProjectMetadataOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class DatasetSummaryOut(Schema):
    key: str
    name: str
    description: str
    instructions: str
    metadata: dict[str, Any]
    project: ProjectReferenceOut | None = None
    original_filename: str
    file_type: str
    status: str
    headers: list[str]
    column_schema: dict[str, dict[str, Any]]
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
    confirmed_at: datetime | None = None
    processed_at: datetime | None = None
    archived_at: datetime | None = None


class DatasetListOut(Schema):
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    datasets: list[DatasetSummaryOut]


class ProjectDetailOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut
    datasets: DatasetListOut


class DatasetCreateIn(Schema):
    name: str
    description: str | None = Field(default=None, max_length=MAX_DATASET_DESCRIPTION_LENGTH)
    instructions: str | None = Field(default=None, max_length=MAX_DATASET_INSTRUCTIONS_LENGTH)
    metadata: dict[str, Any] | None = None
    headers: list[str] | None = None
    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=MAX_API_DATASET_CREATE_ROWS,
    )
    index_column: str | None = None
    column_types: dict[str, ColumnTypeIn] | None = Field(
        default=None,
        description=COLUMN_TYPE_DESCRIPTION,
    )
    project_key: str | None = None


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
    metadata: dict[str, Any] | None = None


class DatasetMetadataOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetColumnAddIn(Schema):
    name: str
    default_value: Any = ""
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


class DatasetRelationshipDeleteOut(Schema):
    status: str
    message: str
    relationship: DatasetRelationshipOut


class DatasetArchiveOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetRowIn(Schema):
    data: dict[str, str]


class DatasetRowPatchIn(Schema):
    data: dict[str, str]


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
    thumbnail_url: str | None = None
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
