from dataclasses import dataclass
from typing import Any

CAPABILITY_VERSION = "2026-07-17"


class CapabilitySelectionError(ValueError):
    """Raised when a caller requests an invalid capability payload selection."""


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


@dataclass(frozen=True)
class RowsetCapabilityTopic:
    id: str
    title: str
    capability_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "capability_ids": list(self.capability_ids),
        }


ROWSET_RECOMMENDED_STARTUP = (
    "Read the setup prompt and store the full Rowset API key privately.",
    (
        "Inspect the current Rowset skill, llms.txt, capabilities response, and relevant "
        "interface documentation before choosing a setup path."
    ),
    (
        "Evaluate MCP, CLI, and REST against the current runtime and user workflow; explain "
        "a recommendation and ask the user which interface to configure."
    ),
    "Configure only the interface the user approves, following its current documentation.",
    (
        "As the final setup step, make an authenticated user-info request through the chosen "
        "interface to verify access, complete onboarding, and start the trial."
    ),
    (
        "Report the verified connection, inspect existing Rowset structure read-only, and "
        "suggest two to four project, section, and dataset structures based on context the "
        "agent already has about the user's work. Ask before creating anything."
    ),
    (
        "When the agent runtime supports scheduled tasks, separately offer an opt-in daily "
        "Rowset tips automation. Create it only after explicit agreement and ground tips in "
        "current Rowset resources."
    ),
)

ROWSET_INTERFACES = (
    {
        "id": "mcp",
        "best_for": "Agent runtimes with remote MCP support and live tool/schema discovery.",
        "current_reference": (
            "After authenticated verification, inspect live tools and call get_rowset_capabilities."
        ),
        "authenticated_verification": "Call get_user_info.",
    },
    {
        "id": "cli",
        "best_for": "Terminal workflows, scripts, and local file handling.",
        "current_reference": "Run rowset --help and rowset capabilities.",
        "authenticated_verification": "Run rowset user info.",
    },
    {
        "id": "rest",
        "best_for": "Applications and runtimes that work naturally with HTTP.",
        "current_reference": "Read the capabilities endpoint and generated API docs.",
        "authenticated_verification": "Request GET /api/user with bearer authentication.",
    },
)

