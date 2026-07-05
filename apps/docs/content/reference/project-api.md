---
title: Project API
description: Create, update, and archive Rowset projects and sections, then assign datasets to semantic groups.
keywords: Rowset projects, project sections, dataset projects, project API
---

# Project API

Projects group datasets by topic, client, workflow, or any other label that helps
agents and users find the right table. A dataset can belong to one project, or no
project. Inside a project, optional sections group related datasets for a goal
such as Blog, Sales, or Support.

Projects do not replace authentication. REST and MCP access still uses the
authenticated profile boundary.

## Create a project

```http
POST {{ api_base_url }}/projects
Content-Type: application/json
```

```json
{
  "name": "Launch",
  "description": "Datasets used for launch operations",
  "metadata": {
    "github_repo": "https://github.com/acme/launch",
    "source_thread": "https://acme.slack.com/archives/C123/p456"
  }
}
```

The response includes `project.key`. Use that key when creating a dataset or
assigning an existing dataset.

## List projects

```http
GET {{ api_base_url }}/projects
```

Returns project description, JSON metadata, and `dataset_count`.

Search projects by name, description, or JSON metadata with `query`:

```http
GET {{ api_base_url }}/projects?query=launch
```

## Get a project

```http
GET {{ api_base_url }}/projects/{project_key}
```

Returns the project, active sections, grouped datasets, and a flat page of
datasets currently assigned to it.

## Update a project

```http
PATCH {{ api_base_url }}/projects/{project_key}
Content-Type: application/json
```

```json
{
  "name": "Launch operations",
  "description": "Datasets used by the launch agent"
}
```

Send only the fields you want to change. Use an empty string to clear
`description`.

## Update project metadata

```http
PATCH {{ api_base_url }}/projects/{project_key}/metadata
Content-Type: application/json
```

```json
{
  "metadata": {
    "notion_doc": "https://notion.so/acme/launch-plan",
    "slack_thread": "https://acme.slack.com/archives/C123/p456"
  }
}
```

Send an empty object to clear project metadata.

## Create a section

```http
POST {{ api_base_url }}/projects/{project_key}/sections
Content-Type: application/json
```

```json
{
  "name": "Blog",
  "description": "Content operations datasets",
  "metadata": {
    "goal": "content-led growth"
  }
}
```

The response includes `section.key`. Use that key with `project_key` when
creating or moving datasets into the section.

## List sections

```http
GET {{ api_base_url }}/projects/{project_key}/sections
```

Returns active sections for one project with `dataset_count`.

## Update a section

```http
PATCH {{ api_base_url }}/projects/{project_key}/sections/{section_key}
Content-Type: application/json
```

```json
{
  "name": "Editorial",
  "description": "Blog planning and publishing datasets"
}
```

## Archive a section

```http
DELETE {{ api_base_url }}/projects/{project_key}/sections/{section_key}
```

Archiving a section does not delete datasets. Datasets stay in the parent project
and become unsectioned.

## Archive a project

```http
DELETE {{ api_base_url }}/projects/{project_key}
```

Archives a project so it no longer appears in normal project lists, search
results, or project detail lookups. Archiving a project does not delete or
archive its datasets; dataset responses treat the archived project as ungrouped.

## Assign a dataset

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/project
Content-Type: application/json
```

```json
{
  "project_key": "{project_key}"
}
```

Attach a dataset to a section inside the project:

```json
{
  "project_key": "{project_key}",
  "section_key": "{section_key}"
}
```

To leave the dataset ungrouped, send:

```json
{
  "project_key": null
}
```

## Related docs

- [Dataset API](/docs/reference/dataset-api/)
- [How Rowset datasets work](/docs/explanation/datasets/)
- [MCP tool reference](/docs/reference/mcp-tools/)
