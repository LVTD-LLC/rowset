from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from apps.core.capabilities import (
    ROWSET_CAPABILITIES,
    ROWSET_USE_CASES,
    public_rowset_capabilities,
    public_rowset_use_cases,
)

PUBLIC_SLUG_PATTERN = re.compile(r"^[-a-zA-Z0-9_]+$")


@dataclass(frozen=True)
class UseCasePageCopy:
    slug: str
    eyebrow: str
    hero_title: str
    meta_description: str
    short_summary: str
    example_name: str
    index_column: str
    sample_rows: tuple[tuple[str, str, str], ...]
    agent_actions: tuple[str, ...]
    workflow_steps: tuple[tuple[str, str], ...]


USE_CASE_PAGE_COPY: dict[str, UseCasePageCopy] = {
    "personal_crm": UseCasePageCopy(
        slug="personal-crm",
        eyebrow="Agent CRM",
        hero_title="A CRM your agent can actually maintain.",
        meta_description=(
            "Use Rowset as an agent-managed personal CRM for people, companies, "
            "conversations, follow-ups, and relationship context."
        ),
        short_summary=(
            "Keep relationship data in private rows so an agent can remember who "
            "matters, what happened, and what comes next."
        ),
        example_name="people",
        index_column="email",
        sample_rows=(
            ("alex@example.com", "follow up", "Asked for pricing notes"),
            ("sam@studio.dev", "warm", "Intro from May conference"),
            ("nora@acme.com", "waiting", "Send recap after demo"),
        ),
        agent_actions=(
            "Add people and companies from meeting notes.",
            "Update relationship stage after each conversation.",
            "Find stale promises before they become dropped balls.",
        ),
        workflow_steps=(
            ("Capture", "The agent turns conversations into structured rows."),
            ("Recall", "It searches by person, company, stage, or next action."),
            ("Act", "It updates follow-ups and exports a snapshot when needed."),
        ),
    ),
    "task_board": UseCasePageCopy(
        slug="agent-task-board",
        eyebrow="Agent task board",
        hero_title="A task board built for delegated agent work.",
        meta_description=(
            "Use Rowset as an agent task board with durable status, owner, priority, "
            "blocked-state, and handoff rows."
        ),
        short_summary=(
            "Give agents a shared task ledger they can inspect and update without "
            "forcing the work into a fixed project-management app."
        ),
        example_name="agent_tasks",
        index_column="task_id",
        sample_rows=(
            ("TASK-104", "doing", "Draft onboarding copy"),
            ("TASK-118", "blocked", "Needs API key decision"),
            ("TASK-121", "todo", "Verify export flow"),
        ),
        agent_actions=(
            "Create tasks with clear ownership and status.",
            "Move work only when dataset instructions allow it.",
            "Surface blockers across long-running agent sessions.",
        ),
        workflow_steps=(
            ("Define", "The agent creates the columns your workflow needs."),
            ("Coordinate", "Each run reads the latest task state before acting."),
            ("Close", "Completed tasks stay searchable for review."),
        ),
    ),
    "feedback_triage": UseCasePageCopy(
        slug="feedback-triage",
        eyebrow="Feedback triage",
        hero_title="Turn scattered feedback into rows an agent can use.",
        meta_description=(
            "Use Rowset to collect, classify, dedupe, and follow up on customer "
            "feedback with private MCP and REST access."
        ),
        short_summary=(
            "Agents can collect requests, link them to customers, count signals, "
            "and publish read-only previews when humans need a board."
        ),
        example_name="feedback",
        index_column="feedback_id",
        sample_rows=(
            ("FB-203", "billing", "Needs annual invoice export"),
            ("FB-219", "mcp", "Wants team-scoped API keys"),
            ("FB-224", "import", "CSV cleanup request"),
        ),
        agent_actions=(
            "Dedupe related requests into a consistent theme.",
            "Attach customer and account context.",
            "Share a read-only preview without opening private row access.",
        ),
        workflow_steps=(
            ("Collect", "The agent writes each signal into a stable dataset."),
            ("Cluster", "It updates categories, status, and customer links."),
            ("Share", "Public previews stay optional and read-only."),
        ),
    ),
    "content_pipeline": UseCasePageCopy(
        slug="content-pipeline",
        eyebrow="Content pipeline",
        hero_title="A content pipeline agents can move without a CMS fight.",
        meta_description=(
            "Use Rowset to manage article, landing page, newsletter, and programmatic "
            "SEO workflows as agent-editable datasets."
        ),
        short_summary=(
            "Track briefs, drafts, review state, canonical URLs, and publish dates "
            "as rows that agents can update from their own tools."
        ),
        example_name="content_queue",
        index_column="slug",
        sample_rows=(
            ("mcp-dataset-api", "review", "Needs examples"),
            ("agent-crm-guide", "draft", "Outline approved"),
            ("feedback-board", "idea", "Use case page"),
        ),
        agent_actions=(
            "Create briefs from research and customer notes.",
            "Move items through review and publish stages.",
            "Export the queue for editors, scripts, or downstream systems.",
        ),
        workflow_steps=(
            ("Plan", "Rows hold the brief, owner, stage, and target URL."),
            ("Produce", "Agents update state as drafts move through review."),
            ("Publish", "Exports provide snapshots for handoff or audit."),
        ),
    ),
    "catalog": UseCasePageCopy(
        slug="product-inventory-catalog",
        eyebrow="Product catalog",
        hero_title="A lightweight catalog your agent can keep current.",
        meta_description=(
            "Use Rowset for product or inventory catalogs with SKU rows, prices, "
            "supplier fields, links, exports, and read-only previews."
        ),
        short_summary=(
            "Store product records in private rows, then let agents update prices, "
            "supplier fields, links, and public snapshots."
        ),
        example_name="products",
        index_column="sku",
        sample_rows=(
            ("SKU-1042", "active", "$49"),
            ("SKU-1188", "review", "$129"),
            ("SKU-1405", "archived", "$24"),
        ),
        agent_actions=(
            "Update structured product fields from trusted sources.",
            "Keep URLs, prices, and notes in typed columns.",
            "Share read-only catalog views with teammates.",
        ),
        workflow_steps=(
            ("Structure", "The agent creates SKU-indexed product rows."),
            ("Maintain", "It updates fields as pricing or suppliers change."),
            ("Distribute", "Exports and previews cover human handoffs."),
        ),
    ),
    "bug_tracker": UseCasePageCopy(
        slug="bug-qa-tracker",
        eyebrow="Bug and QA tracker",
        hero_title="A bug tracker that fits agent-run QA.",
        meta_description=(
            "Use Rowset as an agent-friendly bug and QA tracker for issues, severity, "
            "repro notes, releases, fixes, and customer impact."
        ),
        short_summary=(
            "Keep issue state explicit so agents can file, update, inspect, and "
            "summarize bugs without scraping a browser UI."
        ),
        example_name="issues",
        index_column="issue_id",
        sample_rows=(
            ("ISS-442", "high", "Export timeout on large dataset"),
            ("ISS-451", "medium", "Preview password copy unclear"),
            ("ISS-463", "low", "Settings layout overflow"),
        ),
        agent_actions=(
            "Create issues with reproduction notes and affected version.",
            "Update severity, owner, release, and fix status.",
            "Link bugs to customers, releases, or components.",
        ),
        workflow_steps=(
            ("File", "Agents add structured issues from QA notes or logs."),
            ("Track", "Rows keep status, severity, and ownership visible."),
            ("Review", "Exports and previews support release triage."),
        ),
    ),
}


