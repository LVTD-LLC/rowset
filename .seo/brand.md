# Rowset - Brand Context for SEO

> Read every time. This file is read by every phase of the SEO sprint.

## Product

- **Name:** Rowset
- **One-liner (<=20 words):** Private MCP and REST datasets for trusted AI agents.
- **What we do:** Rowset gives AI agents a stable backend for user-owned structured rows. Users sign in, copy a setup prompt, authorize a scoped bearer API key, and let trusted agents create, inspect, update, export, and optionally share datasets through MCP or REST.
- **Pricing structure:** Free plan plus Rowset Pro at $50/month.
- **Free tier?** Yes - free accounts can create up to 2 datasets with up to 50 rows each. Pro unlocks unlimited hosted datasets and rows.

## Audience

- **Primary persona:** builders and operators delegating structured data work to trusted AI agents.
- **Secondary personas:** developers, founders, analysts, internal-tool builders, solo operators, and small teams.
- **Industries we target:** SaaS, agencies, operations, content teams, product/support, ecommerce, QA.
- **Company size we target:** solo builders through small teams first; larger teams later when permissions/audit depth expands.
- **Jobs to be done (top 3):**
  1. Give an AI agent a private place to create and maintain structured rows.
  2. Expose datasets through MCP and REST without building a custom backend.
  3. Share read-only previews or exports when humans need to review the data.

## Competitors

| Brand | Slug | URL | Tier | Notes |
|---|---|---|---|---|
| Airtable | airtable | https://airtable.com/ | head | Broad spreadsheet/database app with API, automations, collaboration, and templates. Strong brand; not agent-native by default. |
| Google Sheets | google-sheets | https://www.google.com/sheets/about/ | head | Default lightweight spreadsheet. Huge awareness; API available, but agent setup/auth/row semantics are not the product focus. |
| Baserow | baserow | https://baserow.io/ | mid | Open-source Airtable alternative with self-hosting, no-code database UI, and API-first positioning. |
| NocoDB | nocodb | https://nocodb.com/ | mid | Open-source no-code database over SQL backends; often considered alongside Airtable and Baserow. |
| Grist | grist | https://www.getgrist.com/ | niche | Spreadsheet-database hybrid with formulas and document-style workflows. |
| Supabase | supabase | https://supabase.com/ | head-adjacent | Developer Postgres backend; stronger for full apps than quick agent-managed row stores. |
| Retool Database | retool-database | https://retool.com/products/database | niche | Internal-tool database attached to Retool apps and workflows. |

## Brand voice

- **Voice tags:** direct, technical, calm, honest, concrete, agent-native.
- **Person/perspective:** team/we when explaining product decisions; you-focused for user outcomes.
- **Forbidden words/phrases:** revolutionary, seamless, synergy, unlock the power, spreadsheet replacement, no-code platform, AI magic.
- **Reference brands for tone:** Linear docs, Stripe docs, Buttondown's plainspoken product copy.

## Anti-positioning

1. Rowset is not a public spreadsheet host by default.
2. Rowset is not trying to replace Airtable's full no-code app builder.
3. Rowset is not a BI dashboard, warehouse, or ETL orchestration suite.
4. Rowset does not own Google Sheets/source sync; agents can read sources themselves and send rows to Rowset.
5. Rowset does not make public previews a substitute for private REST or MCP authentication.
6. Rowset does not promote browser automation as the preferred agent path.

## Concrete differentiators

1. Hosted MCP is a first-class interface, not an afterthought.
2. The setup prompt, skills, REST docs, and MCP discovery are designed for trusted AI agents.
3. Datasets carry explicit headers, index columns, semantic metadata, instructions, and JSON metadata for agent context.
4. Private-by-default ownership boundaries are central; public previews are optional and read-only.

## Visual brand

- **Accent color (primary):** `oklch(58% 0.16 158)` / emerald
- **Accent color (secondary):** cyan and amber are used sparingly for interface examples.
- **Ink color:** `oklch(18% 0.025 250)`
- **Surface color:** white / very light neutral surfaces.
- **Hero font family:** Inter, ui-sans-serif, system-ui, sans-serif.
- **Body font family:** Inter, ui-sans-serif, system-ui, sans-serif.
- **Icon set:** no dedicated icon library in marketing templates; keep visual language text/table/API driven.

## Links to existing surfaces

- Homepage: https://rowset.lvtd.dev/
- Pricing: https://rowset.lvtd.dev/pricing
- Use cases: https://rowset.lvtd.dev/use-cases
- Docs: https://rowset.lvtd.dev/docs/getting-started/introduction/
- Blog: https://rowset.lvtd.dev/blog/
- Public skill: https://rowset.lvtd.dev/SKILL.md
