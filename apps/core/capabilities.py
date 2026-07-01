from dataclasses import dataclass
from typing import Any

CAPABILITY_VERSION = "2026-07-01"


@dataclass(frozen=True)
class RowsetCapability:
    id: str
    title: str
    summary: str
    mcp_tools: tuple[str, ...]
    rest_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "mcp_tools": list(self.mcp_tools),
            "rest_paths": list(self.rest_paths),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RowsetUseCase:
    id: str
    title: str
    summary: str
    starter_shape: tuple[str, ...]
    rowset_features: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "starter_shape": list(self.starter_shape),
            "rowset_features": list(self.rowset_features),
        }


ROWSET_RECOMMENDED_STARTUP = (
    "Read the setup prompt and store the full Rowset API key privately.",
    "Configure the Rowset MCP server with Authorization: Bearer <ROWSET_API_KEY>.",
    "Discover live MCP tools and schemas from the connected server.",
    "Call get_user_info to verify authentication.",
    "Call get_rowset_capabilities for the current Rowset workflow guide.",
    "Call get_all_datasets, get_archived_datasets, or search_datasets before creating duplicates.",
    (
        "Call get_dataset before row operations so dataset context, schema, and "
        "relationships are in context."
    ),
)

ROWSET_CAPABILITIES = (
    RowsetCapability(
        id="account_and_setup",
        title="Account and MCP setup",
        summary=(
            "Verify the authenticated Rowset profile and use the live MCP server as the "
            "source of truth for exact tool names, schemas, and descriptions."
        ),
        mcp_tools=("get_user_info", "get_rowset_capabilities"),
        rest_paths=("/api/user", "/api/agent-api-keys"),
        notes=(
            "Hosted MCP uses Authorization: Bearer <ROWSET_API_KEY>.",
            "The API key must stay in a private environment variable or secret store.",
            (
                "Read keys inspect data, Read + write keys can mutate datasets and "
                "projects, and Admin keys can create other agent API keys."
            ),
        ),
    ),
    RowsetCapability(
        id="api_key_management",
        title="API key management",
        summary=(
            "Create scoped agent API keys for trusted automation. Admin keys can "
            "provision read, read_write, or admin keys through MCP or REST."
        ),
        mcp_tools=("create_agent_api_key",),
        rest_paths=("/api/agent-api-keys",),
        notes=(
            "The raw key is returned only in the creation response.",
            "Use the smallest permission level that fits the agent's job.",
        ),
    ),
    RowsetCapability(
        id="datasets",
        title="Datasets",
        summary=(
            "Create, search, and inspect API-backed datasets with stable headers, an "
            "index column, row counts, public preview state, and machine-readable metadata."
        ),
        mcp_tools=(
            "get_all_datasets",
            "get_archived_datasets",
            "search_datasets",
            "get_dataset",
            "create_dataset",
        ),
        rest_paths=("/api/datasets", "/api/datasets/archived"),
        notes=(
            (
                "If no reliable business key exists, omit index_column and Rowset "
                "generates rowset_id."
            ),
            (
                "Use get_dataset before row work so the agent sees headers, "
                "index_column, and column_schema."
            ),
        ),
    ),
    RowsetCapability(
        id="dataset_context",
        title="Dataset context and semantic schema",
        summary=(
            "Persist descriptions, operating instructions, JSON metadata, semantic column "
            "types, choice values, and column descriptions for future agent runs."
        ),
        mcp_tools=(
            "get_dataset",
            "update_dataset_metadata",
            "update_dataset_column_types",
        ),
        rest_paths=(
            "/api/datasets/{dataset_key}/metadata",
            "/api/datasets/{dataset_key}/column-types",
        ),
        notes=(
            (
                "column_schema supports text, choice, integer, number, currency, "
                "boolean, date, datetime, email, url, image, and reference."
            ),
            (
                'Use {"type": "reference", "target": "dataset"} when a column stores '
                "another Rowset dataset key. Archived dataset targets remain valid."
            ),
            (
                'Use {"type": "reference", "target": "project"} when a column stores '
                "a Rowset project key. Archived project targets remain valid."
            ),
            (
                "Add column descriptions when an agent should not infer column "
                "meaning from the header alone."
            ),
        ),
    ),
    RowsetCapability(
        id="schema_mutations",
        title="Schema mutations",
        summary=(
            "Evolve ready datasets in place by adding, renaming, dropping, or reordering "
            "columns without recreating the table."
        ),
        mcp_tools=("add_column", "rename_column", "drop_column", "reorder_columns"),
        rest_paths=(
            "/api/datasets/{dataset_key}/columns",
            "/api/datasets/{dataset_key}/columns/rename",
            "/api/datasets/{dataset_key}/columns/drop",
            "/api/datasets/{dataset_key}/columns/reorder",
        ),
        notes=(
            "Index columns cannot be dropped.",
            "Columns used by relationships must be unlinked before destructive schema changes.",
        ),
    ),
    RowsetCapability(
        id="relationships",
        title="Dataset relationships",
        summary=(
            "Define simple foreign-key-style links when a source dataset column stores "
            "another dataset row's index value."
        ),
        mcp_tools=(
            "list_dataset_relationships",
            "create_dataset_relationship",
            "resolve_dataset_relationship",
            "delete_dataset_relationship",
        ),
        rest_paths=(
            "/api/datasets/{dataset_key}/relationships",
            "/api/datasets/{dataset_key}/relationships/{relationship_key}/resolve",
        ),
        notes=(
            "Relationships point to another ready dataset in the same account.",
            (
                "With enforcement enabled, non-blank source values must match "
                "target row indexes on row writes."
            ),
            "Blank relationship values are allowed.",
        ),
    ),
    RowsetCapability(
        id="projects",
        title="Projects",
        summary=(
            "Group related datasets into semantic projects, optionally organize them "
            "into sections inside a project, store project-level JSON metadata, and "
            "archive projects that should disappear from normal project discovery."
        ),
        mcp_tools=(
            "get_all_projects",
            "search_projects",
            "create_project",
            "get_project_sections",
            "create_project_section",
            "get_project",
            "update_project",
            "update_project_metadata",
            "update_project_section",
            "archive_project_section",
            "archive_project",
            "update_dataset_project",
        ),
        rest_paths=(
            "/api/projects",
            "/api/projects/{project_key}",
            "/api/projects/{project_key}/metadata",
            "/api/projects/{project_key}/sections",
            "/api/projects/{project_key}/sections/{section_key}",
            "/api/datasets/{dataset_key}/project",
        ),
        notes=(
            "Projects organize data; they do not change authentication boundaries.",
            "Sections organize datasets inside a project; they do not change access boundaries.",
            "Archiving a project does not delete or archive its datasets.",
            "Archiving a section leaves datasets in the parent project as unsectioned.",
        ),
    ),
    RowsetCapability(
        id="rows",
        title="Rows",
        summary=(
            "Read, search, filter, sort, create, patch, and delete rows within ready "
            "datasets while respecting the dataset index column."
        ),
        mcp_tools=(
            "list_dataset_rows",
            "get_dataset_row",
            "get_dataset_row_by_index",
            "create_dataset_row",
            "update_dataset_row",
            "update_dataset_row_by_index",
            "delete_dataset_row",
        ),
        rest_paths=(
            "/api/datasets/{dataset_key}/rows",
            "/api/datasets/{dataset_key}/rows/by-index",
            "/api/datasets/{dataset_key}/rows/{row_id}",
        ),
        notes=(
            "Use by-index tools when the workflow has a stable business key.",
            "Ask the user before deleting rows unless the user explicitly requested deletion.",
        ),
    ),
    RowsetCapability(
        id="image_assets",
        title="Image assets",
        summary=(
            "Attach private JPEG, PNG, or WebP files to image columns after the target "
            "dataset row exists. Rowset stores an opaque asset reference in the row cell "
            "and returns metadata plus authenticated content URLs."
        ),
        mcp_tools=("attach_image_to_dataset_row", "get_dataset_image_asset"),
        rest_paths=(
            "/api/datasets/{dataset_key}/rows/{row_id}/image",
            "/api/datasets/{dataset_key}/rows/by-index/image",
            "/api/datasets/{dataset_key}/assets/{asset_key}",
            "/api/datasets/{dataset_key}/assets/{asset_key}/content",
        ),
        notes=(
            "Create image columns with type image and leave image cells blank during row writes.",
            (
                "For MCP, read local image bytes yourself and pass base64 or a data URI; "
                "hosted MCP cannot read local file paths."
            ),
            (
                "Use row_id or the dataset index_value to attach the image, then keep "
                "the returned asset:{key} cell value as Rowset-managed metadata."
            ),
            (
                "Rowset normalizes image bytes before storage; byte_size and checksum "
                "describe the stored asset, not necessarily the original local file."
            ),
            (
                "The thumbnail URL is a display URL. It returns a generated thumbnail "
                "when one is smaller, otherwise it falls back to the stored original image."
            ),
            "Use update_dataset_public_preview only when the user asks for a browser share link.",
        ),
    ),
    RowsetCapability(
        id="public_previews",
        title="Public previews",
        summary=(
            "Enable, disable, password-protect, or resize read-only browser previews "
            "for humans who need a link instead of authenticated API access."
        ),
        mcp_tools=("update_dataset_public_preview",),
        rest_paths=("/api/datasets/{dataset_key}/public-preview",),
        notes=(
            "Public previews are not authentication and do not replace private MCP or REST access.",
            "Only enable public preview when the user asks to share a browser-readable table.",
        ),
    ),
    RowsetCapability(
        id="archive_restore_and_exports",
        title="Archive, restore, and export",
        summary=(
            "Archive mistaken datasets without deleting rows, restore archived datasets, "
            "and use REST export endpoints when a file snapshot is required."
        ),
        mcp_tools=("get_archived_datasets", "archive_dataset", "restore_dataset"),
        rest_paths=(
            "/api/datasets/archived",
            "/api/datasets/{dataset_key}",
            "/api/datasets/{dataset_key}/restore",
            "/api/datasets/{dataset_key}/export.csv",
            "/api/datasets/{dataset_key}/export.jsonl",
            "/api/datasets/{dataset_key}/export.xlsx",
            "/api/datasets/{dataset_key}/export.sqlite",
        ),
        notes=(
            "Archive keeps rows and schema metadata recoverable.",
            "Exports are REST fallback paths; prefer MCP row tools for live agent workflows.",
        ),
    ),
)

