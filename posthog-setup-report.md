<wizard-report>
# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into the Rowset Django project. The project already had a mature PostHog foundation (SDK installed, module-level initialization in `CoreConfig.ready()`, and a robust `track_activation_event` helper). The wizard built on top of this by adding the `PosthogContextMiddleware`, enabling exception autocapture, activating a previously-defined-but-unused event constant (`rowset_agent_setup_prompt_copied`), and instrumenting five new business-critical events across the core views and dataset views.

## Events instrumented

| Event Name | Description | File |
|---|---|---|
| `rowset_agent_setup_prompt_copied` | User fetches the agent setup prompt (copying it to configure their AI agent). | `apps/core/views.py` |
| `rowset_trial_reward_claimed` | User claims a trial reward to extend their trial period. | `apps/core/views.py` |
| `rowset_account_deleted` | User permanently deletes their account. | `apps/core/views.py` |
| `rowset_agent_api_key_revoked` | User revokes an agent API key. | `apps/core/views.py` |
| `rowset_dataset_exported` | User exports a dataset to CSV or another format. | `apps/datasets/views.py` |

## Infrastructure changes

| File | Change |
|---|---|
| `rowset/settings.py` | Added `posthog.integrations.django.PosthogContextMiddleware` to `MIDDLEWARE` |
| `apps/core/__init__.py` | Added `posthog.enable_exception_autocapture = True` to PostHog init |
| `apps/core/analytics.py` | Added constants: `ROWSET_TRIAL_REWARD_CLAIMED`, `ROWSET_ACCOUNT_DELETED`, `ROWSET_AGENT_API_KEY_REVOKED`, `ROWSET_DATASET_EXPORTED` |
| `.env` | Set `POSTHOG_API_KEY` and `POSTHOG_HOST` |

## Next steps

We've built a dashboard and five insights based on the events instrumented:

- **Dashboard**: [Analytics basics (wizard)](https://us.posthog.com/project/493217/dashboard/1871945)
- **Subscription conversion funnel**: [https://us.posthog.com/project/493217/insights/7WKibm9u](https://us.posthog.com/project/493217/insights/7WKibm9u)
- **Agent setup funnel**: [https://us.posthog.com/project/493217/insights/PijISd3I](https://us.posthog.com/project/493217/insights/PijISd3I)
- **Key activation events trend**: [https://us.posthog.com/project/493217/insights/8hxue0O8](https://us.posthog.com/project/493217/insights/8hxue0O8)
- **Churn signals**: [https://us.posthog.com/project/493217/insights/GjULzGCG](https://us.posthog.com/project/493217/insights/GjULzGCG)
- **Dataset usage activity**: [https://us.posthog.com/project/493217/insights/cGC3jTFX](https://us.posthog.com/project/493217/insights/cGC3jTFX)

## Verify before merging

- [ ] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code.
- [ ] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures.
- [ ] Add `POSTHOG_API_KEY` and `POSTHOG_HOST` to `.env.example` (or any bootstrap scripts) so collaborators know what to set.
- [ ] Confirm the returning-visitor path also calls `identify` — `track_activation_event` sets `$set` person properties on each capture, but verify that returning sessions are correctly associated with the authenticated user's profile ID.

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

</wizard-report>
