---
version: beta
name: Rowset
description: A clean product UI system for agent-managed API datasets.
colors:
  ink: "oklch(18% 0.025 250)"
  text: "oklch(27% 0.025 250)"
  text-muted: "oklch(46% 0.025 250)"
  background: "oklch(100% 0 0)"
  surface: "oklch(99% 0.004 250)"
  surface-muted: "oklch(96% 0.006 250)"
  border: "oklch(88% 0.012 250)"
  border-strong: "oklch(78% 0.018 250)"
  accent: "oklch(58% 0.16 158)"
  accent-muted: "oklch(95% 0.035 158)"
  code-bg: "oklch(18% 0.025 250)"
  warning-bg: "oklch(96% 0.07 85)"
  warning-text: "oklch(34% 0.09 70)"
  danger-bg: "oklch(96% 0.045 25)"
  danger-text: "oklch(38% 0.15 25)"
typography:
  family: "Inter, ui-sans-serif, system-ui, sans-serif"
  display:
    fontSize: "clamp(3rem, 8vw, 6rem)"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.03em"
  page-title:
    fontSize: "36px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  section-title:
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    fontSize: "12px"
    lineHeight: 1.7
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  full: "9999px"
spacing:
  page-x: "24px"
  page-y: "40px"
  section-y: "64px"
  container: "1152px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-secondary:
    backgroundColor: "{colors.background}"
    borderColor: "{colors.border-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  card:
    backgroundColor: "{colors.background}"
    borderColor: "{colors.border}"
    rounded: "{rounded.md}"
  panel:
    backgroundColor: "{colors.surface-muted}"
    borderColor: "{colors.border}"
    rounded: "{rounded.md}"
  table:
    headerBackground: "{colors.surface-muted}"
    borderColor: "{colors.border}"
  code-panel:
    backgroundColor: "{colors.code-bg}"
    textColor: "#f8fafc"
    rounded: "{rounded.md}"
---

# Rowset Design System

## Direction

Rowset now uses a quiet, light-first product system. The UI is a control
surface for agent setup, dataset visibility, schema review, exports, public
preview settings, and account recovery. It should not feel like an upload
wizard, no-code builder, or broad analytics dashboard.

The first useful action is copying the agent setup prompt. The rest of the UI
supports verification and control: MCP endpoint, REST base URL, recent datasets,
schema metadata, public preview settings, and bearer API key handling.

## Visual Principles

- Prefer flat, bordered surfaces over shadows and glow.
- Use cards only when they frame an interaction or record; otherwise use plain
  layout, dividers, and tables.
- Keep emerald for primary action, active state, and positive state. Do not use
  it as decoration.
- Avoid repeated uppercase section eyebrows. Short labels are sentence case and
  used only where they orient the user.
- Keep app headings calm. Marketing display type is allowed on the landing hero
  only and must not exceed `6rem` or tighter than `-0.03em`.
- Long routes, API keys, dataset names, filenames, headers, and public URLs must
  wrap or scroll without breaking layout.

## Layout

Use a max-width container around `1152px`. The public landing page can use wider
split sections, but authenticated pages should feel like focused workspaces.

- Dashboard: agent setup prompt first, connection details second, recent
  datasets below.
- Dataset list: records in rows, not cards.
- Dataset detail: title/status, API access, schema, sample rows.
- Dataset settings: schema metadata first, public preview controls second,
  destructive deletion last.
- Docs: stable left navigation, readable prose, compact page navigation.

## Components

- **Header:** sticky top bar, single bottom border, no floating pill chrome.
- **Buttons:** 8px radius, 40px minimum height, clear focus states.
- **Forms:** visible labels, 8px radius controls, readable placeholder contrast.
- **Tables:** compact, bordered containers with muted header rows.
- **Alerts:** full bordered boxes with semantic background tints.
- **Code panels:** near-black panels for prompts, auth headers, routes, and
  command examples.

## Product Guardrails

- Do not make dashboard upload/import the primary path.
- Do not promote Google Sheets connection, write-back, or sync as active UI
  promises unless the shipped feature is restored and tested.
- Public previews are read-only browser sharing, not authentication.
- Prefer MCP language first, REST fallback second, browser automation last.
- Never expose full API keys in public pages, screenshots, or docs examples.