ROWSET_USE_CASES = (
    RowsetUseCase(
        id="personal_crm",
        title="Personal CRM",
        summary=(
            "Track people, companies, conversations, follow-ups, and relationship context "
            "without forcing the user into a spreadsheet UI."
        ),
        starter_shape=(
            "People dataset indexed by email or person_id.",
            "Companies dataset indexed by company_id.",
            "Messages or interactions dataset with person_id relationship to People.",
        ),
        rowset_features=("relationships", "dataset_context", "rows", "projects"),
    ),
    RowsetUseCase(
        id="task_board",
        title="Agent task board",
        summary=(
            "Give agents a durable task list with explicit status, owner, priority, and "
            "blocked-state conventions."
        ),
        starter_shape=(
            "Tasks dataset indexed by task_id.",
            "Choice column for status such as todo, blocked, doing, done.",
            "Dataset instructions defining when agents may move or close tasks.",
        ),
        rowset_features=("dataset_context", "schema_mutations", "rows", "projects"),
    ),
    RowsetUseCase(
        id="feedback_triage",
        title="Feedback triage",
        summary=(
            "Collect customer feedback, classify it, link it to customers or accounts, "
            "and keep follow-up state queryable."
        ),
        starter_shape=(
            "Feedback dataset indexed by feedback_id.",
            "Customers dataset indexed by customer_id or email.",
            "Relationship from Feedback.customer_id to Customers.",
        ),
        rowset_features=("relationships", "dataset_context", "rows", "public_previews"),
    ),
    RowsetUseCase(
        id="content_pipeline",
        title="Content pipeline",
        summary=(
            "Track articles, landing pages, newsletters, or social posts from idea "
            "through review and publication."
        ),
        starter_shape=(
            "Content items dataset indexed by slug.",
            "Choice column for stage such as idea, draft, review, published.",
            "Project metadata linking to source docs, repository, or editorial calendar.",
        ),
        rowset_features=(
            "projects",
            "dataset_context",
            "schema_mutations",
            "archive_restore_and_exports",
        ),
    ),
    RowsetUseCase(
        id="catalog",
        title="Product or inventory catalog",
        summary=(
            "Maintain structured product records, prices, supplier fields, and public "
            "read-only snapshots when a teammate needs a browser link."
        ),
        starter_shape=(
            "Products dataset indexed by sku.",
            "Image column for product photos, plus currency and URL semantic columns.",
            "Optional public preview for read-only sharing.",
        ),
        rowset_features=(
            "dataset_context",
            "rows",
            "image_assets",
            "public_previews",
            "archive_restore_and_exports",
        ),
    ),
    RowsetUseCase(
        id="bug_tracker",
        title="Bug or QA tracker",
        summary=(
            "Track issues, severity, affected releases, repro notes, and customer impact "
            "with agent-friendly lookup and updates."
        ),
        starter_shape=(
            "Issues dataset indexed by issue_id.",
            "Choice columns for status and severity.",
            "Optional relationships to Customers, Releases, or Components datasets.",
        ),
        rowset_features=("relationships", "dataset_context", "rows", "projects"),
    ),
)

