# PostHog post-wizard report

The wizard has completed a deep integration of PostHog into the Rowset Django project. The project already had a sophisticated analytics foundation — SDK installed, module-level client configured in `CoreConfig.ready()`, 12 event constants, an async-task capture pipeline via django-q, and full frontend PostHog JS SDK with user identification and session-header forwarding. The wizard layered three targeted improvements on top of that foundation:

1. **`PosthogContextMiddleware`** added to `MIDDLEWARE` — automatically extracts `X-PostHog-Session-ID` and `X-PostHog-Distinct-ID` headers from every request and wires them into the PostHog context for correlated tracing.
2. **`atexit.register(posthog.shutdown)`** added to `CoreConfig.ready()` — ensures the SDK flushes its in-memory event buffer before the process exits.
3. **Two new server-side events** — `rowset_user_logged_in` (via Django's `user_logged_in` signal) and `rowset_account_deleted` (in the `delete_account` view) — fill gaps in the existing acquisition and lifecycle funnels.

## Events

| Event name | Description | File |
|---|---|---|
| `rowset_signup_completed` | A user completes the signup flow (email/password, passkey, or social). | `apps/pages/views.py` |
| `rowset_user_logged_in` | **New** — A user successfully authenticates and logs in to their account. | `apps/core/signals.py` |
| `rowset_account_deleted` | **New** — A user permanently deletes their account and all associated data. | `apps/core/views.py` |
| `rowset_agent_api_key_created` | A user creates a new agent API key from the settings page. | `apps/core/services.py` |
| `rowset_agent_setup_completed` | An agent completes the first-run setup by successfully calling get_user_info. | `apps/core/services.py` |
| `rowset_dataset_created` | A new dataset is created via the REST API or MCP. | `apps/api/services.py` |
| `rowset_dataset_row_mutated` | A row in a dataset is created, updated, or deleted by an agent. | `apps/api/row_mutations.py` |
| `rowset_checkout_started` | A user initiates a Stripe checkout session for a subscription plan. | `apps/core/views.py` |
| `rowset_subscription_started` | A Stripe webhook confirms a new subscription has been created. | `apps/core/stripe_webhooks.py` |
| `rowset_subscription_cancellation_requested` | A user requests cancellation of their active subscription. | `apps/core/stripe_webhooks.py` |
| `rowset_subscription_ended` | A subscription ends due to cancellation, non-payment, or trial expiry. | `apps/core/stripe_webhooks.py` |
| `rowset_payment_failed` | A subscription payment attempt fails as reported by Stripe webhook. | `apps/core/stripe_webhooks.py` |
| `rowset_get_user_info_succeeded` | An agent successfully retrieves authenticated user info via REST API or MCP. | `apps/api/views.py` |

## Next steps

We've built a dashboard and five insights to keep an eye on user behavior:

- **Dashboard** — [Analytics basics (wizard)](https://us.posthog.com/project/493217/dashboard/1872065)
- **Acquisition funnel** — [signup → API key → setup → dataset created](https://us.posthog.com/project/493217/insights/mWAMoVY4)
- **Signups over time** — [Daily signup trend (30 days)](https://us.posthog.com/project/493217/insights/3aSba7q2)
- **Agent activation steps** — [Weekly API key creation vs. setup completion (60 days)](https://us.posthog.com/project/493217/insights/VB7ieCUX)
- **Dataset activity** — [Daily datasets created and row mutations (30 days)](https://us.posthog.com/project/493217/insights/d6kvm3qh)
- **Unique active users** — [Weekly distinct users with agent calls (60 days)](https://us.posthog.com/project/493217/insights/fUkeC1V4)

## Verify before merging

- [ ] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code.
- [ ] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures. In particular, `apps/core/tests/test_signals.py` and `apps/core/tests/test_views.py` exercise the files that were changed.
- [ ] Confirm the returning-visitor path also calls `identify` — the frontend already calls `posthog.identify()` on page load for authenticated users, so this is handled, but verify the new `rowset_user_logged_in` signal fires correctly on both password and social login paths.

### Agent skill

We've left an agent skill folder in your project at `.claude/skills/integration-django/`. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.
