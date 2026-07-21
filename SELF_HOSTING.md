# Self-host Rowset with Docker Compose

Rowset ships one production Compose file. This guide is the deployment interface for people and AI
agents; there is no installer or Rowset-specific deployment command to learn.

The stack runs Caddy, PostgreSQL, Redis, the Rowset web process, and Rowset workers. Caddy is the
only public service and obtains HTTPS certificates automatically. Qdrant is an optional private
service for vector search.

## Prerequisites

Use a Linux server with:

- a public `amd64` or `arm64` CPU;
- Git and OpenSSL;
- Docker Engine with Compose v2.23 or newer;
- at least 4 GB RAM and 25 GB disk;
- a hostname whose `A` or `AAAA` record points to the server; and
- inbound TCP ports 80 and 443, plus UDP 443, open in the firewall.

Run the commands below as a user allowed to use Docker. Do not expose PostgreSQL, Redis, Qdrant, or
the Rowset backend directly to the internet.

## 1. Check out a release

Clone Rowset and check out the newest dated release. Keeping the source tag and container tag equal
makes updates and rollbacks understandable.

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
ROWSET_VERSION="$(git tag --list '20*' --sort=-version:refname | head -n 1)"
test -n "$ROWSET_VERSION"
git checkout "$ROWSET_VERSION"
```

Published Rowset images support `linux/amd64` and `linux/arm64`. For a stricter supply-chain policy,
replace the release tag in `ROWSET_IMAGE` with the digest shown by the GitHub release or registry.

## 2. Create the production environment

Set the public hostname, then create an owner-only `.env` file. The commands generate independent,
shell-safe secrets locally and do not print them.

```bash
export ROWSET_DOMAIN=rowset.example.com
umask 077
cat > .env <<EOF
ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:$ROWSET_VERSION
ROWSET_DOMAIN=$ROWSET_DOMAIN

ENVIRONMENT=prod
DEBUG=off
SECRET_KEY=$(openssl rand -hex 32)

POSTGRES_DB=rowset
POSTGRES_USER=rowset
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_PASSWORD=$(openssl rand -hex 32)

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=$(openssl rand -hex 32)

ROWSET_VECTOR_SEARCH_ENABLED=False
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=$(openssl rand -hex 32)
OPENROUTER_API_KEY=
EOF
chmod 600 .env
```

Replace `rowset.example.com` before continuing. Never commit `.env`, paste it into chat, or share a
fully interpolated Compose configuration.

Optional integrations such as GitHub or Google login, Mailgun, Sentry, PostHog, and S3-compatible
asset storage use the environment variables documented in [README.md](README.md#environment-variables).
Add only the integrations you actually use.

Validate the Compose model before it creates anything:

```bash
docker compose -p rowset -f docker-compose-prod.yml config --quiet
```

## 3. Start Rowset

```bash
docker compose -p rowset -f docker-compose-prod.yml pull
docker compose -p rowset -f docker-compose-prod.yml up -d
```

The Rowset image applies database migrations during startup. Services use `restart: unless-stopped`,
and Docker rotates each service's local logs at three 10 MB files.

Caddy requests a certificate after DNS and ports 80 and 443 are correct. Inspect startup without
printing container environments:

```bash
docker compose -p rowset -f docker-compose-prod.yml ps
docker compose -p rowset -f docker-compose-prod.yml logs --tail=100 caddy backend workers
```

## 4. Verify the deployment

Run Django's production checks inside the deployed container, verify HTTPS without bypassing
certificate validation, and confirm the private API rejects anonymous access:

```bash
docker compose -p rowset -f docker-compose-prod.yml exec -T backend \
  python manage.py check --deploy
curl -fsS "https://$ROWSET_DOMAIN/" >/dev/null
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  "https://$ROWSET_DOMAIN/api/user")" = "401"
```

Create an account in the browser and create a scoped agent API key in Settings. Keep it in a secret
store or private shell, then verify authenticated REST access:

```bash
export ROWSET_API_KEY="replace-with-your-copied-key"
curl -fsS "https://$ROWSET_DOMAIN/api/user" \
  -H "Authorization: Bearer $ROWSET_API_KEY"
```

Configure a Streamable HTTP MCP client with:

```text
URL: https://<ROWSET_DOMAIN>/mcp/
Authorization: Bearer <ROWSET_API_KEY>
```

For Codex-compatible clients:

```bash
codex mcp add rowset \
  --url "https://$ROWSET_DOMAIN/mcp/" \
  --bearer-token-env-var ROWSET_API_KEY
```

Discover the live tool schemas, then call `get_user_info` and `get_rowset_capabilities`. Do not put
the raw API key in MCP configuration or logs.

## Optional vector search

PostgreSQL remains the source of truth; Qdrant is a rebuildable private index. To enable it, set
`ROWSET_VECTOR_SEARCH_ENABLED=True` and `OPENROUTER_API_KEY` in `.env`, then start the profile:

```bash
docker compose -p rowset -f docker-compose-prod.yml --profile vector-search up -d
docker compose -p rowset -f docker-compose-prod.yml exec -T backend \
  python manage.py backfill_dataset_vectors --all --dry-run
docker compose -p rowset -f docker-compose-prod.yml exec -T backend \
  python manage.py backfill_dataset_vectors --all --stop-on-error
```

Leave the flag false and use the normal startup command when vector search is not needed.

## Data, backups, and updates

The Compose project stores durable data in named volumes for PostgreSQL, public media, private
media, Caddy, and optional Qdrant. Redis and Qdrant are not canonical user-data stores.

Use your infrastructure provider's encrypted volume snapshots when available. Also take regular
PostgreSQL dumps and copy them off the host:

```bash
umask 077
mkdir -p backups
chmod 700 backups
docker compose -p rowset -f docker-compose-prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/rowset-$(date -u +%Y%m%dT%H%M%SZ).dump"
chmod 600 backups/*.dump
```

If assets use the local `media_data` and `private_media_data` volumes, include those volumes in the
same backup window. If assets use S3-compatible storage, enable bucket versioning and back up that
bucket separately. A backup stored only on the Rowset host is not disaster recovery. Test restores
in an isolated project before relying on them.

Do not run `docker compose down -v`; `-v` deletes the named volumes and user data.

To update, back up first, fetch tags, check out the selected release, update `ROWSET_IMAGE` in
`.env` to the same tag, then pull and recreate the services:

```bash
git fetch --tags
git checkout <new-release-tag>
docker compose -p rowset -f docker-compose-prod.yml pull
docker compose -p rowset -f docker-compose-prod.yml up -d
docker compose -p rowset -f docker-compose-prod.yml ps
```

Rollback uses the same sequence with the previous source tag and image tag. Do not mix a Compose
file from one release with an arbitrary image from another.

## Troubleshooting

Start with service state and bounded logs:

```bash
docker compose -p rowset -f docker-compose-prod.yml ps
docker compose -p rowset -f docker-compose-prod.yml logs --tail=100 caddy backend db redis workers
```

- Certificate failure: confirm DNS points to this server and ports 80/443 are reachable. Do not use
  `curl -k`; it hides the problem.
- Caddy 502: inspect backend, PostgreSQL, and Redis health and logs.
- Configuration failure: run `docker compose -p rowset -f docker-compose-prod.yml config --quiet`
  and correct the named missing variable in `.env`.
- Migration or application failure: inspect backend logs, then run `python manage.py check --deploy`
  through `docker compose exec` as shown above.
- Unsupported host: use a Linux `amd64` or `arm64` server.

Only ports 80 and 443 (plus UDP 443) should be public. Ports 5432, 6379, 6333, and the backend's
internal port must remain private.
