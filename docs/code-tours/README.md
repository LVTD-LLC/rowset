# Rowset Code Tours

Use these tours before changing a Rowset flow. Each tour names the files to read,
the commands to run, and the mistakes agents commonly make in that area.

## Tours

- [Dataset Lifecycle And Agent Surfaces](dataset-lifecycle.md) - dataset
  creation/import, row mutation, REST/MCP flow, vector search, agent access, and
  public previews.
- [API Service Kernel Extraction Map](service-kernel-map.md) - service domains,
  caller surfaces, extraction order, required checks, and no-go areas before
  refactoring `apps/api/services.py`.
- [Deployment And Startup Flow](deployment-startup.md) - container builds,
  entrypoints, health checks, worker startup, production imports, and startup
  smoke checks.
- [Dataset Asset Storage Flow](asset-storage.md) - private image asset storage,
  cleanup retry rows, public preview asset URLs, and storage test boundaries.

## How To Use A Tour

1. Read the relevant section before editing.
2. Inspect the listed files in the order shown.
3. Run the smallest command listed for the touched area.
4. Use [agent task templates](../agent-task-templates.md) to frame the work and
   verification evidence.