ROWSET_CAPABILITIES = (
    RowsetCapability(
        id="account_and_setup",
        title="Account access and interface discovery",
        summary=(
            "Connect through MCP, CLI, or REST; use live capabilities and interface "
            "documentation as the source of truth; and verify the authenticated profile."
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
        id="product_feedback",
        title="Product feedback",
        summary=(
            "Submit concise Rowset product feedback from an authenticated agent when MCP, "
            "REST, setup, docs, or workflow behavior is confusing or missing."
        ),
        mcp_tools=("submit_feedback",),
        rest_paths=("/api/feedback",),
        notes=(
            "Read-level agent API keys may submit feedback.",
            "Do not include API keys, secrets, or private dataset contents in feedback.",
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
        rest_paths=("/api/datasets", "/api/datasets/{dataset_key}", "/api/datasets/archived"),
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
                "column_schema supports text, tags, choice, integer, number, currency, "
                "boolean, date, datetime, email, url, image, audio, reference, and calculated."
            ),
            (
                'Use {"type": "calculated", "calculation": "relationship_count", '
                '"relationship_key": "..."} on the target dataset to count source rows '
                "from an incoming relationship."
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
            "Evolve active datasets in place by adding, renaming, dropping, or reordering "
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
            "Relationships point to another active dataset in the same account.",
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
            "Read, search, filter, sort, create, patch, and delete rows across ready "
            "datasets or within one dataset while respecting the dataset index column."
        ),
        mcp_tools=(
            "search_rows",
            "list_dataset_rows",
            "search_dataset_rows",
            "get_dataset_row",
            "get_dataset_row_by_index",
            "create_dataset_row",
            "update_dataset_row",
            "update_dataset_row_by_index",
            "delete_dataset_row",
        ),
        rest_paths=(
            "/api/search",
            "/api/datasets/{dataset_key}/rows",
            "/api/datasets/{dataset_key}/search",
            "/api/datasets/{dataset_key}/rows/by-index",
            "/api/datasets/{dataset_key}/rows/{row_id}",
        ),
        notes=(
            "Use by-index tools when the workflow has a stable business key.",
            "Use search_rows or /api/search when the relevant dataset is unknown or "
            "multiple datasets matter.",
            "Use search_dataset_rows for ranked hybrid search within one known dataset.",
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
        id="audio_assets",
        title="Audio assets",
        summary=(
            "Attach private MP3, WAV, M4A, AAC, Ogg, FLAC, or WebM files to audio "
            "columns after the target dataset row exists. Rowset stores an opaque "
            "asset reference in the row cell and returns metadata plus authenticated "
            "content URLs."
        ),
        mcp_tools=("attach_audio_to_dataset_row", "get_dataset_audio_asset"),
        rest_paths=(
            "/api/datasets/{dataset_key}/rows/{row_id}/audio",
            "/api/datasets/{dataset_key}/rows/by-index/audio",
            "/api/datasets/{dataset_key}/assets/{asset_key}",
            "/api/datasets/{dataset_key}/assets/{asset_key}/content",
        ),
        notes=(
            "Create audio columns with type audio and leave audio cells blank during row writes.",
            (
                "For MCP, read local audio bytes yourself and pass base64 or a data URI; "
                "hosted MCP cannot read local file paths."
            ),
            (
                "Use row_id or the dataset index_value to attach the audio, then keep "
                "the returned asset:{key} cell value as Rowset-managed metadata."
            ),
            "Rowset stores audio bytes privately without transcoding.",
            "Use update_dataset_public_preview only when the user asks for a browser share link.",
        ),
    ),
    RowsetCapability(
        id="public_previews",
        title="Public previews",
        summary=(
            "Enable, disable, password-protect, or resize read-only public datasets "
            "for browser review and dedicated public JSON reads."
        ),
        mcp_tools=("update_dataset_public_preview",),
        rest_paths=(
            "/api/datasets/{dataset_key}/public-preview",
            "/api/public/datasets/{public_key}",
            "/api/public/datasets/{public_key}/rows",
        ),
        notes=(
            "Public datasets do not replace authenticated MCP or REST for private reads or writes.",
            (
                "Unprotected public datasets need no credential; password-protected public API "
                "requests require X-Rowset-Public-Password on every request."
            ),
            "Only enable public access when the user asks to share a read-only dataset.",
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
            "Use the current CLI or REST documentation when a file snapshot is required.",
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
    "Use public datasets only for deliberate read-only browser or JSON sharing.",
    (
        "Do not claim dashboard upload wizards, Rowset-owned Google Sheets sync, "
        "or spreadsheet write-back are active product paths."
    ),
)

ROWSET_CAPABILITY_TOPICS = (
    RowsetCapabilityTopic(
        id="setup",
        title="Account access, setup, API keys, and feedback",
        capability_ids=("account_and_setup", "api_key_management", "product_feedback"),
    ),
    RowsetCapabilityTopic(
        id="datasets",
        title="Dataset discovery and creation",
        capability_ids=("datasets",),
    ),
    RowsetCapabilityTopic(
        id="schema",
        title="Dataset context and schema changes",
        capability_ids=("dataset_context", "schema_mutations"),
    ),
    RowsetCapabilityTopic(
        id="rows",
        title="Row reads, search, writes, and deletion",
        capability_ids=("rows",),
    ),
    RowsetCapabilityTopic(
        id="relationships",
        title="Relationships between datasets",
        capability_ids=("relationships",),
    ),
    RowsetCapabilityTopic(
        id="projects",
        title="Projects and sections",
        capability_ids=("projects",),
    ),
    RowsetCapabilityTopic(
        id="assets",
        title="Image and audio assets",
        capability_ids=("image_assets", "audio_assets"),
    ),
    RowsetCapabilityTopic(
        id="previews",
        title="Public read-only previews",
        capability_ids=("public_previews",),
    ),
    RowsetCapabilityTopic(
        id="archive_exports",
        title="Archive, restore, and exports",
        capability_ids=("archive_restore_and_exports",),
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

    topic_capability_ids = {
        capability_id
        for topic in ROWSET_CAPABILITY_TOPICS
        for capability_id in topic.capability_ids
    }
    if topic_capability_ids != valid_capability_ids:
        missing_ids = sorted(valid_capability_ids - topic_capability_ids)
        unknown_ids = sorted(topic_capability_ids - valid_capability_ids)
        raise ValueError(
            "ROWSET_CAPABILITY_TOPICS must cover the capability registry exactly; "
            f"missing={missing_ids}, unknown={unknown_ids}"
        )


def _visible_rowset_capabilities() -> tuple[RowsetCapability, ...]:
    return ROWSET_CAPABILITIES


def _visible_rowset_use_cases(
    capabilities: tuple[RowsetCapability, ...],
) -> tuple[RowsetUseCase, ...]:
    visible_capability_ids = {capability.id for capability in capabilities}
    return tuple(
        use_case
        for use_case in ROWSET_USE_CASES
        if set(use_case.rowset_features) <= visible_capability_ids
    )


def public_rowset_capabilities() -> tuple[RowsetCapability, ...]:
    return _visible_rowset_capabilities()


def public_rowset_use_cases() -> tuple[RowsetUseCase, ...]:
    return _visible_rowset_use_cases(public_rowset_capabilities())


def _normalize_topics(topics: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    normalized_topics = tuple(
        dict.fromkeys(topic.strip().lower() for topic in topics or () if topic.strip())
    )
    known_topics = {topic.id for topic in ROWSET_CAPABILITY_TOPICS}
    unknown_topics = sorted(set(normalized_topics) - known_topics)
    if unknown_topics:
        label = "topic" if len(unknown_topics) == 1 else "topics"
        raise CapabilitySelectionError(
            f"Unknown capability {label}: {', '.join(unknown_topics)}. "
            f"Available topics: {', '.join(sorted(known_topics))}."
        )
    return normalized_topics


def _capabilities_for_topics(topics: tuple[str, ...]) -> tuple[RowsetCapability, ...]:
    selected_ids = {
        capability_id
        for topic in ROWSET_CAPABILITY_TOPICS
        if topic.id in topics
        for capability_id in topic.capability_ids
    }
    return tuple(
        capability for capability in _visible_rowset_capabilities() if capability.id in selected_ids
    )


def rowset_capabilities_payload(
    *,
    topics: list[str] | tuple[str, ...] | None = None,
    include_use_cases: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    _validate_capability_registry()
    normalized_topics = _normalize_topics(topics)
    if full and normalized_topics:
        raise CapabilitySelectionError("Choose topics or full mode, not both.")

    if full:
        mode = "full"
    elif normalized_topics:
        mode = "topics"
    else:
        mode = "summary"

    payload: dict[str, Any] = {
        "product": "Rowset",
        "capability_version": CAPABILITY_VERSION,
        "summary": (
            "Rowset gives trusted AI agents private MCP, CLI, and REST access to "
            "user-owned structured datasets."
        ),
        "mode": mode,
    }

    if not full and not normalized_topics:
        payload.update(
            {
                "usage": (
                    "Request one or more available topic IDs for details. Set full=true for "
                    "the complete guide, and include_use_cases=true only when examples help."
                ),
                "available_topics": [topic.as_dict() for topic in ROWSET_CAPABILITY_TOPICS],
                "guardrails": list(ROWSET_GUARDRAILS),
            }
        )
        if include_use_cases:
            payload["use_cases"] = [use_case.as_dict() for use_case in ROWSET_USE_CASES]
        return payload

    visible_capabilities = (
        _visible_rowset_capabilities() if full else _capabilities_for_topics(normalized_topics)
    )
    payload.update(
        {
            "source_of_truth": (
                "Use this live guide for current feature groups and workflow semantics, then "
                "consult MCP tool schemas, CLI help, or generated REST API docs for the exact "
                "interface selected by the user."
            ),
            "capabilities": [capability.as_dict() for capability in visible_capabilities],
            "guardrails": list(ROWSET_GUARDRAILS),
        }
    )
    if normalized_topics:
        payload["requested_topics"] = list(normalized_topics)
    if full or "setup" in normalized_topics:
        payload["interfaces"] = list(ROWSET_INTERFACES)
        payload["recommended_startup"] = list(ROWSET_RECOMMENDED_STARTUP)
    if include_use_cases:
        use_cases = _visible_rowset_use_cases(visible_capabilities)
        payload["use_cases"] = [use_case.as_dict() for use_case in use_cases]
    return payload
