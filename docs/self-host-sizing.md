# Rowset self-host sizing

These requirements cover the supported single-host Docker Compose stack: Caddy, PostgreSQL, Redis,
the Rowset web process, and workers. They are deliberately conservative for a new, lightly used
installation. Dataset size, local assets, request volume, and retention eventually matter more than
the empty-stack baseline.

## Profiles

| Profile | CPU | RAM class | Disk class | Use it for |
| --- | ---: | ---: | ---: | --- |
| Minimum | 2 vCPU | 4 GB | 40 GB | Evaluation and low-traffic installations with active capacity monitoring |
| Tested | 2 vCPU | 4 GB | 40 GB | The amd64 and arm64 clean-start benchmarks below |
| Recommended | 4 vCPU | 8 GB | 80 GB | Small production teams, safer updates, and useful growth headroom |

Minimum and tested are intentionally the same. We have not validated a smaller host and do not
publish one as supported. Provider kernels report slightly less than advertised capacity, so the
machine thresholds are 3.75 billion RAM bytes and 38 billion disk bytes for a nominal 4 GB / 40 GB
host. The recommended machine thresholds similarly allow normal provider and filesystem overhead
on an 8 GB / 80 GB host.

`deployment/self-host/requirements.json` is the source of truth for automation. It contains the
minimum, tested, and recommended profiles, supported OS versions and architectures, and the startup
timeout. The future preflight command should read that file rather than copy these values into shell
code.

## Supported platform

The tested operating system is Ubuntu 24.04 on `linux/amd64` and `linux/arm64`. The benchmark booted
every required Compose image, not only the Rowset image. The Rowset OCI index and the Caddy, Redis,
and PostgreSQL images therefore all resolved and ran on both architectures.

Other Linux distributions may work, but they are not in the checked-in support contract until the
same benchmark passes there. Do not infer support from Docker availability alone.

## July 2026 benchmark

Both runs used the full five-service stack and immutable Rowset image tag
`86e4f5c600c861391d6b6e0882a875d675aaea28`, whose OCI index digest was
`sha256:45e6b83055f9ebd5b8a8cabdd86d09b82e1e4b7f7728e2bb7022d86b166639ea`.
The startup clock began after all image pulls completed and stopped when HTTP through Caddy was
healthy. Memory was sampled ten seconds later.

| Platform and host | Pull | Cold start | Logical images | New disk use | Steady container RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| amd64, Hetzner CX23, 2 vCPU / 4 GB / 40 GB | 53 s | 60 s | 1.18 GB | 5.08 GB | 1.93 GB |
| arm64, native Ubuntu VM, 2 vCPU / 4 GB / 40 GB | 537 s | 28 s | 1.13 GB | 4.96 GB | 1.75 GB |

The arm64 pull ran through a constrained local VM network, so its pull duration is not a hosting
expectation. Pull time remains separate from startup because registry and network speed dominate it.
The checked-in 180-second health window is three times the slower observed cold start and covers
migrations, dependency health checks, and ordinary shared-CPU variance. An early 502 during first
startup is not a final failure; keep checking health until that bounded window expires.

Raw evidence is checked in under `docs/benchmarks/self-hosting/`. Reproduce it only on a disposable,
otherwise clean host because the command creates and removes a dedicated Compose project and its
volumes:

```bash
deployment/self-host/benchmark.sh \
  ghcr.io/lvtd-llc/rowset:<full-git-sha> \
  benchmark.json
```

The host needs Docker Engine, Compose v2, Buildx, Python 3, curl, OpenSSL, and `timeout`. The command
requires an immutable full-Git-SHA image tag, checks the host against
`deployment/self-host/requirements.json`, verifies its platform in the OCI index, and emits JSON.

## Capacity planning

- **PostgreSQL:** Row data, indexes, temporary query space, and vacuum headroom grow independently of
  the empty stack. Alert on disk use and plan a larger disk before sustained usage approaches 70%.
- **local assets:** `media_data` and `private_media_data` share the host disk. Prefer object storage
  for large image or audio collections, or budget their retained size separately.
- **backups:** keep PostgreSQL dumps and media archives off-host. If a local staging copy is required,
  reserve room for at least one full database dump plus one full local-media archive.
- **image layers:** a clean install added about 5 GB. Updates can temporarily retain old and new
  layers, so reserve at least twice the measured footprint before pulling a release.
- **log rotation:** Compose caps each of five services at three 10 MB files, approximately 150 MB
  total before small Docker metadata overhead. External application logs need their own retention.

The 8 GB / 80 GB recommendation is the safer default when future database, local asset, backup, or
update-layer growth is unknown. More disk does not replace off-host backups or monitoring.
