from ninja import Schema
from typing import Optional


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
    icon: Optional[str] = None  # URL or base64 string
    image: Optional[str] = None  # URL or base64 string
    status: BlogPostStatus = BlogPostStatus.DRAFT


class BlogPostUpdateIn(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None
    tags: Optional[str] = None
    content: Optional[str] = None
    status: Optional[BlogPostStatus] = None


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
    blog_post: Optional[BlogPostItemOut] = None



class ProfileSettingsOut(Schema):
    
    has_pro_subscription: bool
    


class UserSettingsOut(Schema):
    profile: ProfileSettingsOut
