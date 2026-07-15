# Technology behind Rowset

Rowset uses a boring, reliable stack for agent-managed datasets without unnecessary moving parts.

- [Django](https://www.djangoproject.com/) is the primary web framework and backend foundation.
- [Djass](https://djass.dev/) provides codebase generation.
- [PostgreSQL](https://www.postgresql.org/) stores users, datasets, and API state.
- [Redis](https://redis.io/) provides caching and the message broker for background work.
- [Django-Q2](https://django-q2.readthedocs.io/) runs and schedules background tasks.
- [Alpine.js](https://alpinejs.dev/) manages local browser state for small controls.
- [HTMX](https://htmx.org/) provides server-rendered HTML updates without a client router.
- [PostHog](https://posthog.com/) provides product analytics and usage insights.
- [Sentry](https://sentry.io/) provides error tracking and production visibility.
- [CapRover](https://caprover.com/) supports deployment and server management.
- [WhiteNoise](https://whitenoise.evans.io/) serves static assets from Django.

Questions about the stack? Email [rasul@lvtd.dev](mailto:rasul@lvtd.dev).
