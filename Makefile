COMPOSE_LOCAL ?= docker compose -f docker-compose-local.yml
COMPOSE_TEST ?= $(COMPOSE_LOCAL) -f docker-compose-test.yml
PYTHON_RUN ?= $(COMPOSE_LOCAL) run --rm backend python
CHECK_PYTHON_RUN ?= $(COMPOSE_TEST) run --rm backend python
PYTEST_RUN ?= $(COMPOSE_TEST) run --rm backend pytest
UV_RUN ?= uv run
NPM ?= npm
TARGET_ARGS = $(filter-out $@,$(MAKECMDGOALS))

.PHONY: \
	ci-local \
	coverage \
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
	restart-worker \
	serve \
	shell \
	template-check \
	test \
	type-check

%:
	@:

serve:
	$(COMPOSE_LOCAL) up -d --build
	$(COMPOSE_LOCAL) logs -f backend

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

format-python:
	$(UV_RUN) ruff format .

type-check:
	$(UV_RUN) ty check apps/core/capabilities.py apps/core/agent_skill.py rowset/utils.py rowset/logging_utils.py

coverage:
	$(COMPOSE_TEST) run --rm backend sh -c 'uv run --with coverage coverage run -m pytest $(TARGET_ARGS) && uv run --with coverage coverage report -m'

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
