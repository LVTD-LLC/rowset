# Product analytics

Rowset uses PostHog for consented product analytics. Sentry remains the source for application
errors. Never send API keys, dataset contents, query text, full URLs, Stripe identifiers, or ad
click IDs to PostHog.

## Event contract

Event names are lowercase snake case and describe completed actions. Every server event includes
`event_version`, `environment`, and `current_state`; authenticated server events also include
`profile_id`. Browser and authenticated server events use the profile ID as the identified
`distinct_id`. Anonymous public server events use validated pseudonymous browser identity and
session headers when available and never invent a person identity. Logout calls `reset()`.

`rowset_traffic_request_observed` is the deliberate exception to the person-oriented server event
contract. It is a personless, GeoIP-disabled request-count signal with no stable or caller-supplied
identity and `$process_person_profile=false`; the SDK supplies a random event-scoped `distinct_id`.
Each capture uses a fresh PostHog context so it cannot inherit profile, session, or request tags.
Rowset supplies only the bounded traffic category, request interface, normalized Django route name,
outcome/status class, environment, and approved public content identity fields when available. It
never supplies a raw URL, query string, IP address, user-agent, cookie, authorization value, or MCP
method. The SDK may add its standard runtime and library context properties.

The primary acquisition funnel is:

1. `$pageview` and `rowset_marketing_cta_clicked`
2. `rowset_signup_completed`
3. `rowset_agent_api_key_created` and `rowset_agent_setup_prompt_copied`
4. `rowset_agent_setup_completed`
5. `rowset_dataset_created` and `rowset_dataset_row_mutated`
6. `rowset_checkout_started` and `rowset_subscription_started`

Public dataset measurement uses the same funnel vocabulary:

| Stage | Canonical signal | Meaning |
| --- | --- | --- |
| Reach | `$pageview` with `content_group=public_dataset` | A consented browser rendered an available public preview or row-detail page. |
| Intent | `rowset_public_dataset_row_opened` or `rowset_public_dataset_export_requested` | A consented browser deliberately opened a row or requested an export. |
| Engagement | `rowset_public_dataset_markdown_opened` or `rowset_public_dataset_export_completed` | The server successfully returned the Markdown representation or an export. |
| Conversion | The existing signup and activation events | The visitor completed signup or the first meaningful agent setup milestone. |

Intent events are browser signals; they do not prove the requested response succeeded. Completion
events are server signals and fire only after an eligible public request succeeds. Do not count raw
requests, pagination, filtering, sorting, or copied cell text as meaningful engagement.

Every public dataset signal includes `content_group=public_dataset`, a `content_id`, and a bounded
`content_surface` of `preview`, `row_detail`, `markdown`, or `export`. Export events also include a
bounded `export_format` from the formats the endpoint accepts. A row open identifies only the
dataset and surface; it never includes a row ID or row value.

`content_id` is the one approved asset-level identity. Derive it on the server as
`pd_v1_` followed by the first 24 lowercase hexadecimal characters of an HMAC-SHA256 digest of the
canonical lowercase public-key string, keyed by the deployment's Django `SECRET_KEY`. It is stable
within one deployment, unlinkable across deployments with different secrets, and changes if the
secret is rotated. Never send the public key, private dataset key, dataset name, column names, row
IDs, row values, preview password, or the raw public URL to PostHog.

Only successful, available public datasets receive a `content_id`. Every public dataset request
records a bounded `public_access_state` in structured request telemetry: `available` for an enabled
and authorized success, `locked` when a password is required, `denied` when supplied access is
invalid, `disabled` when sharing is inactive, and `not_found` when no active dataset exists.
Browser and PostHog server events are emitted only for `available`; the other states never receive
or expose a dataset identity.

Lifecycle events are `rowset_subscription_cancellation_requested`, `rowset_subscription_ended`,
and `rowset_payment_failed`. Additive property changes keep the current event version; incompatible
meaning changes require a new event name or version.

Critical signup, setup, checkout, and subscription events flush the server SDK queue before their
worker task completes. High-volume dataset activity remains buffered.

## Traffic categories and metric sources

`traffic_category` is a bounded derived property, not a claim that Rowset has identified a person.
Classify each request once, using the first matching rule below, and retain every category in
all-traffic reporting:

