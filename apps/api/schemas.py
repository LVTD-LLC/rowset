from datetime import datetime

from ninja import Schema

from apps.blog.choices import BlogPostStatus


class SubmitFeedbackIn(Schema):
    feedback: str
    page: str


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
    is_staff: bool
    is_superuser: bool
    profile: UserProfileOut


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
    rows: list[DatasetRowOut]


class DatasetApiOut(Schema):
    status: str
    message: str
    row: DatasetRowOut | None = None
