# Self-hosting Rowset

<!-- toc -->
## Table of contents

- [Render deployment](#render-deployment)
- [Required configuration](#required-configuration)
- [Docker Compose deployment](#docker-compose-deployment)
- [What you'll learn](#what-youll-learn)
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup steps](#setup-steps)
  - [1. Create deployment directory](#1-create-deployment-directory)
  - [2. Download and configure environment file](#2-download-and-configure-environment-file)
  - [3. Download docker-compose file](#3-download-docker-compose-file)
  - [4. Start the application](#4-start-the-application)
  - [5. Verify deployment](#5-verify-deployment)
  - [Lifecycle and local Docker logs](#lifecycle-and-local-docker-logs)
- [Persistent media and backups](#persistent-media-and-backups)
- [Expose your application](#expose-your-application)
  - [Option 1: Direct port access](#option-1-direct-port-access)
  - [Option 2: Nginx reverse proxy (recommended)](#option-2-nginx-reverse-proxy-recommended)
  - [Option 3: Add SSL with Certbot](#option-3-add-ssl-with-certbot)
- [Environment variables](#environment-variables)
- [Required variables](#required-variables)
  - [Core Django settings](#core-django-settings)
  - [Database configuration](#database-configuration)
  - [Redis configuration](#redis-configuration)
- [Optional variables](#optional-variables)
  - [Sentry (Error Tracking)](#sentry-error-tracking)
  - [PostHog (Analytics and Logs)](#posthog-analytics-and-logs)
  - [Chatwoot (Support Chat)](#chatwoot-support-chat)
  - [Buttondown (Email Newsletter)](#buttondown-email-newsletter)
  - [Stripe (Payments)](#stripe-payments)
  - [Email configuration](#email-configuration)
  - [OAuth/Social Authentication](#oauthsocial-authentication)
  - [Storage configuration](#storage-configuration)
  - [MJML (Email Templates)](#mjml-email-templates)
  - [Logging](#logging)
- [Getting the .env.example file](#getting-the-envexample-file)
- [Security best practices](#security-best-practices)
<!-- /toc -->


This file keeps deployment/self-hosting notes in the repository without exposing them in the in-app user documentation.


## Render deployment


[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=)

## Required configuration

Before deploying, you need to configure environment variables. See the environment variables section below for detailed information about all configuration options.

Refer to the environment variables section below for the complete list of required and optional variables.

All other variables beyond the required ones are optional but may enhance functionality.

**Note:** This should work out of the box with Render's free tier if you provide the required configuration. Here's what you need to know about the limitations:

- **Worker Service Limitation**: The worker service is not a dedicated worker type (those are only available on paid plans). For the free tier, I had to use a web service through a small hack, but it works fine for most use cases.

- **Memory Constraints**: The free web service has a 512 MB RAM limit, which can cause issues with **automated background tasks only**. When you add a project, it runs a suite of background tasks to analyze your website, generate articles, keywords, and other content. These automated processes can hit memory limits and potentially cause failures.

- **Manual Tasks Work Fine**: However, if you perform tasks manually (like generating a single article), these typically use the web service instead of the worker and should work reliably since it's one request at a time.

- **Upgrade Recommendation**: If you do upgrade to a paid plan, use the actual worker service instead of the web service workaround for better automated task reliability.

**Reality Check**: The website functionality should be usable on the free tier - you'll only pay for API costs. Manual operations work fine, but automated background tasks (especially when adding multiple projects) may occasionally fail due to memory constraints. It's not super comfortable for heavy automated use, but perfectly functional for manual content generation.

If you know of any other services like Render that allow deployment via a button and provide free Redis, Postgres, and web services, please let me know in the [Issues](/issues) section. I can try to create deployments for those. Bear in mind that free services are usually not large enough to run this application reliably.

## Docker Compose deployment


Deploy Rowset on your own server using Docker Compose.

## What you'll learn

- Set up Rowset with Docker Compose
- Configure environment variables
- Access your deployed application
- Troubleshoot common deployment issues

## Overview

Docker Compose provides a streamlined way to deploy Rowset on your server. This method handles all services (database, Redis, backend, and workers) with a single command.

This approach works best if you have a VPS or dedicated server where you can run Docker.

## Prerequisites

Before starting, make sure you have:

- A server with Docker, Docker Buildx, and Docker Compose installed
- A `linux/amd64` or `linux/arm64` server. These are the architectures published
  by the Rowset container image.
- SSH access to your server
- Basic familiarity with command line
- API keys for AI services (Gemini, Perplexity, Jina Reader, Keywords Everywhere)

## Setup steps

### 1. Fetch the deployment files

SSH into your server and clone Rowset so the Compose file, environment example,
and architecture preflight stay together:

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
```

### 2. Configure the environment

Copy the example environment file:

```bash
cp .env.example .env
```

Now edit the `.env` file to add your credentials:

```bash
nano .env
```

You need to configure several environment variables for Rowset to work properly. See the environment variables section below for complete details on all available options.

At minimum, update these required values:

- AI API keys (GEMINI_API_KEY, PERPLEXITY_API_KEY, JINA_READER_API_KEY, KEYWORDS_EVERYWHERE_API_KEY)
- Database password (POSTGRES_PASSWORD)
- Redis password (REDIS_PASSWORD)
- Django secret key (SECRET_KEY)
- Allowed hosts (ALLOWED_HOSTS)
- Debug mode (DEBUG - set to False for production)

The `.env.example` file includes all available configuration options with explanations. Update any additional settings you need.

Save the file (in nano: Ctrl+X, then Y, then Enter).

### 3. Verify image architecture support

Use an immutable release or full Git SHA tag and verify that its manifest
contains the current server platform before pulling it:

```bash
export ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:<release-or-sha-tag>
deployment/verify-image-platforms.sh "$ROWSET_IMAGE"
```

The preflight accepts `linux/amd64` and `linux/arm64` only, and fails when the
selected image manifest does not include the host architecture. Add the same
`ROWSET_IMAGE` value to `.env`; both application services use it.

### 4. Start the application

Run this command to start all services:

```bash
export ROWSET_IMAGE="$(sed -n 's/^ROWSET_IMAGE=//p' .env)"
docker compose -f docker-compose-prod.yml -p rowset up --detach --remove-orphans
```

Docker will:
- Download the necessary images
- Create the database and Redis containers
- Start the backend and worker services
- Run database migrations automatically

This takes 2-5 minutes on first deployment.

### 5. Verify deployment

Check that all services are running:

```bash
docker compose ps
```

You should see four containers running: `db`, `redis`, `backend`, and `workers`.

Check the logs to ensure no errors:

```bash
docker compose logs backend
```

### Lifecycle and local Docker logs

All four services use `restart: unless-stopped`, so containers restart
automatically after a Docker daemon or host restart unless an operator stopped
them explicitly. Backend and workers wait for healthy PostgreSQL and Redis
dependencies during Compose startup.

Docker's local `json-file` logs rotate at three 10 MB files: approximately
30 MB per service and 120 MB across the four-service stack, before small Docker
metadata overhead. Application-level external logging remains separately
configurable through the optional observability settings below.

To validate or share the Compose structure without resolving `.env` values, use:

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p rowset \
  config --no-env-resolution --no-interpolate
```

Do not share `.env`, ordinary fully resolved `docker compose config` output, or
container environment output; all can contain secrets.

## Persistent media and backups

The production Compose file keeps local uploads in two named volumes and mounts
both volumes into the backend and workers:

- `media_data` stores files written through Django's default media storage at
  `/app/media`.
- `private_media_data` stores private dataset image and audio assets at
  `/app/private_media` when S3-compatible asset storage is not configured.

Named volumes survive container replacement, so normal updates and
`docker compose up -d --force-recreate` do not remove uploaded files. Never use
`docker compose down -v` during an update: `-v` deletes the database, Redis, and
both media volumes.

For a small single-server installation, local volumes are the simplest option.
Create a permission-restricted archive of both media paths with:

```bash
deployment/self-host/backup-local-media.sh /var/backups/rowset
```

The command starts a one-off backend container, reads both volumes, and writes a
timestamped `.tar.gz` plus a `.sha256` checksum with mode `0600`. Copy these
archives off the server; a backup stored only on the Rowset host does not protect
against disk or server loss. This media-only archive does not include PostgreSQL,
so it must be paired with a database backup for a complete restore.

Use S3-compatible storage when private dataset assets should be durable outside
the Compose host or shared across multiple hosts. Setting
`ROWSET_ASSET_S3_ENDPOINT_URL` moves private dataset assets to that object store;
it does not move files written through Django's default `/app/media` storage.
Continue backing up `media_data`, and follow the object store provider's
versioning and backup guidance for the private asset bucket.

## Expose your application

The backend runs on port 8000. You need to expose it to the internet.

### Option 1: Direct port access

If your server allows it, access Rowset at:

```
http://your-server-ip:8000
```

This works for testing but isn't recommended for production.

### Option 2: Nginx reverse proxy (recommended)

Install Nginx on your server:

```bash
sudo apt update
sudo apt install nginx
```

Create an Nginx configuration:

```bash
sudo nano /etc/nginx/sites-available/rowset
```

Add this configuration:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/rowset /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Now access Rowset at `http://yourdomain.com`.

### Option 3: Add SSL with Certbot

Secure your site with HTTPS:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Follow the prompts. Certbot automatically configures SSL and sets up auto-renewal.

## Environment variables


This guide covers all environment variables needed to configure Rowset.

## Required variables

These variables are essential for Rowset to function:

### Core Django settings

**ENVIRONMENT**
- Environment mode for the application
- Values: `dev` or `prod`
- Set to `prod` for production deployments
- Set to `dev` for local development

**SECRET_KEY**
- Secret key for Django security features
- Must be kept confidential in production
- Generate one with: `python -c "import secrets; print(secrets.token_urlsafe(50))"`

**DEBUG**
- Set to `False` in production
- Set to `True` only for local development
- Never deploy to production with DEBUG=True

**SITE_URL**
- Full URL where your Rowset instance is accessible
- Example: `https://yourdomain.com`
- Used for generated public URLs, trusted origins, and the Django Site domain
- Running migrations synchronizes the Django Site record; no admin edit is required

**ALLOW_SIGNUPS**
- Set to `False` to pause new account creation
- Defaults to `True`
- Existing users can still log in while signups are paused

**ALLOWED_HOSTS**
- Comma-separated list of domains that can access your application
- Example: `yourdomain.com,www.yourdomain.com`
- Use `*` for testing only (not secure for production)

### Database configuration

**POSTGRES_DB**
- Name of the PostgreSQL database
- Example: `rowset_db`

**POSTGRES_USER**
- PostgreSQL username
- Example: `rowset_user`

**POSTGRES_PASSWORD**
- Password for your PostgreSQL database
- Use a strong, randomly generated password
- Generate one with: `openssl rand -base64 32`

**POSTGRES_HOST**
- PostgreSQL server hostname
- Example: `localhost` (for local), `db` (for Docker)

**POSTGRES_PORT**
- PostgreSQL server port
- Default: `5432`
- Optional - defaults to 5432 if not specified

### Redis configuration

**REDIS_HOST**
- Redis server hostname
- Example: `localhost` (for local), `redis` (for Docker)
- Default: `localhost`

**REDIS_PORT**
- Redis server port
- Default: `6379`

**REDIS_PASSWORD**
- Password for your Redis instance
- Use a strong, randomly generated password
- Generate one with: `openssl rand -base64 32`

**REDIS_DB**
- Redis database number
- Default: `0`

## Optional variables

These variables enhance functionality but aren't required:

### Sentry (Error Tracking)

**SENTRY_DSN**
- DSN for Sentry error tracking
- Get your DSN from [Sentry](https://sentry.io/)
- Used for error monitoring, tracing, profiling, and logs
- Leave empty to disable Sentry

**SENTRY_RELEASE**
- Optional release identifier, usually your deployed commit SHA or app version
- Enables Sentry release/regression tracking and links issues to deploys

**SENTRY_TRACES_SAMPLE_RATE**
- Performance trace sample rate from `0.0` to `1.0`
- Defaults to `1.0` so low-volume/open-source projects get complete traces

**SENTRY_PROFILE_SESSION_SAMPLE_RATE**
- Profiling sample rate for sampled traces from `0.0` to `1.0`
- Defaults to `1.0`; reduce for high-traffic projects if needed

**SENTRY_ENABLE_LOGS**
- Set to `True` to enable Sentry structured logs support
- Defaults to `True`

**SENTRY_ENABLE_METRICS**
- Set to `True` to emit low-cardinality HTTP request count and duration metrics
- Defaults to `True`

**SENTRY_SEND_DEFAULT_PII**
- Set to `True` to attach authenticated user/request PII to Sentry events
- Defaults to `False`; only enable when your privacy policy and data handling allow it

**SENTRY_INCLUDE_LOCAL_VARIABLES**
- Set to `True` to include stack-frame local variables in Sentry events
- Defaults to `False` to avoid accidentally capturing secrets or sensitive form data

**SENTRY_MAX_BREADCRUMBS**
- Number of breadcrumbs kept with each event
- Defaults to `100`

### PostHog (Analytics and Logs)

**POSTHOG_API_KEY**
- PostHog project token beginning with `phc_`
- Get your key from [PostHog](https://posthog.com/)
- Used for product analytics, feature flags, and OTLP log ingestion
- Leave empty to disable PostHog

**POSTHOG_HOST**
- Regional PostHog ingestion host
- Defaults to `https://us.i.posthog.com`; use `https://eu.i.posthog.com` for EU Cloud

**POSTHOG_LOGS_ENABLED**
- Enables batched OpenTelemetry log export
- Defaults to enabled in production when `POSTHOG_API_KEY` is configured

**POSTHOG_LOG_LEVEL**
- Minimum log level exported to PostHog
- Defaults to `INFO`

**POSTHOG_SERVICE_NAME**
- Optional service name used by PostHog's OpenTelemetry service facet
- Defaults to `rowset-web` or `rowset-worker`

### Chatwoot (Support Chat)

**CHATWOOT_BASE_URL**
- Base URL for your Chatwoot instance
- Leave empty to disable the support chat widget

**CHATWOOT_WEBSITE_TOKEN**
- Website inbox token from Chatwoot
- Leave empty to disable the support chat widget

**CHATWOOT_HMAC_SECRET**
- Optional identity validation secret from the Chatwoot website inbox
- When set, authenticated Rowset users are identified with an HMAC hash

### Buttondown (Email Newsletter)

**BUTTONDOWN_API_KEY**
- API key for Buttondown email service
- Get your key from [Buttondown](https://buttondown.email/)
- Used for managing email newsletters
- Leave empty to disable Buttondown integration

### Stripe (Payments)

**STRIPE_LIVE_SECRET_KEY**
- Stripe secret key for live/production mode
- Get from [Stripe Dashboard](https://dashboard.stripe.com/)
- Used for processing real payments
- Leave empty if only using test mode

**STRIPE_TEST_SECRET_KEY**
- Stripe secret key for test mode
- Get from [Stripe Dashboard](https://dashboard.stripe.com/)
- Used for testing payment flows
- Required for development

**DJSTRIPE_WEBHOOK_SECRET**
- Webhook signing secret from Stripe
- Get from Stripe webhook configuration
- Used to verify webhook authenticity
- Required for handling Stripe events

### Email configuration

Configure these to send emails from Rowset (for notifications, password resets, etc.):

**MAILGUN_API_KEY**
- API key for Mailgun email service
- Get your key from [Mailgun](https://www.mailgun.com/)
- Used for sending transactional emails
- Leave empty to use console email backend (emails printed to console)

**MAILGUN_SENDER_DOMAIN**
- Mailgun sender domain used for the API endpoint
- Defaults to `mg.lvtd.dev`
- The app sends transactional email from `Rasul Kireev <rasul@lvtd.dev>`

### OAuth/Social Authentication

**GITHUB_CLIENT_ID**
- GitHub OAuth application client ID
- Get from [GitHub Developer Settings](https://github.com/settings/developers)
- Used for GitHub social login
- Leave empty to disable GitHub authentication

**GITHUB_CLIENT_SECRET**
- GitHub OAuth application client secret
- Get from [GitHub Developer Settings](https://github.com/settings/developers)
- Required if GITHUB_CLIENT_ID is set

### Dataset Asset Storage

Configure these to store private dataset image assets in Cloudflare R2 or another
S3-compatible object store. Leave `ROWSET_ASSET_S3_ENDPOINT_URL` empty to use
local disk storage.

**ROWSET_ASSET_S3_ENDPOINT_URL**
- Cloudflare R2 S3-compatible endpoint URL
- Example: `https://<account-id>.r2.cloudflarestorage.com`

**ROWSET_ASSET_STORAGE_BUCKET_NAME**
- R2 bucket name for private dataset image assets

**ROWSET_ASSET_ACCESS_KEY_ID**
- R2 access key ID
- Required when `ROWSET_ASSET_S3_ENDPOINT_URL` is set

**ROWSET_ASSET_SECRET_ACCESS_KEY**
- R2 secret access key
- Required when `ROWSET_ASSET_S3_ENDPOINT_URL` is set

**ROWSET_ASSET_REGION_NAME**
- S3-compatible region name
- Use `auto` for Cloudflare R2

### Vector Search

Configure these only when you want semantic dataset row search. Rowset/Postgres
remains the canonical source of truth; Qdrant is a rebuildable retrieval index.

**ROWSET_VECTOR_SEARCH_ENABLED**
- Set to `True` to enable vector indexing, backfill, and search.
- Leave `False` until Qdrant and the embedding provider are configured.

**QDRANT_URL**
- Qdrant HTTP URL.
- For private Docker or CapRover deployments, prefer an internal service URL.

**QDRANT_API_KEY**
- Qdrant API key, if your Qdrant service requires one.
- Keep this secret out of logs, docs examples, and screenshots.

**QDRANT_COLLECTION_PREFIX**
- Prefix for Rowset-managed Qdrant collections.
- Defaults to `rowset`.

**QDRANT_TIMEOUT_SECONDS**
- Timeout for Qdrant client requests.
- Defaults to `10`.

**ROWSET_EMBEDDING_MODEL**
- Embedding model used for dataset row vectors.
- Defaults to `openai/text-embedding-3-small`.

**ROWSET_EMBEDDING_DIMENSIONS**
- Embedding dimension count. Do not mix incompatible dimensions in one collection.
- Defaults to `1536`.

**OPENROUTER_BASE_URL**
- OpenRouter API base URL used by PydanticAI embeddings.
- Defaults to `https://openrouter.ai/api/v1`.

**OPENROUTER_API_KEY**
- OpenRouter API key used for the configured embedding model.
- Required when vector search is enabled.

After enabling vector search, backfill an existing ready dataset with:

```bash
python manage.py backfill_dataset_vectors <dataset_key> --dry-run
python manage.py backfill_dataset_vectors <dataset_key>
```

Use `--limit` for a small first run and `--batch-size` to tune embedding and
Qdrant write batches.

### MJML (Email Templates)

**MJML_URL**
- URL for MJML HTTP server
- Used for rendering MJML email templates to HTML
- Leave empty to use MJML command-line tool

### Logging

**DJANGO_LOG_LEVEL**
- Django logging level for production
- Values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- Default: `INFO`
- Only applies when ENVIRONMENT=prod

## Getting the .env.example file

The complete `.env.example` file with all variables and detailed comments is available in the Rowset repository.

Download it directly:

```bash
wget /raw/main/.env.example -O .env
```

Or with curl:

```bash
curl -o .env /raw/main/.env.example
```

This file includes all available options with explanations and example values.

## Security best practices

Follow these guidelines to keep your Rowset installation secure:

**Never commit .env files**
- Add `.env` to your `.gitignore`
- Use environment variables or secret management systems for production

**Use strong passwords**
- Generate random passwords for database and Redis
- Use at least 32 characters for production passwords

**Keep secrets confidential**
- Don't share your SECRET_KEY or API keys
- Rotate keys immediately if exposed

**Use HTTPS in production**
- Set ALLOWED_HOSTS to specific domains only
- Configure SSL/TLS certificates for your domain
- Never set DEBUG=True in production

**Limit access**
- Use firewall rules to restrict database and Redis access
- Only expose necessary ports to the internet
- Use strong authentication for all services
