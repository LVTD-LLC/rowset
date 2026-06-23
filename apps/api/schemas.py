from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import Field

from apps.api.services import MAX_API_DATASET_CREATE_ROWS
from apps.blog.choices import BlogPostStatus


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


class ProjectReferenceOut(Schema):
    key: str
    name: str
    description: str


class ProjectSummaryOut(ProjectReferenceOut):
    dataset_count: int
    created_at: datetime
    updated_at: datetime


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


class ProjectCreateOut(Schema):
    status: str
    message: str
    project: ProjectSummaryOut


class DatasetSummaryOut(Schema):
    key: str
    name: str
    project: ProjectReferenceOut | None = None
    original_filename: str
    file_type: str
    status: str
    headers: list[str]
    column_schema: dict[str, dict[str, str]]
    index_column: str
    index_generated: bool
    row_count: int
    public_enabled: bool
    public_key: str
    public_url: str
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
    headers: list[str] | None = None
    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=MAX_API_DATASET_CREATE_ROWS,
    )
    index_column: str | None = None
    column_types: dict[str, str] | None = None
    project_key: str | None = None


class DatasetCreateOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetColumnTypesPatchIn(Schema):
    column_types: dict[str, str]


class DatasetColumnTypesOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetColumnAddIn(Schema):
    name: str
    default_value: Any = ""
    column_type: str | None = None


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


class DatasetArchiveOut(Schema):
    status: str
    message: str
    dataset: DatasetSummaryOut


class DatasetRowIn(Schema):
    data: dict[str, str]


class DatasetRowPatchIn(Schema):
    data: dict[str, str]


class DatasetRowOut(Schema):
    id: int
    row_number: int
    index_value: str
    data: dict[str, str]


class DatasetRowsOut(Schema):
    dataset: str
    count: int
    limit: int
    offset: int
    has_more: bool
    rows: list[DatasetRowOut]


class DatasetApiOut(Schema):
    status: str
    message: str
    row: DatasetRowOut | None = None
