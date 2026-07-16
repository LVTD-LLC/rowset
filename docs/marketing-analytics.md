# Marketing analytics measurement contract

Status: implementation contract

Owner: Product Analytics

Effective: 2026-07-16

This is the minimum contract for Rowset's first measurable marketing campaign. It answers
reach, engagement, signup, activation, and human-only conversion without broad autocapture,
session replay, or speculative events. Add an event or property only when a named report below
cannot be answered without it.

## Canonical metrics

Use events captured after this contract's production deployment cutoff; older events are excluded
rather than migrated. Exclude events where `internal_traffic = true`. A person is a PostHog identity after normal
anonymous-to-identified merging; a session is keyed by PostHog's `$session_id`. HTTP requests,
IPs, and user-agent strings are never proxies for people or sessions.

| Metric | Definition | Canonical system |
| --- | --- | --- |
| Reach | Distinct PostHog people with an eligible `$pageview`. Report all reach and `traffic_category = human` reach side by side. | PostHog browser events |
| Engaged visit | Distinct `$session_id` with either two eligible `$pageview` events or one `public_dataset_row_opened`, `public_dataset_export_clicked`, `public_dataset_markdown_opened`, `signup_cta_clicked`, or `signup_started`. | PostHog browser events |
| Export intent | Count `public_dataset_export_clicked`; unique intent is distinct `$session_id` + `content_id` + `export_format`. A click is not an export success. | PostHog browser events |
| Signup started | Distinct PostHog people with `signup_started`. `signup_submitted` is a diagnostic step, not completion. | PostHog browser events |
| Signup completed | Distinct `profile_id` with `rowset_signup_completed`, counted after the account/profile transaction succeeds. | PostHog backend event |
| Activation | Distinct `profile_id` whose first `rowset_get_user_info_succeeded` occurs through authenticated REST or MCP. Repeated capability checks do not create more activations. | PostHog backend event |
| Human-only conversion | For one `campaign_id`, distinct profiles with `rowset_signup_completed` within seven days of their earliest linked `$pageview` carrying that ID and `traffic_category = human`, divided by distinct people with that acquisition pageview in the reporting window. First touch wins when a person encounters multiple campaigns; `$utm_campaign` is a breakdown, never the cohort key. Profiles without a linked acquisition pageview remain in total signup reporting but are excluded from this rate. | PostHog identity-linked browser and backend events |
| Public dataset requests | Successful public-preview requests grouped by immutable `content_id`. This includes no-JavaScript clients and is separate from visible impressions. | OpenTelemetry/server logs |
| Request volume | Count `http.request.completed` logs by normalized route, status class, interface, and traffic category. Never label this count as visitors. | OpenTelemetry/server logs |

External analytics is a reach cross-check, not a source for Rowset conversion metrics. Backend
success wins whenever browser intent and backend outcome disagree.

## Event contract

`current` means the producer exists on `origin/main` at the effective date. `planned` assigns the
exact contract to a downstream RMA task; it does not imply that data is already available.

