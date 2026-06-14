---
version: alpha
name: Rowset
description: A crisp product UI system for agent-managed API datasets.
colors:
  primary: "#07130F"
  primary-strong: "#020617"
  secondary: "#10B981"
  tertiary: "#22D3EE"
  accent: "#BEF264"
  neutral: "#F8FAFC"
  surface: "#FFFFFF"
  surface-muted: "#F1F5F9"
  surface-dark: "#0F172A"
  border: "#E2E8F0"
  border-dark: "#1E293B"
  text: "#0F172A"
  text-muted: "#475569"
  text-inverse: "#FFFFFF"
  text-inverse-muted: "#D1FAE5"
  success: "#34D399"
  warning: "#FDE047"
  danger: "#F87171"
typography:
  headline-display:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 72px
    fontWeight: 900
    lineHeight: 1
    letterSpacing: -0.055em
  headline-lg:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 60px
    fontWeight: 900
    lineHeight: 1
    letterSpacing: -0.045em
  headline-md:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 32px
    fontWeight: 900
    lineHeight: 1.1
    letterSpacing: -0.035em
  body-lg:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.6
  body-md:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.65
  body-sm:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  label-caps:
    fontFamily: Inter, ui-sans-serif, system-ui, sans-serif
    fontSize: 12px
    fontWeight: 800
    lineHeight: 1
    letterSpacing: 0.3em
  code-sm:
    fontFamily: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.7
rounded:
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 64px
  section-y: 96px
  page-x: 24px
  container: 1280px
components:
  button-primary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.full}"
    padding: 16px
  button-primary-hover:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
  button-secondary:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-inverse}"
    typography: "{typography.body-md}"
    rounded: "{rounded.full}"
    padding: 16px
  card-light:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.text}"
    rounded: "{rounded.xxl}"
    padding: 28px
  card-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-inverse}"
    rounded: "{rounded.xxl}"
    padding: 28px
  chip-success:
    backgroundColor: "{colors.success}"
    textColor: "{colors.primary}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.full}"
    padding: 8px
  code-panel:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.text-inverse-muted}"
    typography: "{typography.code-sm}"
    rounded: "{rounded.xl}"
    padding: 20px
  chip-api:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.primary-strong}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.full}"
    padding: 8px
  chip-export:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.primary}"
    typography: "{typography.label-caps}"
    rounded: "{rounded.full}"
    padding: 8px
  page-background:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.text}"
  divider-light:
    backgroundColor: "{colors.border}"
    height: 1px
  divider-dark:
    backgroundColor: "{colors.border-dark}"
    height: 1px
  muted-copy:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-muted}"
    typography: "{typography.body-sm}"
  alert-warning:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.primary-strong}"
    rounded: "{rounded.lg}"
    padding: 16px
  alert-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.primary-strong}"
    rounded: "{rounded.lg}"
    padding: 16px
---

# Rowset Design System

## Overview

Rowset should feel like a serious developer/data utility with just enough glow to make agent-managed data feel trustworthy. The core metaphor is **agent prompt → authenticated MCP → managed dataset → shareable preview**.

The UI combines dark, high-contrast command-center surfaces with bright emerald/cyan/lime accents. It should feel fast, technical, trustworthy, and pragmatic — closer to a polished internal data platform than a generic SaaS template.

Primary audiences are builders, operators, and AI-agent-heavy teams who want agents to create, mutate, export, and share stable datasets without custom backend work.

## Colors

The palette is built around a dark green-black base and API-like status accents.

