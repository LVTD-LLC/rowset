COMPOSE_LOCAL ?= docker compose -f docker-compose-local.yml
COMPOSE_TEST ?= $(COMPOSE_LOCAL) -f docker-compose-test.yml
PYTHON_RUN ?= $(COMPOSE_LOCAL) run --rm backend python
CHECK_PYTHON_RUN ?= $(COMPOSE_TEST) run --rm backend python
PYTEST_RUN ?= $(COMPOSE_TEST) run --rm backend pytest
UV_RUN ?= uv run
NPM ?= npm
COVERAGE_RUN ?= $(COMPOSE_TEST) run --rm backend sh -c
COVERAGE_PYTEST ?= uv run --with coverage coverage run --source=apps,rowset -m pytest
COVERAGE_REPORT ?= uv run --with coverage coverage report -m
TARGET_ARGS = $(filter-out $@,$(MAKECMDGOALS))

.PHONY: \
	ci-local \
	cli-build \
	cli-test \
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
	native-logs \
	native-manage \
	native-restart \
	native-serve \
	native-shell \
	native-setup \
	native-start \
	native-status \
	native-stop \
	native-test \
	restart-worker \
	serve \
	shell \
	template-check \
	test

%:
	@:

serve:
	$(COMPOSE_LOCAL) up -d --build
	$(COMPOSE_LOCAL) logs -f backend

native-setup:
	./scripts/native-stack.sh setup

native-start:
	./scripts/native-stack.sh start

native-serve:
	./scripts/native-stack.sh start
	./scripts/native-stack.sh logs

native-stop:
	./scripts/native-stack.sh stop

native-restart:
	./scripts/native-stack.sh restart

native-status:
	./scripts/native-stack.sh status

native-logs:
	./scripts/native-stack.sh logs $(TARGET_ARGS)

native-manage:
	./scripts/native-stack.sh manage $(TARGET_ARGS)

native-shell:
	./scripts/native-stack.sh manage shell_plus --ipython

native-test:
	./scripts/native-stack.sh test $(TARGET_ARGS)

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

coverage:
	$(COVERAGE_RUN) '$(COVERAGE_PYTEST) $(TARGET_ARGS) && $(COVERAGE_REPORT)'

template-check:
	$(UV_RUN) djlint frontend/templates --check

frontend-install:
	$(NPM) ci

frontend-lint:
	$(NPM) run lint

frontend-build:
	$(NPM) run build

frontend-check: frontend-lint frontend-build

cli-test:
	cd cli && go test ./...

cli-build:
	mkdir -p cli/bin
	cd cli && go build -o bin/rowset ./cmd/rowset

restart-worker:
	$(COMPOSE_LOCAL) up -d workers --force-recreate
