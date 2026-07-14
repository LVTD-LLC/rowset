ARG UV_VERSION=0.11.15

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM node:24 AS build

WORKDIR /app
COPY . .

RUN npm install
RUN npm run build

FROM python:3.14

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV DJANGO_SETTINGS_MODULE=rowset.settings
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN chmod +x deployment/entrypoint.sh
COPY --from=build /app/frontend/build/ ./frontend/build/

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=10s --start-period=180s --retries=8 \
    CMD ["/opt/venv/bin/python", "-m", "deployment.healthcheck"]

CMD ["sh", "deployment/entrypoint.sh"]
