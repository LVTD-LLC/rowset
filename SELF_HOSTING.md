# Self-host Rowset

This is the supported Docker Compose path for a single-server Rowset installation. It runs
PostgreSQL, Redis, the Rowset web process, workers, and Caddy. Caddy is the only public ingress and
manages trusted HTTPS certificates automatically.

## What this path supports

- `linux/amd64` and `linux/arm64` servers
- one public hostname supplied as `ROWSET_DOMAIN`
- automatic HTTPS issuance, renewal, and HTTP-to-HTTPS redirects
- private backend, database, Redis, and worker services
- persistent PostgreSQL, Redis, media, private asset, and Caddy state
- authenticated browser, REST, and Streamable HTTP MCP traffic

This guide intentionally provides one production proxy path. Caddy is not an application
dependency: advanced operators can replace it if their ingress preserves forwarded HTTPS, client
addresses, streaming responses, request sizes, and backend isolation.

## Prerequisites

You need:

- a VPS or dedicated server running Linux on `amd64` or `arm64`
- Docker Engine, Docker Buildx, and Docker Compose v2
- a domain or subdomain whose DNS you control
- SSH access with permission to run Docker
- inbound TCP ports 80 and 443 open; UDP 443 is optional but enables HTTP/3
- an immutable Rowset release or full Git SHA image tag

The examples assume a dedicated Rowset host. If another service already occupies ports 80 or 443,
move it or use your existing ingress instead of starting the included Caddy service.

## 1. Prepare DNS and firewall

Create an A record pointing your hostname to the server's public IPv4 address. Add an AAAA record
only when the server has working public IPv6.

Allow inbound:

- TCP 22 from trusted administration addresses
- TCP 80 from the internet for certificate validation and HTTPS redirects
- TCP 443 from the internet for HTTPS
- UDP 443 from the internet when HTTP/3 is desired

Do not expose ports 5432, 6379, or 8000. The production Compose file publishes only Caddy's web
ports.

Confirm DNS before starting the stack:

```bash
export ROWSET_DOMAIN=rowset.example.com
getent ahosts "$ROWSET_DOMAIN"
```

The returned address must match the server. Certificate issuance cannot succeed until public DNS
and ports 80/443 reach Caddy.

## 2. Fetch Rowset and verify the image

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
cp .env.example .env
```

Choose a release or full Git SHA tag. Do not use a mutable `latest` tag.

```bash
export ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:<release-or-sha-tag>
deployment/verify-image-platforms.sh "$ROWSET_IMAGE"
```

The preflight fails if the image does not publish the current server architecture.

## 3. Configure the environment

Edit `.env` and set at least:

```dotenv
ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:<release-or-sha-tag>
ROWSET_DOMAIN=rowset.example.com
ENVIRONMENT=prod
DEBUG=off
SECRET_KEY=<long-random-value>
POSTGRES_PASSWORD=<long-random-value>
REDIS_PASSWORD=<long-random-value>
```

Generate independent values instead of reusing passwords:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
openssl rand -base64 48
openssl rand -base64 48
```

Compose derives `SITE_URL=https://${ROWSET_DOMAIN}` for the web and worker containers. Do not add a
scheme, path, or port to `ROWSET_DOMAIN` in production. Startup migrations synchronize the Django
Site record from this URL; no admin edit is required.

Review optional email, OAuth, analytics, object-storage, payments, and vector-search settings in
`.env.example`. Leave unused integrations blank. Never commit `.env`.

## 4. Start Rowset with automatic HTTPS

```bash
docker compose -f docker-compose-prod.yml -p rowset up -d --remove-orphans
```

Inspect startup state and logs:

```bash
docker compose -f docker-compose-prod.yml -p rowset ps
docker compose -f docker-compose-prod.yml -p rowset logs --tail=100 caddy backend workers
```

The Rowset image runs migrations during startup. The backend health check also verifies PostgreSQL
and Redis before Caddy treats the application as ready.