def _capability_titles() -> dict[str, str]:
    return {capability.id: capability.title for capability in public_rowset_capabilities()}


def _duplicate_capability_ids() -> tuple[str, ...]:
    capability_ids = [capability.id for capability in ROWSET_CAPABILITIES]
    return tuple(
        sorted(
            capability_id
            for capability_id in set(capability_ids)
            if capability_ids.count(capability_id) > 1
        )
    )


def _duplicate_public_slugs() -> set[str]:
    page_copy_slugs = []
    for use_case in public_rowset_use_cases():
        page_copy = USE_CASE_PAGE_COPY.get(use_case.id)
        if isinstance(page_copy, UseCasePageCopy) and isinstance(page_copy.slug, str):
            page_copy_slugs.append(page_copy.slug)

    return {slug for slug in page_copy_slugs if page_copy_slugs.count(slug) > 1}


def _invalid_public_slugs() -> tuple[str, ...]:
    invalid_slugs = []
    for use_case in public_rowset_use_cases():
        use_case_id = use_case.id
        page_copy = USE_CASE_PAGE_COPY.get(use_case_id)
        if not isinstance(page_copy, UseCasePageCopy):
            invalid_slugs.append(f"{use_case_id}: <invalid page copy>")
            continue

        if not isinstance(page_copy.slug, str) or not PUBLIC_SLUG_PATTERN.fullmatch(page_copy.slug):
            invalid_slugs.append(f"{use_case_id}: {page_copy.slug or '<empty>'}")

    return tuple(invalid_slugs)


