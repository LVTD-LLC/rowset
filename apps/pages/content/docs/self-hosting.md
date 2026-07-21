---
title: Self-host Rowset with Docker Compose
description: Deploy Rowset on your own Linux server with the supported production Compose stack.
keywords: self-host Rowset, Docker Compose, private AI agent backend, Rowset deployment
---

# Self-host Rowset with Docker Compose

Use the supported production Compose stack when Rowset must run on infrastructure
you control. This guide gets you to the release-specific deployment instructions
and a verified HTTPS instance without duplicating an operations runbook that may
change between releases.

If you do not want to manage a server, DNS, backups, and upgrades, use the hosted
Rowset service and start with the [quickstart](/docs/quickstart).

## What you manage

The Rowset release provides the application image, production Compose file, and
database migrations. As the operator, you manage:

- the Linux server and firewall;
- DNS and the public hostname;
- secrets and optional integrations;
- backups, monitoring, updates, and recovery; and
- access to the Rowset accounts and agent API keys created on your instance.

PostgreSQL is the source of truth for Rowset data. Do not expose PostgreSQL,
Redis, Qdrant, or the Rowset backend directly to the internet. Caddy should be
the only public service.

## Before you begin

You need:

- a Linux server with an `amd64` or `arm64` CPU, at least 4 GB RAM, and 25 GB disk;
- Git, OpenSSL, Docker Engine, and Docker Compose v2.23 or newer;
- a hostname with an `A` or `AAAA` record pointing to the server; and
- inbound TCP ports 80 and 443, plus UDP 443, open in the firewall.

Run the deployment as a user allowed to use Docker.

## 1. Check out a stable release

Clone Rowset and check out the newest dated release:

```bash
git clone https://github.com/LVTD-LLC/rowset.git
cd rowset
ROWSET_VERSION="$(git tag --list '20*' --sort=-version:refname | head -n 1)"
test -n "$ROWSET_VERSION"
git checkout "$ROWSET_VERSION"
```

Keep the checked-out source tag and the `ROWSET_IMAGE` tag identical. This makes
updates and rollbacks predictable.

## 2. Follow the release guide

Open `SELF_HOSTING.md` from the release you checked out:

```bash
less SELF_HOSTING.md
```

That file is the deployment runbook for the release. It includes the complete
`.env` template, local secret generation, optional integrations, backup guidance,
updates, rollbacks, and troubleshooting. Use that checked-out copy instead of a
guide from another release or the `main` branch.

Never commit `.env`, paste it into chat, or share a fully interpolated Compose
configuration.

## 3. Validate and start the stack

After creating `.env` as described in the release guide, validate the Compose
model before starting services:

```bash
docker compose -p rowset -f docker-compose-prod.yml config --quiet
```

Then pull and start the release:

```bash
docker compose -p rowset -f docker-compose-prod.yml pull
docker compose -p rowset -f docker-compose-prod.yml up -d
docker compose -p rowset -f docker-compose-prod.yml ps
```

The baseline stack runs Caddy, PostgreSQL, Redis, the Rowset web process, and
Rowset workers. Caddy obtains and renews the HTTPS certificate after DNS and the
firewall are configured correctly.

## 4. Verify the deployment

Run the production checks and confirm HTTPS works without bypassing certificate
validation:

```bash
docker compose -p rowset -f docker-compose-prod.yml exec -T backend \
  python manage.py check --deploy
curl -fsS "https://$ROWSET_DOMAIN/" >/dev/null
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  "https://$ROWSET_DOMAIN/api/user")" = "401"
```

The `401` response confirms that the private API rejects anonymous requests.

Create an account on the instance, create an agent API key in Settings, and
verify authenticated access:

```bash
export ROWSET_API_KEY="YOUR_ROWSET_API_KEY"
curl -fsS "https://$ROWSET_DOMAIN/api/user" \
  -H "Authorization: Bearer $ROWSET_API_KEY"
```

Store the API key in a private environment variable or secret store. Do not put
the raw key in agent configuration, logs, screenshots, or repositories.

## Give the deployment to a trusted agent

You can copy this prompt into an agent that has terminal access to the server:

```text
Deploy the newest stable Rowset release on this Linux server. Use SELF_HOSTING.md
from the checked-out release as the only deployment runbook. Before changing the
server, verify the CPU architecture, RAM, disk, Docker Compose version, DNS, and
firewall requirements and report any blocker. Generate secrets locally without
printing them. Do not expose private services, print .env, or run destructive
volume commands. After startup, verify service health, trusted HTTPS, anonymous
API rejection, and authenticated API access. Stop and ask me before deleting
data, replacing an existing deployment, or changing DNS or firewall rules.
```

Supply the hostname and credentials through the agent runtime's private secret
mechanism, not in the prompt.

## Back up before updates

Back up PostgreSQL and any locally stored media in the same backup window, copy
the backups off the Rowset server, and test restores in an isolated environment.
A backup stored only on the server is not disaster recovery.

Do not run `docker compose down -v`. The `-v` option deletes named volumes and
can permanently remove user data.

For updates and rollbacks, use the sequence in the checked-out release's
`SELF_HOSTING.md`. Do not combine a Compose file from one release with an image
from another.

## Next steps

- [Connect over MCP](/docs/connect-mcp) using `https://<your-hostname>/mcp/`.
- [Use Rowset from the CLI](/docs/use-cli) with your instance's `/api/` base URL.
- [Start with your first agent dataset](/docs/quickstart).
- [Learn how Rowset access paths differ](/docs/core-concepts).