- **Primary (#07130F):** Deep green-black for hero sections, CTAs on light backgrounds, and the core brand mood.
- **Primary Strong (#020617):** Near-black slate for code surfaces, product mocks, and maximum contrast panels.
- **Secondary (#10B981):** Emerald interaction color for primary action, success, active states, and the main dataset signal.
- **Tertiary (#22D3EE):** Cyan for API routes, secondary highlights, and technical affordances.
- **Accent (#BEF264):** Lime for export/share callouts and small high-energy moments; use sparingly.
- **Neutral/Surface (#F8FAFC / #FFFFFF / #F1F5F9):** Clean product surfaces for setup, dataset state, API details, and sharing controls.
- **Text (#0F172A / #475569):** Slate text keeps the product grounded and avoids pure-black harshness on light pages.

Use emerald as the dominant accent. Cyan and lime should support the API/export story, not compete for primary action ownership.

## Typography

Typography is intentionally system-first and dense enough for product work.

- **Headlines:** Heavy, tightly tracked sans-serif. Use `font-black`-style weight for concise product claims like “Rowset gives your AI agent a dataset backend.”
- **Body:** Neutral, readable sans-serif at comfortable line-height. Product explanations should feel concise, not precious.
- **Labels:** Uppercase, wide-tracked labels for section eyebrows, status chips, and technical metadata.
- **Code/data:** Monospace for routes, JSON, row previews, IDs, and API examples. Monospace blocks should reinforce that Rowset produces real machine-readable interfaces.

## Layout

Use a max-width container around 1280px with generous horizontal padding and spacious vertical section rhythm.

- Landing pages should alternate between immersive dark sections and clean light explanation sections.
- Hero layouts can use a two-column split: narrative/CTA on the left, API or dataset mock on the right.
- Product cards should be large, rounded, and grouped in simple grids: 3-up for process steps, 4-up for use cases, 2-up for before/after comparisons.
- Preserve strong responsive behavior: stack early, keep CTAs large, and avoid horizontal overflow from long API routes.

## Elevation & Depth

Depth comes from tonal layering, subtle borders, gradients, and controlled glow — not heavy generic shadows.

- Dark hero/product panels may use blurred emerald/cyan radial gradients behind the content.
- Light cards should rely on border contrast first, then soft shadows only on hover or important grouped panels.
- Code panels should feel inset and glassy with low-opacity white borders.
- Avoid drop-shadow-heavy “startup template” styling. Rowset should feel engineered.

## Shapes

The shape language is rounded and modern, but still structural.

- Use pill-shaped CTAs and chips (`9999px`) for primary actions and statuses.
- Use large-radius cards (`24px`–`32px`) for dataset panels, feature blocks, FAQ items, and product mocks.
- Use smaller radii (`8px`–`16px`) for form controls, table containers, and inline data rows.
- Keep radii consistent inside a section; do not mix sharp enterprise tables with bubbly marketing cards unless the contrast is intentional.

## Components

- **Primary button:** Emerald background, deep green-black text, pill radius, bold label, slight lift on hover. Only one dominant primary action per section.
- **Secondary button:** Subtle bordered or dark-surface pill. It should support sign-in/docs links without stealing attention from the primary action.
- **Dataset/API mock:** Dark slate shell, prompt panel, MCP endpoint, monospace route panel, JSON response block, and compact dataset state rows.
- **Feature cards:** Large rounded cards with one strong idea each. Use numbered or icon-led headers and concise body copy.
- **Before/after panels:** Pair agent prompt/setup state with dark product-grade route and tool panels.
- **FAQ items:** Dark rounded disclosure cards with emerald plus icons and muted answer text.
- **Forms/app screens:** Prefer clear labels, visible focus rings, generous touch targets, and helpful empty/error states over decoration.

## Do's and Don'ts

- Do make the agent outcome visible quickly: MCP URL, skill URL, dataset key, routes, JSON, indexed lookup, export, and public preview URL.
- Do keep copy practical and concrete; avoid vague “data transformation platform” language.
- Do use emerald for the main conversion path and success states.
- Do preserve WCAG AA contrast, especially on emerald/cyan/lime surfaces.
- Do treat long file names, column names, API keys, and routes as first-class overflow cases.
- Don't use generic SaaS gradients without product-specific data/API context.
- Don't overuse emojis; one small icon per use-case card is enough.
- Don't make manual upload the primary product path. Agents should create and mutate datasets through MCP or REST.
- Don't make public sharing feel like the default. Private authenticated API access is the core product path.