| Event | Type | Status | Required properties | Optional properties | Source and trigger | Privacy | Example | Owner | Downstream metric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `$pageview` | Browser | planned | `route_name`, `pathname`, `hostname`, `referrer_domain`, `$session_id`, `traffic_category` | `campaign_id`, `$utm_source`, `$utm_medium`, `$utm_campaign`, `$utm_content`, `$utm_term`, `content_id` | Once after an eligible marketing, docs, auth, or public-dataset page renders. Public-preview pageviews require `content_id`. An HTMX history navigation emits once only when the user-visible URL changes. | derived and public-safe | `{$event: "$pageview", route_name: "pages:pricing"}` | Web | Reach, public dataset impressions, engaged visit, acquisition cohort |
| `public_dataset_row_opened` | Browser | planned | `content_id`, `$session_id`, `traffic_category` | `campaign_id` | Once when a row detail becomes visible after an intentional open. Do not include the row index or values. | derived and public-safe | `{content_id: "fddae2f3-e103-47fe-9605-9ae2669ba059"}` | Datasets | Engaged visit, dataset interaction |
| `public_dataset_export_clicked` | Browser | planned | `content_id`, `export_format`, `$session_id`, `traffic_category` | `campaign_id` | Once when a visitor intentionally chooses an export format, before delivery. | derived and public-safe | `{content_id: "fddae2f3-e103-47fe-9605-9ae2669ba059", export_format: "csv"}` | Datasets | Export intent, engaged visit |
| `public_dataset_export_completed` | Backend | planned | `content_id`, `export_format`, `request_id`, `traffic_category` | `$session_id`, `campaign_id` | Once after a public export returns a successful 2xx response. Deduplicate by `request_id`; compare intent and success as aggregates, not one-to-one click correlation. | derived, public-safe, and pseudonymous | `{content_id: "fddae2f3-e103-47fe-9605-9ae2669ba059", export_format: "csv"}` | Datasets | Export success |
| `public_dataset_markdown_opened` | Browser | planned | `content_id`, `$session_id`, `traffic_category` | `campaign_id` | Once when a visitor deliberately opens the Markdown/AI-reader representation. Server logs remain authoritative for successful delivery and sessionless agent requests. | derived and public-safe | `{content_id: "fddae2f3-e103-47fe-9605-9ae2669ba059"}` | Datasets | Engaged visit, Markdown intent |
| `signup_cta_clicked` | Browser | planned | `route_name`, `$session_id`, `traffic_category` | `campaign_id`, `content_id` | Once when an eligible signup CTA is intentionally activated. | derived and public-safe | `{route_name: "datasets:public-preview", content_id: "fddae2f3-e103-47fe-9605-9ae2669ba059"}` | Growth | Signup intent, engaged visit |
| `signup_started` | Browser | planned | `route_name`, `$session_id`, `traffic_category` | `campaign_id`, `$utm_source`, `$utm_medium`, `$utm_campaign`, `$utm_content`, `$utm_term` | Once per session when the signup form first becomes usable. | derived and public-safe | `{route_name: "account_signup", campaign_id: "hn-2026-07"}` | Identity | Signup started, engaged visit |
| `signup_submitted` | Browser | planned | `route_name`, `$session_id`, `traffic_category` | `campaign_id` | Once per form submission attempt. Never include form values or validation messages. | derived and public-safe | `{route_name: "account_signup"}` | Identity | Signup funnel diagnostics |
| `rowset_signup_completed` | Backend | current | `profile_id` | `$session_id`, `campaign_id` | After account/profile creation commits successfully. For browser signup, link the validated anonymous PostHog identity to `profile_id` before capture so conversion does not depend on a later page load. Count the first event per profile. | pseudonymous and public-safe | `{profile_id: "1842"}` | Identity | Signup completed, human-only conversion |
| `rowset_get_user_info_succeeded` | Backend | current | `profile_id`, `request_interface` | `$session_id`, `campaign_id`, `agent_api_key_access_level` | After an authenticated REST or MCP user-info request succeeds. Activation is the first event per `profile_id`; later events remain usage. | pseudonymous and public-safe | `{profile_id: "1842", request_interface: "mcp"}` | Agent platform | Activation |
| `http.request.completed` | Server log | current | `request.id`, `request.interface`, `http.route`, `http.response.status_class`, `traffic_category`, `internal_traffic` | `content_id`, `$session_id`, `campaign_id` | Once after every non-health HTTP request completes or raises. Public-preview routes require `content_id`; `outcome` remains the operational success/failure field. | derived, public-safe, and pseudonymous | `{http.route: "datasets:public-preview", http.response.status_class: "2xx"}` | Web | Public dataset requests, request volume |

For every event row, the complete required-property set is the row's listed properties plus
`internal_traffic`. The request-log row lists it directly. This shared invariant is normative and
must be included in producer completeness tests.

The current backend event and request-log producers do not yet emit every required property.
RMA-007 owns conversion events; RMA-008 and RMA-009 own missing log and traffic fields.
Existing dataset-created, row-mutated,
API-key-created, and setup-prompt-copied events remain product telemetry but are not required for
the first marketing report.

