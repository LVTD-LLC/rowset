import bleach
import markdown as md
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

register = template.Library()
ALLOWED_MARKDOWN_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "dd",
    "dl",
    "dt",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_MARKDOWN_ATTRIBUTES = {
    "a": ["href", "title"],
    "td": ["align"],
    "th": ["align"],
}
ALLOWED_MARKDOWN_PROTOCOLS = {"http", "https", "mailto"}


@register.filter
@stringfilter
def markdown(value):
    md_instance = md.Markdown(extensions=["tables"])

    html = md_instance.convert(value)
    html = bleach.clean(
        html,
        tags=ALLOWED_MARKDOWN_TAGS,
        attributes=ALLOWED_MARKDOWN_ATTRIBUTES,
        protocols=ALLOWED_MARKDOWN_PROTOCOLS,
        strip=True,
    )

    return mark_safe(html)


@register.filter
@stringfilter
def replace_quotes(value):
    return value.replace('"', "'")
