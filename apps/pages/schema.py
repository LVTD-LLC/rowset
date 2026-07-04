from __future__ import annotations

import json
from collections.abc import Sequence

from django.templatetags.static import static
from django.urls import reverse

from rowset.utils import build_absolute_public_url

ROWSET_NAME = "Rowset"
ROWSET_DESCRIPTION = "Private MCP and REST datasets for trusted AI agents."
ROWSET_AUTHOR = "Rasul Kireev"


def json_ld(payload: dict | list[dict]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def public_url(path: str) -> str:
    return build_absolute_public_url(path)


def logo_url() -> str:
    return public_url(static("vendors/images/logo.png"))


def organization_schema() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": ROWSET_NAME,
        "url": public_url("/"),
        "logo": {"@type": "ImageObject", "url": logo_url()},
        "founder": {"@type": "Person", "name": ROWSET_AUTHOR},
    }


def software_application_schema() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": ROWSET_NAME,
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "Web",
        "description": ROWSET_DESCRIPTION,
        "url": public_url("/"),
        "author": {"@type": "Person", "name": ROWSET_AUTHOR},
        "publisher": {"@type": "Organization", "name": ROWSET_NAME},
        "offers": [
            {
                "@type": "Offer",
                "name": "Rowset Free",
                "price": "0",
                "priceCurrency": "USD",
            },
            {
                "@type": "Offer",
                "name": "Rowset Pro",
                "price": "50",
                "priceCurrency": "USD",
            },
        ],
    }


def breadcrumb_list_schema(items: Sequence[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": name,
                "item": public_url(path),
            }
            for index, (name, path) in enumerate(items, start=1)
        ],
    }


def faq_page_schema(faqs: Sequence[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
            for question, answer in faqs
        ],
    }


def article_schema(
    *,
    headline: str,
    description: str,
    path: str,
    date_published: str | None = None,
    date_modified: str | None = None,
    article_body: str | None = None,
) -> dict:
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "url": public_url(path),
        "author": {"@type": "Person", "name": ROWSET_AUTHOR},
        "publisher": {
            "@type": "Organization",
            "name": ROWSET_NAME,
            "logo": {"@type": "ImageObject", "url": logo_url()},
        },
    }
    if date_published:
        schema["datePublished"] = date_published
    if date_modified:
        schema["dateModified"] = date_modified
    if article_body:
        schema["articleBody"] = article_body
    return schema


def use_case_article_schema(use_case: dict) -> dict:
    return article_schema(
        headline=f"{use_case['title']} - Rowset use case",
        description=use_case["meta_description"],
        path=reverse("use_case_detail", kwargs={"slug": use_case["slug"]}),
    )