ROWSET_GUARDRAILS = (
    "Keep private authenticated dataset access as the default.",
    "Do not expose API keys, OAuth tokens, raw secrets, or private row data in public outputs.",
    (
        "Ask before destructive actions such as deleting rows, archiving datasets, "
        "or clearing preview passwords."
    ),
    "Use public previews only for read-only browser sharing.",
    (
        "Do not claim dashboard upload wizards, Rowset-owned Google Sheets sync, "
        "or spreadsheet write-back are active product paths."
    ),
)


def _validate_capability_registry() -> None:
    capability_ids = [capability.id for capability in ROWSET_CAPABILITIES]
    duplicate_ids = sorted(
        capability_id
        for capability_id in set(capability_ids)
        if capability_ids.count(capability_id) > 1
    )
    if duplicate_ids:
        raise ValueError("ROWSET_CAPABILITIES contains duplicate IDs: " + ", ".join(duplicate_ids))

    valid_capability_ids = set(capability_ids)
    unknown_references = []
    for use_case in ROWSET_USE_CASES:
        missing_ids = sorted(set(use_case.rowset_features) - valid_capability_ids)
        if missing_ids:
            unknown_references.append(f"{use_case.id}: {', '.join(missing_ids)}")

    if unknown_references:
        raise ValueError(
            "ROWSET_USE_CASES references unknown capability IDs: " + "; ".join(unknown_references)
        )


