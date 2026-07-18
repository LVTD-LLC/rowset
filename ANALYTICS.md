# Product analytics

Rowset uses PostHog for consented product analytics. Sentry remains the source for application
errors. Never send API keys, dataset contents, query text, full URLs, Stripe identifiers, or ad
click IDs to PostHog.

## Event contract

Event names are lowercase snake case and describe completed actions. Every server event includes
`event_version`, `environment`, `profile_id`, and `current_state`. Browser and server events use the
profile ID as the identified `distinct_id`. Logout calls `reset()`.

The primary acquisition funnel is:

1. `$pageview` and `rowset_marketing_cta_clicked`
2. `rowset_signup_completed`
3. `rowset_agent_api_key_created` and `rowset_agent_setup_prompt_copied`
4. `rowset_agent_setup_completed`
5. `rowset_dataset_created` and `rowset_dataset_row_mutated`
6. `rowset_checkout_started` and `rowset_subscription_started`

Lifecycle events are `rowset_subscription_cancellation_requested`, `rowset_subscription_ended`,
and `rowset_payment_failed`. Additive property changes keep the current event version; incompatible
meaning changes require a new event name or version.

Critical signup, setup, checkout, and subscription events flush the server SDK queue before their
worker task completes. High-volume dataset activity remains buffered.

## Attribution and consent

Browser capture is opted out by default. A visitor must choose **Allow analytics** before Rowset
captures a pageview or CTA. Consent is stored for one year. Declining removes Rowset's attribution
cookie. Only `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, the normalized
landing route, and referring domain are retained. Click IDs such as `gclid` and `fbclid` are
intentionally excluded.

The sanitized first and latest touch are copied to the profile at signup. Backend activation and
revenue events then carry the latest `utm_*` properties and `initial_utm_*` properties, so campaign
reporting does not depend on a browser event arriving at the same time.

## PostHog project setup

- Send browser and backend events to the same project.
- Set `POSTHOG_BROWSER_HOST` to a first-party reverse proxy in production. It must forward PostHog
  ingestion and static asset paths without caching ingestion responses.
- Keep `POSTHOG_HOST` on the regional PostHog ingestion endpoint for server capture and logs.
- Exclude `environment != prod`, staff traffic, and known office/VPN traffic in PostHog project
  filters before using dashboards for marketing decisions.
- Build funnels using the events above and break down by `utm_source`, `utm_medium`, and
  `utm_campaign`. Use `initial_utm_*` for acquisition and unprefixed `utm_*` for latest-touch views.
- Validate a campaign with a unique test UTM through consent, signup, agent setup, and checkout
  before launching spend.
