# Blog Posts

Published blog posts live in `apps/blog/posts` as Markdown files. Every
`*.md` file in that directory is public on deploy at `/blog/{filename-slug}`.

Required frontmatter:

```yaml
---
title: Agent-managed dataset workflows
description: A concise search snippet for the article.
published_at: 2026-07-03
---
```

Optional frontmatter:

```yaml
updated_at: 2026-07-03
author: Rasul Kireev
keywords:
  - Rowset
  - MCP
topics:
  - agent workflows
canonical_url: https://rowset.com/blog/agent-managed-dataset-workflows
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
```

Use lowercase filename slugs such as `agent-managed-datasets.md`. There is no
draft status or database sync path; keep unfinished posts outside this folder.
