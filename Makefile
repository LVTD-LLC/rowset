COMPOSE_LOCAL ?= docker compose -f docker-compose-local.yml
COMPOSE_TEST ?= $(COMPOSE_LOCAL) -f docker-compose-test.yml
PYTHON_RUN ?= $(COMPOSE_LOCAL) run --rm backend python
CHECK_PYTHON_RUN ?= $(COMPOSE_TEST) run --rm backend python
PYTEST_RUN ?= $(COMPOSE_TEST) run --rm backend pytest
UV_RUN ?= uv run
NPM ?= npm
COVERAGE_RUN ?= $(COMPOSE_TEST) run --rm backend sh -c
COVERAGE_PYTEST ?= uv run --with coverage coverage run --source=apps,rowset -m pytest
COVERAGE_FAIL_UNDER ?= 80
COVERAGE_REPORT ?= uv run --with coverage coverage report -m --fail-under=$(COVERAGE_FAIL_UNDER)
HIGH_RISK_COVERAGE_FILES = \
	apps/api/services.py \
	apps/datasets/services.py \
	apps/datasets/vector_search.py \
	apps/mcp_server/server.py
TYPE_CHECK_FILES = \
	apps/api/admin.py \
	apps/api/auth.py \
	apps/api/errors.py \
	apps/api/models.py \
	apps/api/row_contracts.py \
	apps/api/schemas.py \
	apps/api/urls.py \
	apps/api/utils.py \
	apps/blog/admin.py \
	apps/blog/choices.py \
	apps/blog/model_typing.py \
	apps/blog/models.py \
	apps/blog/urls.py \
	apps/blog/views.py \
	apps/core/admin.py \
	apps/core/agent_skill.py \
	apps/core/agents/base.py \
	apps/core/analytics.py \
	apps/core/base_models.py \
	apps/core/capabilities.py \
	apps/core/choices.py \
	apps/core/context_processors.py \
	apps/core/forms.py \
	apps/core/model_typing.py \
	apps/core/model_utils.py \
	apps/core/models.py \
	apps/core/signals.py \
	apps/core/stripe_webhooks.py \
	apps/core/templatetags/markdown_extras.py \
	apps/core/urls.py \
	apps/core/utils.py \
	apps/datasets/admin.py \
	apps/datasets/apps.py \
	apps/datasets/choices.py \
	apps/datasets/constants.py \
	apps/datasets/embeddings.py \
	apps/datasets/history.py \
	apps/datasets/management/commands/backfill_dataset_vectors.py \
	apps/datasets/management/commands/retry_dataset_asset_file_deletions.py \
	apps/datasets/model_typing.py \
	apps/datasets/public_previews.py \
	apps/datasets/services.py \
	apps/datasets/types.py \
	apps/datasets/urls.py \
	apps/datasets/vector_search.py \
	apps/datasets/vector_tasks.py \
	apps/docs/admin.py \
	apps/docs/models.py \
	apps/docs/urls.py \
	apps/docs/views.py \
	apps/mcp_server/apps.py \
	apps/mcp_server/auth.py \
	apps/mcp_server/models.py \
	apps/mcp_server/server.py \
	apps/pages/admin.py \
	apps/pages/checks.py \
	apps/pages/context_processors.py \
	apps/pages/model_typing.py \
	apps/pages/models.py \
	apps/pages/urls.py \
	apps/pages/use_cases.py \
	apps/pages/views.py \
	rowset/adapters.py \
	rowset/asgi.py \
	rowset/logging_utils.py \
	rowset/sentry_metrics.py \
	rowset/sentry_utils.py \
	rowset/settings.py \
	rowset/sitemaps.py \
	rowset/storages.py \
	rowset/urls.py \
	rowset/utils.py \
	rowset/wsgi.py \
	scripts/agent-eval-seed.py \
	scripts/check-quality-drift.py \
	scripts/startup-smoke.py
TARGET_ARGS = $(filter-out $@,$(MAKECMDGOALS))

.PHONY: \
	agent-eval-seed \
	ci-local \
	coverage \
	coverage-high-risk \
	django-check \
	format-check \
	format-python \
	frontend-build \
	frontend-check \
	frontend-install \
	frontend-lint \
	lint-python \
	manage \
	makemigrations \
	migrate \
	migrations-check \
	quality-drift-check \
	restart-worker \
	serve \
	shell \
	startup-smoke \
	template-check \
	test \
	type-check

%:
	@:

serve:
	$(COMPOSE_LOCAL) up -d --build
	$(COMPOSE_LOCAL) logs -f backend

agent-eval-seed:
	$(UV_RUN) python scripts/agent-eval-seed.py $(TARGET_ARGS)

shell:
	$(PYTHON_RUN) ./manage.py shell_plus --ipython

manage:
	$(PYTHON_RUN) ./manage.py $(TARGET_ARGS)

makemigrations:
	$(PYTHON_RUN) ./manage.py makemigrations

migrate:
	$(PYTHON_RUN) ./manage.py migrate

test:
	$(PYTEST_RUN) $(TARGET_ARGS)

migrations-check:
	$(CHECK_PYTHON_RUN) ./manage.py makemigrations --check --dry-run

django-check:
	$(CHECK_PYTHON_RUN) ./manage.py check

ci-local:
	./scripts/ci-local.sh

lint-python:
	$(UV_RUN) ruff check .

format-check:
	$(UV_RUN) ruff format --check .

quality-drift-check:
	$(UV_RUN) python scripts/check-quality-drift.py

startup-smoke:
	$(UV_RUN) python scripts/startup-smoke.py

format-python:
	$(UV_RUN) ruff format .

type-check:
	$(UV_RUN) ty check $(TYPE_CHECK_FILES)

coverage:
	$(COVERAGE_RUN) '$(COVERAGE_PYTEST) $(TARGET_ARGS) && $(COVERAGE_REPORT)'

coverage-high-risk:
	$(COVERAGE_RUN) '$(COVERAGE_PYTEST) $(TARGET_ARGS) && $(COVERAGE_REPORT) $(HIGH_RISK_COVERAGE_FILES)'

template-check:
	$(UV_RUN) djlint frontend/templates --check

frontend-install:
	$(NPM) ci

frontend-lint:
	$(NPM) run lint

frontend-build:
	$(NPM) run build

frontend-check: frontend-lint frontend-build

restart-worker:
	$(COMPOSE_LOCAL) up -d workers --force-recreate