Caddy requests a public certificate after it can reach the configured hostname. Initial issuance
normally completes shortly after DNS and firewall prerequisites are correct.

### Lifecycle and local Docker logs

All five services use `restart: unless-stopped`, so containers restart automatically after a Docker
daemon or host restart unless an operator stopped them explicitly. Backend and workers wait for
healthy PostgreSQL and authenticated Redis dependencies during Compose startup; Caddy waits for the
healthy backend.

Docker's local `json-file` logs rotate at three 10 MB files: approximately 30 MB per service and
150 MB across the five-service stack, before small Docker metadata overhead. Application-level
external logging remains separately configurable through optional observability settings.

To validate or share the Compose structure without resolving `.env` values, use:

```bash
docker compose --env-file .env -f docker-compose-prod.yml -p rowset \
  config --no-env-resolution --no-interpolate
```

Do not share `.env`, ordinary fully resolved `docker compose config` output, or container environment
output; all can contain secrets.

## 5. Verify web, REST, and MCP

Verify that HTTP redirects once to HTTPS and that HTTPS is healthy:

```bash
curl -I "http://$ROWSET_DOMAIN"
curl -fsS "https://$ROWSET_DOMAIN/" >/dev/null
```

The HTTP response should redirect to `https://$ROWSET_DOMAIN/`. The HTTPS command must complete
without `--insecure`; using `-k` would hide certificate failures.

Run the authenticated, mutating post-deployment smoke test from the Rowset checkout on the host:

```bash
deployment/self-host/smoke-test.sh
```

The command creates a short-lived temporary user and scoped API key, verifies REST authentication,
initializes MCP, checks live tool discovery, creates a one-row dataset through REST, reads that row
through MCP, and waits for a real worker task. It removes the worker result, dataset, key, profile,
and user on both success and failure. The raw key stays in command memory and is never passed as an
argument or printed.

`smoke-test.sh` uses `docker-compose-prod.yml`, the `rowset` Compose project, and the container's
`SITE_URL` by default. Pass management-command options after the script when needed:

```bash
deployment/self-host/smoke-test.sh --base-url "https://$ROWSET_DOMAIN" --timeout 60
```

For credential safety, `--base-url` must match the configured HTTPS `SITE_URL` origin. HTTP is
accepted only for loopback and the internal `backend` service during local deployment checks.

Use `--fail-after` with one of `setup`, `rest_auth`, `mcp_initialize`, `mcp_tools`,
`dataset_create`, `dataset_read`, or `worker` to verify cleanup after a deliberate failure. This
command mutates temporary data and is intended for install completion, deployment verification,
and CI. Keep ordinary load-balancer and uptime checks on the non-mutating health endpoint.

Create an account in the browser, create a scoped agent API key in Settings, and store it only in a
private shell or secret store:

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

Discover the live tool schemas, then call `get_user_info`, `get_rowset_capabilities`, and
`get_all_datasets`. Do not put the raw API key in MCP configuration or logs.

## Certificate renewal and Caddy state

Caddy obtains certificates, renews them in the background, and serves HTTP-to-HTTPS redirects
without a separate certificate client or host-level timer. The named volumes are:

- `caddy_data`: certificates, private keys, and other durable Caddy state
- `caddy_config`: autosaved Caddy configuration state

Check certificate maintenance and renewal activity with:

```bash
docker compose -f docker-compose-prod.yml -p rowset logs caddy
docker compose -f docker-compose-prod.yml -p rowset exec caddy caddy list-modules >/dev/null
```

Normal `up -d` and container recreation preserve these volumes. Never run `docker compose down -v`
as an update command: it deletes Caddy state along with Rowset's database, Redis, and media data.

## Persistent data and backups

The production stack uses these named volumes:

- `postgres_data`
- `redis_data`
- `media_data`
- `private_media_data`
- `caddy_data`
- `caddy_config`

Back up public and private local media with:

```bash
deployment/self-host/backup-local-media.sh /var/backups/rowset
```

The script writes a permission-restricted archive and checksum. It does not back up PostgreSQL.
Create a database dump separately:

