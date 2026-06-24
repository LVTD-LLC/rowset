---
title: Project API
description: Create and update Rowset projects, then assign datasets to semantic groups.
keywords: Rowset projects, dataset projects, project API
---

# Project API

Projects group datasets by topic, client, workflow, or any other label that helps
agents and users find the right table. A dataset can belong to one project, or no
project.

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

Returns the project plus a page of datasets currently assigned to it.

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

To leave the dataset ungrouped, send:

```json
{
  "project_key": null
}
```
