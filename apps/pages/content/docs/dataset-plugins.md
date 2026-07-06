---
title: Use dataset plugins
description: Install trusted Rowset dataset plugins, enable them per dataset, and map plugin roles to existing columns.
keywords: Rowset dataset plugins, Flashcards plugin, plugin marketplace
---

# Use dataset plugins

Dataset plugins add richer human-facing views or workflows on top of dataset
rows. Rows stay the source of truth. The plugin only changes how a human reviews
or works with those rows.

## Install a plugin

Signed-in users can open the plugin marketplace from the app navigation. A
plugin must be installed for the account before it can be enabled on a dataset.

MCP and REST only list plugins installed for the authenticated account.

```text
get_available_dataset_plugins
```

REST:

```http
GET {{ api_base_url }}/dataset-plugins
```

## Enable a plugin on a dataset

Plugins are enabled per dataset. Column-based plugins use config to map plugin
roles to existing dataset headers.

MCP:

```text
enable_dataset_plugin
```

REST:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/plugins/{plugin_slug}
Content-Type: application/json
```

```json
{
  "config": {
    "columns": {
      "front_question": "question",
      "back_answer": "answer"
    }
  }
}
```

## Flashcards

The built-in Flashcards plugin renders dataset rows as study cards. Required
roles:

- `front_question`
- `back_answer`

Optional roles:

- `front_title`
- `front_image`
- `back_title`
- `back_image`
- `tags`

Use image columns for front or back images. Use a stable `card_id` index column
when the agent will update cards over time.

## Disable a plugin

Disabling a plugin removes the plugin view from that dataset. It does not delete
rows, schema, or assets.

```text
disable_dataset_plugin
```

REST:

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/plugins/{plugin_slug}
```