| Category | Deterministic rule |
| --- | --- |
| `api_client` | The request uses an API or MCP route/interface. This route rule wins over user-agent matching. |
| `ai_agent` | A maintained, explicit user-agent allowlist identifies an interactive AI agent or agent fetcher. |
| `link_preview` | A maintained, explicit user-agent allowlist identifies a social, chat, or search preview fetcher. |
| `crawler` | A maintained, explicit user-agent allowlist identifies a search, training, monitoring, or archival crawler. |
| `unknown_automation` | The user agent is absent, malformed, names a generic script client, or otherwise cannot be classified. |
| `human` | An eligible browser request has a recognizable browser user agent and matches neither an explicit automation category nor an unknown-automation condition. |

Keep the allowlists small, checked in, and covered by representative tests. Match case-insensitively
against bounded user-agent tokens; do not add the raw user agent as a Rowset event property.
Classification uses only route/interface and known user-agent tokens. It must not use raw IP
addresses, fingerprints, request-rate behavior, or probabilistic bot scores. Known AI crawlers
belong to `crawler`; reserve `ai_agent` for interactive agent/tool retrieval. Unknown traffic stays
visible instead of being folded into `human`.

For precedence examples, an API request with a browser-like user agent is `api_client`; a web
request with a missing, malformed, or generic-script user agent is `unknown_automation`; and only a
recognizable browser user agent unmatched by the earlier rules is `human`.

PostHog's `$virt_traffic_*` and `$virt_bot_*` properties are advisory diagnostics, not the canonical
Rowset category: their taxonomy and IP-assisted detection can change outside this repository. Do
not substitute them for `traffic_category` in funnels or human-only conversion reporting.

Put the server-derived category on eligible browser pageview/intent context for both full-page and
HTMX responses, on public server completion events, and on the personless
`rowset_traffic_request_observed` event emitted after Django and MCP requests complete. Do not
reclassify in browser JavaScript.

Use PostHog browser events as the canonical source for consented reach and intent, PostHog server
events for successful engagement and irreversible conversion, and structured request telemetry for
all request traffic including non-consenting browsers and automation. In PostHog, use
`rowset_traffic_request_observed` for total request volume and category shares; do not add it to
browser pageviews because the two events measure different things. Report both all-traffic and
`traffic_category=human` request views. Human-only conversion means human-category consented
browser reach joined to canonical server conversion events through the existing anonymous/profile
identity; do not divide raw request counts by signups or describe a user-agent category as verified
humanity.

## Attribution and consent

Browser capture is opted out by default. A visitor must choose **Allow analytics** before Rowset
captures a pageview, page-leave event, or CTA. Page-leave capture remains enabled while automatic
pageview and DOM autocapture stay disabled, so PostHog can calculate consented session duration
without collecting element interactions. Consent is stored for one year. Declining removes
Rowset's attribution cookie. Only `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`,
`utm_term`, `campaign_id`, the normalized landing route, referring domain, and the external
referrer origin are retained. Referrer paths and query strings are discarded. Click IDs such as
`gclid` and `fbclid` are intentionally excluded.

After identification, the sanitized first and latest touch are synchronized to the PostHog person
as `first_touch_*` and `current_touch_*` properties. The first touch is set once; a later tagged
navigation replaces the current touch, while an untagged signup or authentication navigation does
not erase it. For an authenticated and consenting visitor, the browser also sends a same-origin,
CSRF-protected synchronization request after attribution changes. The server reads and sanitizes
its own attribution cookie rather than accepting attribution JSON from the request. Backend
activation and revenue events then carry the latest campaign properties and their `initial_*`
equivalents, so campaign reporting does not depend on a browser event arriving at the same time.

## PostHog project setup

- Send browser and backend events to the same project.
- Set `POSTHOG_BROWSER_HOST` to a first-party reverse proxy in production. It must forward PostHog
  ingestion and static asset paths without caching ingestion responses.
- Keep the browser SDK's `ui_host` on the US PostHog app so generated links do not point at the
  ingestion proxy.
- Keep `POSTHOG_HOST` on the regional PostHog ingestion endpoint for server capture and logs.
- Exclude `environment != prod`, staff traffic, and known office/VPN traffic in PostHog project
  filters before using dashboards for marketing decisions.
- Build funnels using the events above and break down by `utm_source`, `utm_medium`, and
  `utm_campaign`. Use `initial_*` event properties or `first_touch_*` person properties for
  acquisition, and unprefixed event properties or `current_touch_*` person properties for the
  latest touch. Use `campaign_id` when the campaign platform supplies a stable campaign identifier.
- Validate a campaign with a unique test UTM through consent, signup, agent setup, and checkout
  before launching spend.