def get_use_case_page_registry_errors() -> tuple[str, ...]:
    use_case_ids = {use_case.id for use_case in ROWSET_USE_CASES}
    public_use_case_ids = {use_case.id for use_case in public_rowset_use_cases()}
    page_copy_ids = set(USE_CASE_PAGE_COPY)
    duplicate_capability_ids = _duplicate_capability_ids()
    duplicate_slugs = sorted(_duplicate_public_slugs())
    invalid_slugs = _invalid_public_slugs()
    valid_feature_ids = {capability.id for capability in ROWSET_CAPABILITIES}
    missing_page_copy_ids = sorted(public_use_case_ids - page_copy_ids)
    stale_page_copy_ids = sorted(page_copy_ids - use_case_ids)
    unknown_feature_references = []

    for use_case in ROWSET_USE_CASES:
        missing_feature_ids = sorted(set(use_case.rowset_features) - valid_feature_ids)
        if missing_feature_ids:
            unknown_feature_references.append(f"{use_case.id}: {', '.join(missing_feature_ids)}")

    errors = []
    if missing_page_copy_ids:
        errors.append(
            "USE_CASE_PAGE_COPY is missing entries for ROWSET_USE_CASES: "
            + ", ".join(missing_page_copy_ids)
        )
    if stale_page_copy_ids:
        errors.append(
            "USE_CASE_PAGE_COPY contains entries without ROWSET_USE_CASES: "
            + ", ".join(stale_page_copy_ids)
        )
    if duplicate_capability_ids:
        errors.append(
            "ROWSET_CAPABILITIES contains duplicate IDs: " + ", ".join(duplicate_capability_ids)
        )
    if duplicate_slugs:
        errors.append(
            "USE_CASE_PAGE_COPY contains duplicate public slugs: " + ", ".join(duplicate_slugs)
        )
    if invalid_slugs:
        errors.append(
            "USE_CASE_PAGE_COPY contains invalid public slugs: " + ", ".join(invalid_slugs)
        )
    if unknown_feature_references:
        errors.append(
            "ROWSET_USE_CASES references unknown capability IDs: "
            + "; ".join(unknown_feature_references)
        )

    return tuple(errors)


def validate_use_case_page_registry() -> None:
    errors = get_use_case_page_registry_errors()
    if errors:
        raise ValueError("; ".join(errors))


def _ensure_use_case_page_registry_configured() -> None:
    try:
        validate_use_case_page_registry()
    except ValueError as exc:
        raise ImproperlyConfigured(str(exc)) from exc


def get_use_case_pages() -> tuple[dict[str, object], ...]:
    _ensure_use_case_page_registry_configured()
    feature_titles = _capability_titles()
    pages: list[dict[str, object]] = []

    for use_case in public_rowset_use_cases():
        page_copy = USE_CASE_PAGE_COPY.get(use_case.id)
        if page_copy is None:
            raise ImproperlyConfigured(
                f"USE_CASE_PAGE_COPY is missing entries for ROWSET_USE_CASES: {use_case.id}"
            )

        features = []
        for feature_id in use_case.rowset_features:
            feature_title = feature_titles.get(feature_id)
            if feature_title is None:
                raise ImproperlyConfigured(
                    "ROWSET_USE_CASES references unknown capability IDs: "
                    f"{use_case.id}: {feature_id}"
                )
            features.append(feature_title)

        pages.append(
            {
                "id": use_case.id,
                "slug": page_copy.slug,
                "title": use_case.title,
                "eyebrow": page_copy.eyebrow,
                "hero_title": page_copy.hero_title,
                "summary": use_case.summary,
                "short_summary": page_copy.short_summary,
                "meta_description": page_copy.meta_description,
                "starter_shape": use_case.starter_shape,
                "features": tuple(features),
                "example_name": page_copy.example_name,
                "index_column": page_copy.index_column,
                "sample_rows": page_copy.sample_rows,
                "agent_actions": page_copy.agent_actions,
                "workflow_steps": page_copy.workflow_steps,
            }
        )

    return tuple(pages)


def get_use_case_page(slug: str) -> dict[str, object] | None:
    return next((page for page in get_use_case_pages() if page["slug"] == slug), None)
