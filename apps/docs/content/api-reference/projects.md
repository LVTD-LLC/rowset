---
title: Project API
description: Create Rowset projects and assign datasets to semantic groups.
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
  "description": "Datasets used for launch operations"
}
```

The response includes `project.key`. Use that key when creating a dataset or
assigning an existing dataset.

## List projects

```http
GET {{ api_base_url }}/projects
```

Returns project metadata and `dataset_count`.

## Get a project

```http
GET {{ api_base_url }}/projects/{project_key}
```

Returns the project plus a page of datasets currently assigned to it.

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