## Property contract

Omit optional properties when unavailable; never invent placeholder values. Strings are bounded
to 128 characters unless an enum is specified. PostHog carries `distinct_id` in the event envelope,
so it is not duplicated as an event property.

| Property | Type | Requirement | Source | Privacy | Example | Owner | Downstream metric |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `route_name` | Bounded Django route name | Required on browser page/auth events | Server-rendered route metadata | public-safe | `pages:pricing` | Web | Reach, funnel path |
| `pathname` | Normalized path or path template without query string | Required on `$pageview` | Server allowlist; browser reads rendered value | public-safe | `/share/datasets/:content_id/` | Web | Reach, funnel path |
| `hostname` | Lowercase allowlisted hostname | Required on `$pageview` | Browser location, allowlisted | public-safe | `rowset.lvtd.dev` | Web | Environment filtering |
| `referrer_domain` | Registrable domain or `direct`; never a full URL | Required on `$pageview` | Browser-derived from referrer | derived | `ycombinator.com` | Growth | Acquisition source |
| `campaign_id` | Bounded campaign slug | Required when a tagged campaign supplies it; optional otherwise | Allowlisted landing parameter, persisted by PostHog/session attribution | public-safe | `hn-2026-07` | Growth | Campaign cohort |
| `$utm_source` | Allowlisted lowercase slug | Optional; discard nonconforming values | Landing query parsed through the campaign allowlist; never raw SDK capture | public-safe | `hackernews` | Growth | Acquisition source |
| `$utm_medium` | Allowlisted lowercase slug | Optional; discard nonconforming values | Landing query parsed through the campaign allowlist; never raw SDK capture | public-safe | `community` | Growth | Acquisition source |
| `$utm_campaign` | Allowlisted lowercase slug | Optional; discard nonconforming values | Landing query parsed through the campaign allowlist; never raw SDK capture | public-safe | `public-dataset-launch` | Growth | Campaign cohort |
| `$utm_content` | Allowlisted creative slug | Optional; discard nonconforming values | Landing query parsed through the campaign allowlist; never raw SDK capture | public-safe | `show-hn-post` | Growth | Creative comparison |
| `$utm_term` | Allowlisted term slug; never raw search text | Optional; discard nonconforming values | Landing query parsed through the campaign allowlist; never raw SDK capture | public-safe | `agent-backend` | Growth | Campaign detail |
| `content_id` | Full immutable public-preview UUID; never dataset name or private dataset key | Required on public dataset events and public-preview request logs; omit on denied/not-found private resources | Dataset `public_key`, already exposed in the public URL | public-safe | `fddae2f3-e103-47fe-9605-9ae2669ba059` | Datasets | Asset-level reach, engagement, and requests |
| `$session_id` | PostHog session identifier | Required on browser events; optional only after validated backend correlation | PostHog web SDK | pseudonymous | `019b4a...` | Web | Sessions, engaged visit |
| `profile_id` | Stable internal profile ID string | Required on authenticated backend outcomes | Backend | pseudonymous | `1842` | Identity | Signup, activation |
| `request_id` | Server-generated opaque correlation ID, at most 128 characters | Required on export completion | Export service; never copy a client-supplied ID into analytics | pseudonymous | `f6a91e...` | Web | Export deduplication |
| `request_interface` | `rest` or `mcp` | Required on agent connection | Authenticated request boundary | public-safe | `mcp` | Agent platform | Activation by interface |
| `export_format` | `csv`, `jsonl`, `xlsx`, `sqlite`, or `parquet` | Required on export events | Browser selection/backend validation | public-safe | `csv` | Datasets | Export intent and success |
| `traffic_category` | `human`, `search_crawler`, `social_preview`, `ai_agent`, `unknown_automation`, or `authenticated_api` | Required on public browser and request events | Bounded server classifier; correlated to browser event | derived | `human` | Web | Human reach/conversion, agent use |
| `internal_traffic` | Boolean | Required on every contract event and request log | Explicit internal profile/session allowlist; never inferred from IP | derived | `false` | Product Analytics | Production cohort exclusion |
| `request.id` | Validated request correlation string | Required only in server logs; may preserve a validated client correlation header | Request middleware | pseudonymous | `edge.req-123` | Web | Request tracing |
| `request.interface` | `web`, `htmx`, or `rest` | Required only in `http.request.completed` | Request middleware | public-safe | `web` | Web | Request volume by interface |
| `http.route` | Normalized Django route name, never raw path | Required only in `http.request.completed` | Resolved request metadata | public-safe | `datasets:public-preview` | Web | Request volume, public asset requests |
| `http.response.status_class` | `2xx`, `3xx`, `4xx`, or `5xx` | Required only in `http.request.completed` | Response status | public-safe | `2xx` | Web | Request success/error rate |
| `agent_api_key_access_level` | `read`, `read_write`, or `admin` | Optional on authenticated agent events | Backend key record | public-safe | `read_write` | Agent platform | Activation diagnostics |

