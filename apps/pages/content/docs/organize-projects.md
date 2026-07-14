---
title: Organize with projects
description: Group Rowset datasets into projects and sections without changing API or MCP access boundaries.
keywords: Rowset projects, project sections, dataset organization
---

# Organize with projects

Use projects when a Rowset account has multiple datasets for the same client,
campaign, workflow, agent, or research area. Use sections when a project needs a
small amount of internal grouping.

Projects are organization metadata. They do not grant, remove, or change API and
MCP access.

## When to create a project

Create a project when datasets are easier to find as a group:

- a launch with content, outreach, and bug datasets
- a client workspace
- a research project with sources, leads, and notes
- a personal operating system with tasks, contacts, and follow-ups

## Project metadata

Projects can carry JSON metadata for context that belongs to the group:

```json
{
  "github_repo": "https://github.com/acme/launch",
  "slack_thread": "https://acme.slack.com/archives/C123/p456",
  "owner": "growth"
}
```

Agents can read this through MCP or REST before deciding which dataset to use.

## Sections

Sections are optional groups inside a project. For example, a Launch project can
have:

- Blog
- Outreach
- Support
- QA

When a section is archived, datasets stay in the parent project as unsectioned.

## MCP tools

```text
get_all_projects
search_projects
create_project
get_project
get_project_sections
create_project_section
update_project
update_project_metadata
update_project_section
archive_project_section
archive_project
update_dataset_project
```

## REST endpoints

```http
GET /api/projects
POST /api/projects
GET /api/projects/{project_key}
PATCH /api/projects/{project_key}
PATCH /api/projects/{project_key}/metadata
GET /api/projects/{project_key}/sections
POST /api/projects/{project_key}/sections
PATCH /api/projects/{project_key}/sections/{section_key}
DELETE /api/projects/{project_key}/sections/{section_key}
DELETE /api/projects/{project_key}
PATCH /api/datasets/{dataset_key}/project
```

Use [Project API](/docs/project-api) for endpoint details.
