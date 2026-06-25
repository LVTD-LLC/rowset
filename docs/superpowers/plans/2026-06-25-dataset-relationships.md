# Dataset Relationships Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simple first-class way for Rowset users and agents to define, validate, discover, and resolve relationships between datasets.

**Architecture:** Store relationship definitions as owned Django records between a source dataset column and a target dataset index. Keep business rules in `apps/api/services.py`, then expose thin REST, MCP, and UI surfaces that reuse those services.

**Tech Stack:** Django 6, Django Ninja, FastMCP, PostgreSQL, Django templates, pytest through `make test`.

---

### Task 1: Model and Migration

**Files:**
- Modify: `apps/datasets/models.py`
- Modify: `apps/datasets/choices.py`
- Generate: `apps/datasets/migrations/*.py`

- [ ] Add `DatasetRelationship` with profile ownership, source dataset, source column, target dataset, target index column, relationship name, enforcement flag, timestamps, and uniqueness constraints.
- [ ] Add a relationship mutation type for audit history.
- [ ] Run `make makemigrations`.

### Task 2: Service Layer

**Files:**
- Modify: `apps/api/services.py`
- Test: `apps/datasets/tests/test_csv_datasets.py`

- [ ] Add serializers and service functions to create, list, delete, and resolve relationships.
- [ ] Validate same-profile ownership, ready target datasets, existing source columns, target index column, duplicate relationship names, and relationship values on row create/update when enforcement is enabled.
- [ ] Keep blank source values allowed so optional relationships remain possible.

### Task 3: REST API

**Files:**
- Modify: `apps/api/schemas.py`
- Modify: `apps/api/views.py`
- Test: `apps/datasets/tests/test_csv_datasets.py`

- [ ] Add schemas and endpoints for dataset relationships.
- [ ] Use shared service functions and return clear HTTP errors.

### Task 4: MCP Tools

**Files:**
- Modify: `apps/mcp_server/server.py`
- Test: `apps/mcp_server/tests/test_server.py`

- [ ] Add MCP tools for create/list/delete/resolve relationship actions.
- [ ] Keep tool bodies thin and delegate to the service layer.

### Task 5: UI and Docs

**Files:**
- Modify: `apps/datasets/views.py`
- Modify: `frontend/templates/datasets/detail.html`
- Modify: `frontend/templates/datasets/settings.html`
- Modify: `apps/docs/content/features/datasets.md`
- Modify: `apps/docs/content/api-reference/datasets.md`
- Modify: `apps/docs/content/features/mcp.md`

- [ ] Show relationship definitions on dataset detail/settings pages.
- [ ] Document the Personal CRM pattern and the REST/MCP surfaces.

### Task 6: Verification

**Commands:**
- `make test apps/datasets/tests/test_csv_datasets.py -k relationship`
- `make test apps/mcp_server/tests/test_server.py -k relationship`
- `make test apps/datasets/tests/test_csv_datasets.py apps/mcp_server/tests/test_server.py`

- [ ] Run focused relationship tests first.
- [ ] Run the broader touched test files before final summary.
