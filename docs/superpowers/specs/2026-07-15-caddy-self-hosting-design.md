# Caddy Self-Hosting Design

## Goal

Make the repository's Docker Compose path a reusable, provider-neutral way to deploy Rowset with
trusted HTTPS. A user with a VPS and a domain should supply one normal networking input,
`ROWSET_DOMAIN`, then start the checked-in stack without choosing a proxy, installing certificate
tools on the host, or exposing the Django backend directly.

This design delivers SH-004, SH-005, and SH-010 together because their ingress isolation, Django
security settings, and reverse-proxy behavior form one deployment boundary.

## User Journey

The supported production path is:

1. Clone the Rowset repository on a server with Docker Compose.
2. Copy the self-host environment example and fill in application secrets, storage settings, an
   immutable Rowset image reference, and `ROWSET_DOMAIN=rowset.example.com`.
3. Point the domain's A and/or AAAA records to the server and allow inbound TCP 80 and 443.
4. Start the checked-in production Compose stack with the documented command.
5. Wait for the services to become healthy, then verify the public HTTPS health, REST, and MCP
   endpoints with the documented smoke commands.

Caddy obtains and renews the certificate after deployment because certificate authorities must
validate the live domain. Certificate and Caddy configuration state persist in named volumes, so
container replacement does not discard TLS state.

## Chosen Architecture

The production Compose stack owns Caddy alongside PostgreSQL, Redis, the Rowset backend, and
workers. Caddy is the only service with host port mappings. It publishes TCP 80 and TCP/UDP 443;
the backend exposes its HTTP port only to the internal Compose network.

The request path is:

```text
browser / REST client / MCP client
  -> Caddy on 80 or 443
  -> automatic HTTP-to-HTTPS redirect or TLS termination
  -> backend:80 on the private Compose network
  -> Django / FastMCP
```

`ROWSET_DOMAIN` is the only normal networking input. Compose passes that value to Caddy and derives
`SITE_URL=https://${ROWSET_DOMAIN}` for the backend and workers. This avoids asking operators to
keep separate domain, allowed-host, CSRF-origin, and public-URL settings synchronized. Existing
application settings continue deriving the host and trusted origin from `SITE_URL`.

The Caddy service uses the official image, a checked-in Caddyfile, an automatic restart policy,
and named `/data` and `/config` volumes. The Caddyfile uses an environment-substituted site address
and proxies to the Compose service name rather than localhost.

## Caddy Behavior

The checked-in Caddyfile will provide only Rowset's required ingress behavior:

- automatic public certificate issuance and renewal for `ROWSET_DOMAIN`
- automatic HTTP-to-HTTPS redirects
- reverse proxying to `backend:80`
- forwarded host, client-address, and request-scheme information using Caddy's standard proxy
  behavior
- immediate response flushing for the Streamable HTTP MCP endpoint so long-running responses are
  not accumulated by the proxy
- a request-body ceiling large enough for the largest supported Rowset asset after base64 and JSON
  encoding overhead
- bounded, useful access logging without request bodies, authorization headers, cookies, or other
  secrets

The body ceiling will be derived from Rowset's documented 32 MB audio limit. It must accept that
payload through MCP's base64 JSON representation, while still rejecting unexpectedly large
requests at the ingress boundary.

No DNS-provider plugin, wildcard certificate, on-demand TLS, cloud load balancer, or host-installed
certificate client is part of the default. Standard public DNS plus ports 80 and 443 keeps the
path portable across ordinary VPS providers.

## Django Production Security

When `ENVIRONMENT=prod`, Rowset will:

- trust the proxy's `X-Forwarded-Proto: https` signal through
  `SECURE_PROXY_SSL_HEADER`
- mark session and CSRF cookies Secure
- redirect requests Django still perceives as HTTP
- emit a deliberate HSTS policy
- retain the `SITE_URL`-derived allowed host and CSRF trusted origin

Caddy and Django may both enforce HTTPS, but correctly forwarded HTTPS requests must be recognized
as secure by Django, preventing redirect loops. Local development remains HTTP-capable because the
secure settings are conditional on production mode.

The deployment must pass Django's deployment checks without warnings attributable to proxy HTTPS,
secure cookies, HTTPS redirects, or HSTS.

## Explicit IP-Only Diagnostic Mode

An IP-only path exists only as a temporary deployment diagnostic. It is implemented as a separate,
prominently named Compose override and a separate documented command. The override makes the Caddy
site address explicitly `http://<server-ip>` and disables Django's production-only HTTPS behavior
for that run.