## Identity, attribution, and privacy rules

- Preserve PostHog's anonymous identity across normal full-page and HTMX navigation. Identify with
  `String(profile_id)` only after authentication; reset only on logout or account change.
- Use PostHog-native first-touch and current-touch attribution where it answers the report. Store
  custom attribution only after a production test proves a gap. Later direct traffic must not
  overwrite the first campaign touch.
- `content_id` identifies a public campaign asset, not a private dataset. It must be opaque and
  safe to expose in browser source, events, and bounded logs.
- Never capture dataset names, row indexes or contents, private dataset keys, emails, form values,
  validation messages, raw IPs, raw user agents, cookies, auth headers, tokens, reset links, full
  referrer URLs, or unbounded URLs/query strings.
- Treat campaign query parameters as untrusted input. Emit only configured slug values and discard
  email-like, token-like, overlength, or unknown values; PostHog must not automatically ingest the
  raw UTM query parameters.
- Generate analytics `request_id` values on the server. Client-provided correlation headers may be
  preserved as log-only `request.id` after validation, but must never be forwarded into PostHog
  event properties.
- Keep autocapture and session replay disabled. Explicit contract events are the complete first
  release; ordinary clicks and DOM text are not analytics inputs.
- Unknown traffic stays `unknown_automation`; do not silently count it as human. Human-only rates
  use only `traffic_category = human` acquisition events.
- Classify once at the server request boundary with this precedence: authenticated REST/MCP is
  `authenticated_api`; then known search crawlers, social previews, and AI-agent user-agent
  families; then ordinary allowlisted browser families as `human`; everything else is
  `unknown_automation`. Render the server result into browser events. A client cannot promote
  itself to `human`, and overlapping signals use the first matching category.
- Keep eligible routes, production hostnames, internal identities, campaign/UTM slugs, and traffic
  signature allowlists in one server-owned policy module: `apps/core/analytics_policy.py`. Event,
  request-log, and server-rendered browser metadata must call that policy rather than copy lists.

## Verification gate

Before any producer or dashboard ships:

1. Compare its exact event name and properties with this contract. While the product remains young,
   replace obsolete producers and update queries directly instead of adding compatibility paths.
2. Read the live PostHog event/property schema. Existing names may be reused only when their
   semantics match; otherwise remove or replace the producer while the product has no compatibility
   obligation.
3. Prove required-property completeness, anonymous continuity, one event per trigger, URL
   sanitization, and absence of prohibited data with focused tests.
4. Run a tagged production journey and reconcile browser events, backend outcomes, and request
   logs. Expected differences must be explained; request counts must never be called users.

Repository inspection on 2026-07-16 confirmed the current backend event names above,
`autocapture: false`, `capture_pageview: false`, anonymous identity preserved across ordinary
navigation, an explicit logout reset, normalized request logging, and validated request/session
correlation. The live PostHog schema still requires an authenticated connector check before
RMA-001 can be marked Done.