def rowset_capabilities_payload() -> dict[str, Any]:
    _validate_capability_registry()
    return {
        "product": "Rowset",
        "capability_version": CAPABILITY_VERSION,
        "summary": (
            "Rowset gives trusted AI agents a private MCP and REST backend for "
            "user-owned structured datasets."
        ),
        "source_of_truth": (
            "Use MCP tools/list for exact current schemas. Use this guide for workflow "
            "semantics, feature groups, and recommended startup order."
        ),
        "recommended_startup": list(ROWSET_RECOMMENDED_STARTUP),
        "capabilities": [capability.as_dict() for capability in ROWSET_CAPABILITIES],
        "use_cases": [use_case.as_dict() for use_case in ROWSET_USE_CASES],
        "guardrails": list(ROWSET_GUARDRAILS),
    }


def render_rowset_llms_txt(
    *,
    site_url: str,
    mcp_url: str,
    rest_api_base_url: str,
    api_docs_url: str,
    setup_skill_url: str,
    features_skill_url: str,
    use_cases_skill_url: str,
) -> str:
    _validate_capability_registry()
    lines = [
        "# Rowset",
        "",
        (
            "> Rowset gives trusted AI agents a private MCP and REST backend for "
            "user-owned structured datasets."
        ),
        "",
        f"Capability version: {CAPABILITY_VERSION}",
        "",
        "## Important URLs",
        "",
        f"- Site: {site_url}",
        f"- MCP endpoint: {mcp_url}",
        f"- REST API base: {rest_api_base_url}",
        f"- Generated API docs: {api_docs_url}",
        f"- Setup skill: {setup_skill_url}",
        f"- Feature reference skill: {features_skill_url}",
        f"- Use-case guide skill: {use_cases_skill_url}",
        "",
        "## Recommended agent startup",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(ROWSET_RECOMMENDED_STARTUP, 1))
    lines.extend(
        [
            "",
            "## Current capabilities",
            "",
        ]
    )
    for capability in ROWSET_CAPABILITIES:
        lines.extend(
            [
                f"### {capability.title}",
                "",
                capability.summary,
                "",
                f"- MCP tools: {', '.join(capability.mcp_tools)}",
            ]
        )
        if capability.rest_paths:
            lines.append(f"- REST paths: {', '.join(capability.rest_paths)}")
        for note in capability.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend(
        [
            "## Use-case guides",
            "",
        ]
    )
    for use_case in ROWSET_USE_CASES:
        lines.extend(
            [
                f"### {use_case.title}",
                "",
                use_case.summary,
                "",
                "Starter shape:",
            ]
        )
        lines.extend(f"- {item}" for item in use_case.starter_shape)
        lines.append(f"- Relevant Rowset features: {', '.join(use_case.rowset_features)}")
        lines.append("")

    lines.extend(
        [
            "## Guardrails",
            "",
        ]
    )
    lines.extend(f"- {guardrail}" for guardrail in ROWSET_GUARDRAILS)
    lines.extend(
        [
            "",
            "## Notes for agents",
            "",
            "- Prefer MCP tools over browser automation.",
            "- Treat MCP tools/list as the exact tool schema source.",
            (
                "- Use REST only when MCP cannot perform the requested action or "
                "a file export is needed."
            ),
            (
                "- Never print or store raw Rowset API keys in tracked files, "
                "logs, screenshots, public chats, or final responses."
            ),
            "",
        ]
    )
    return "\n".join(lines)