The normal production command never loads this override. The documentation labels it insecure,
forbids accounts or private datasets, and directs the operator to remove it after confirming basic
container and network health. Direct backend port access is not restored in diagnostic mode;
traffic still passes through Caddy, preserving the same container topology.

A disposable DNS name such as an sslip.io-style hostname is the preferred pre-production test
because it exercises the real trusted-certificate path.

## Replaceability and Scope

Caddy is the one supported golden-path proxy, not an application dependency. Advanced operators
may replace the Caddy service with a load balancer or another reverse proxy if they preserve the
same boundary contract:

- backend traffic remains private
- the public proxy sends the original host, client address, and HTTPS scheme
- Streamable HTTP responses are not buffered or cut off
- the supported request size reaches Django
- public HTTP redirects to HTTPS

Alternative-proxy tutorials and compatibility configuration are outside this change. The existing
Nginx, Certbot, generic-proxy, and direct-port production instructions will be removed rather than
maintained as competing golden paths.

## Documentation Shape

`SELF_HOSTING.md` becomes the canonical Compose deployment guide and describes one production
sequence: prepare DNS, configure the environment, start the stack, inspect health and logs, and run
HTTPS/REST/MCP smoke checks. It also explains automatic renewal, persistent Caddy volumes, firewall
ports, updates, and the isolated HTTP diagnostic override.

`README.md` will point to that guide instead of presenting multiple proxy choices or advertising
port 8000 as the production ingress. Environment examples will distinguish local `SITE_URL` from
self-hosted `ROWSET_DOMAIN` so local Docker development remains unchanged.

## Testing Strategy

Fast repository-level tests will parse Compose and inspect the Caddyfile to prove:

- Caddy is the only service publishing public web ports
- backend, database, Redis, and workers have no public host ports
- Caddy has persistent data/config volumes and reaches the backend by service name
- production derives HTTPS `SITE_URL` from required `ROWSET_DOMAIN`
- the Caddyfile activates the domain, reverse proxy, streaming flush, and bounded upload behavior
- the HTTP diagnostic override is separate and explicit

Django settings tests will load production-like configuration and prove proxy HTTPS recognition,
secure cookies, SSL redirect, HSTS, allowed-host behavior, and unchanged development defaults.
Request tests will exercise a normal full-page request and an HTMX request with forwarded HTTPS to
confirm that the server-rendered application and CSRF/security middleware retain their existing
behavior.

Verification will proceed from fast structural/settings tests to Docker-backed focused tests, then
Compose config validation and a production-like container smoke run. Where a disposable public
hostname is available, the final operational check will inspect the trusted certificate and
headers, verify one HTTP-to-HTTPS redirect, call MCP initialize and tools/list, exercise a
long-lived MCP request, and upload the maximum supported asset size. Renewal evidence comes from
Caddy's persisted certificate state and logs; Caddy performs renewal internally rather than
through a separate Certbot dry-run command.

## Failure Handling and Operational Guardrails

- Compose fails interpolation when `ROWSET_DOMAIN` or the immutable Rowset image reference is
  missing.
- Caddy remains unhealthy or logs certificate errors when DNS or firewall prerequisites are not
  satisfied; the guide provides a short diagnostic order covering DNS, ports, container logs, and
  effective Compose configuration.
- TLS state is never stored in the image or repository and must not be removed during ordinary
  updates.
- Deployment examples never include API keys, OAuth secrets, private dataset contents, or real
  credentials.
- Operators are warned that `docker compose down -v` deletes database, media, Redis, and Caddy
  state.

## Rowset Task Tracking

SH-004, SH-005, and SH-010 move to `Doing` when implementation begins. They move to `Done` only
after their combined acceptance criteria have verified evidence. If public-domain validation is
unavailable in the implementation environment, the rows remain in `Review` with the exact remote
smoke checks recorded rather than claiming certificate issuance was observed.

## References

- [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Running Caddy in Docker](https://caddyserver.com/docs/running)
- [Caddyfile environment variables](https://caddyserver.com/docs/caddyfile/concepts#environment-variables)
- `AGENTS.md`
- `PRODUCT.md`
- `TECH.md`
- `STRUCTURE.md`
- `SELF_HOSTING.md`
- SH-004, SH-005, and SH-010 in the Rowset Self-Hosting Path dataset