```bash
umask 077
docker compose -f docker-compose-prod.yml -p rowset exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "/var/backups/rowset/rowset-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

Copy database and media backups off the server. A backup stored only on the Rowset host does not
protect against disk or server loss.

When `ROWSET_ASSET_S3_ENDPOINT_URL` is configured, private dataset image and audio assets live in
the object store instead of `private_media_data`. Follow the provider's versioning and backup
guidance as well.

## Updates

Read the release notes, choose a new immutable image tag, and verify its platform before changing
`.env`:

```bash
export ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:<new-release-or-sha-tag>
deployment/verify-image-platforms.sh "$ROWSET_IMAGE"
docker compose -f docker-compose-prod.yml -p rowset pull
docker compose -f docker-compose-prod.yml -p rowset up -d --remove-orphans
docker compose -f docker-compose-prod.yml -p rowset ps
```

Back up PostgreSQL and local media before updates. Do not add `-v` to `down` commands.

## Temporary insecure IP-only diagnostic mode

This mode is only for diagnosing container startup before a hostname is available. It serves plain
HTTP through Caddy and disables Django's production HTTPS enforcement. It is not a production
configuration.

Do not create accounts, API keys, or private datasets in this mode. Do not send credentials over
it. Prefer a disposable DNS hostname that exercises trusted HTTPS whenever possible.

Set `ROWSET_DOMAIN` to the server IP, then load the explicitly insecure override:

```bash
export ROWSET_DOMAIN=203.0.113.10
docker compose -f docker-compose-prod.yml \
  -f deployment/self-host/compose.insecure-http.yml \
  -p rowset up -d --remove-orphans
curl -I "http://$ROWSET_DOMAIN"
```

Traffic still enters through Caddy; backend port 8000 remains closed. Tear this mode down before
normal deployment:

```bash
docker compose -f docker-compose-prod.yml \
  -f deployment/self-host/compose.insecure-http.yml \
  -p rowset down
```

Then configure DNS, restore `ROWSET_DOMAIN` to the hostname, and start only
`docker-compose-prod.yml`.

## Troubleshooting

### Caddy cannot obtain a certificate

Check in this order:

```bash
getent ahosts "$ROWSET_DOMAIN"
sudo ss -lntup | grep -E ':(80|443)\b'
docker compose -f docker-compose-prod.yml -p rowset logs --tail=200 caddy
```

DNS must resolve to this server, ports 80 and 443 must be reachable from the internet, and no other
process can bind those ports. Do not work around certificate errors with `curl -k`.

### Caddy returns 502

```bash
docker compose -f docker-compose-prod.yml -p rowset ps
docker compose -f docker-compose-prod.yml -p rowset logs --tail=200 backend db redis
```

Caddy waits for the backend health check. Resolve database, Redis, migration, or environment
failures reported by the backend.

### Inspect the effective Compose configuration

```bash
docker compose -f docker-compose-prod.yml -p rowset config
```

Review hostnames, image references, ports, mounts, and service dependencies. Do not paste output
containing secrets into public issues or chats.

### Confirm the backend is private

From another host, scan only systems you own or are authorized to test. Ports 80 and 443 should be
reachable; port 8000 should be closed. PostgreSQL and Redis must not be publicly reachable.

## Environment reference

The core self-hosting values are:

| Variable | Purpose |
| --- | --- |
| `ROWSET_IMAGE` | Immutable Rowset release or full Git SHA image reference |
| `ROWSET_DOMAIN` | Public hostname without scheme, path, or port |
| `ENVIRONMENT` | Set to `prod` for the supported production path |
| `DEBUG` | Set to `off` in production |
| `SECRET_KEY` | Long independent Django secret |
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_USER` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Strong PostgreSQL password |
| `REDIS_PASSWORD` | Strong Redis password |

`ROWSET_INSECURE_HTTP` is intentionally absent from `.env.example`; only the diagnostic Compose
override sets it. See `.env.example` and the README environment table for optional integrations.
