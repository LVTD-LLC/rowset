#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
requirements_file="$script_dir/requirements.json"
compose_file="$root/docker-compose-prod.yml"
insecure_compose_file="$script_dir/compose.insecure-http.yml"
project_name=rowset-benchmark

usage() {
    printf 'Usage: %s IMAGE:FULL_GIT_SHA OUTPUT.json\n' "$0" >&2
    exit 2
}

test "$#" -eq 2 || usage
image=$1
output=$2
image_tag=${image##*:}
printf '%s\n' "$image_tag" | grep -Eq '^[0-9a-f]{40}$' || {
    printf 'IMAGE must use an immutable full Git SHA tag.\n' >&2
    exit 2
}

for command in docker python3 curl openssl timeout; do
    command -v "$command" >/dev/null 2>&1 || {
        printf 'Missing required command: %s\n' "$command" >&2
        exit 2
    }
done
docker compose version >/dev/null
docker buildx version >/dev/null 2>&1 || {
    printf 'Docker Buildx is required to inspect image platforms.\n' >&2
    exit 2
}

case "$(uname -m)" in
    x86_64 | amd64) platform=linux/amd64 ;;
    aarch64 | arm64) platform=linux/arm64 ;;
    *) printf 'Unsupported host architecture: %s\n' "$(uname -m)" >&2; exit 1 ;;
esac

os_id=$(. /etc/os-release && printf '%s' "$ID")
os_version=$(. /etc/os-release && printf '%s' "$VERSION_ID")
cpu_cores=$(getconf _NPROCESSORS_ONLN)
if cpu_max=$(cat /sys/fs/cgroup/cpu.max 2>/dev/null); then
    cpu_quota=${cpu_max%% *}
    cpu_period=${cpu_max##* }
    if test "$cpu_quota" != max; then
        cgroup_cpu_cores=$((cpu_quota / cpu_period))
        test "$cgroup_cpu_cores" -ge 1 || cgroup_cpu_cores=1
        test "$cgroup_cpu_cores" -ge "$cpu_cores" || cpu_cores=$cgroup_cpu_cores
    fi
fi
memory_bytes=$(awk '/^MemTotal:/ { printf "%.0f", $2 * 1024 }' /proc/meminfo)
if cgroup_memory_bytes=$(cat /sys/fs/cgroup/memory.max 2>/dev/null); then
    case "$cgroup_memory_bytes" in
        '' | max) ;;
        *) test "$cgroup_memory_bytes" -ge "$memory_bytes" || memory_bytes=$cgroup_memory_bytes ;;
    esac
fi
docker_root=$(docker info --format '{{.DockerRootDir}}')
disk_path=${ROWSET_BENCHMARK_DISK_PATH:-$docker_root}
disk_bytes=${ROWSET_BENCHMARK_DISK_BYTES:-$(df -B1 --output=size "$disk_path" | awk 'NR == 2 { print $1 }')}
health_timeout=$(python3 "$script_dir/check-requirements.py" "$requirements_file" \
    --platform "$platform" --os-id "$os_id" --os-version "$os_version" \
    --cpu-cores "$cpu_cores" --memory-bytes "$memory_bytes" --disk-bytes "$disk_bytes")

if docker ps -aq --filter "label=com.docker.compose.project=$project_name" | grep -q . || \
    docker volume ls -q --filter "label=com.docker.compose.project=$project_name" | grep -q . || \
    docker network ls -q --filter "label=com.docker.compose.project=$project_name" | grep -q .; then
    printf 'Refusing to benchmark over an existing %s Compose project.\n' "$project_name" >&2
    exit 1
fi

environment_file=$(mktemp "${TMPDIR:-/tmp}/rowset-benchmark.XXXXXX")
manifest_file=$(mktemp "${TMPDIR:-/tmp}/rowset-benchmark-manifest.XXXXXX")
compose() {
    docker compose --env-file "$environment_file" -p "$project_name" -f "$compose_file" \
        -f "$insecure_compose_file" "$@"
}
cleanup() {
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "$environment_file"
    rm -f "$manifest_file"
}
trap cleanup EXIT HUP INT TERM

ROWSET_IMAGE=$image ROWSET_DOMAIN=benchmark.invalid \
    "$script_dir/init-env.sh" "$environment_file" >/dev/null
export ROWSET_ENV_FILE=$environment_file

docker buildx imagetools inspect "$image" > "$manifest_file"
"$root/deployment/verify-image-platforms.sh" --manifest-file "$manifest_file" \
    "$image" "$platform" >/dev/null
image_digest=$(awk '/^Digest:/ { print $2; exit }' "$manifest_file")
printf '%s\n' "$image_digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || {
    printf 'Could not resolve an OCI index digest for %s.\n' "$image" >&2
    exit 1
}
image_indexes=$(
    compose config --images | sort -u | while IFS= read -r reference; do
        digest=$(docker buildx imagetools inspect "$reference" | \
            awk '/^Digest:/ { print $2; exit }')
        printf '%s\t%s\n' "$reference" "$digest"
    done | python3 -c '
import json
import re
import sys

images = []
for line in sys.stdin:
    reference, digest = line.rstrip("\n").split("\t", 1)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"Could not resolve an OCI index digest for {reference}")
    images.append({"reference": reference, "digest": digest})
print(json.dumps(images))
'
)
disk_used_before_pull=$(df -B1 --output=used "$disk_path" | awk 'NR == 2 { print $1 }')
pull_started=$(date +%s)
timeout "${ROWSET_BENCHMARK_PULL_TIMEOUT_SECONDS:-1800}" docker compose \
    --env-file "$environment_file" -p "$project_name" -f "$compose_file" \
    -f "$insecure_compose_file" pull --quiet
pull_seconds=$(($(date +%s) - pull_started))

image_logical_bytes=$(
    compose config --images | sort -u | \
        xargs docker image inspect --format '{{.Size}}' | awk '{ total += $1 } END { print total }'
)

started=$(date +%s)
startup_deadline=$((started + health_timeout))
timeout "$health_timeout" docker compose --env-file "$environment_file" -p "$project_name" \
    -f "$compose_file" -f "$insecure_compose_file" up -d --remove-orphans >/dev/null
while :; do
    remaining=$((startup_deadline - $(date +%s)))
    if test "$remaining" -le 0; then
        compose ps >&2
        compose logs --tail=100 backend workers caddy >&2
        printf 'Rowset did not become healthy within %s seconds.\n' "$health_timeout" >&2
        exit 1
    fi
    curl_timeout=$remaining
    test "$curl_timeout" -le 5 || curl_timeout=5
    if curl --connect-timeout 2 --max-time "$curl_timeout" -fsS \
        -H 'Host: benchmark.invalid' http://127.0.0.1/ >/dev/null 2>&1; then
        break
    fi
    test "$remaining" -le 1 || sleep 1
done
cold_start_seconds=$(($(date +%s) - started))
sleep 10

for service in $(compose config --services); do
    container_ids=$(compose ps -aq "$service")
    container_count=0
    for container_id in $container_ids; do
        container_count=$((container_count + 1))
    done
    if test "$container_count" -ne 1 || \
        test "$(docker inspect --format '{{.State.Running}}' "$container_ids")" != true; then
        compose ps >&2
        printf 'Required service %s does not have exactly one running container.\n' \
            "$service" >&2
        exit 1
    fi
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
        "$container_ids")
    restarts=$(docker inspect --format '{{.RestartCount}}' "$container_ids")
    if { test -n "$health" && test "$health" != healthy; } || test "$restarts" -ne 0; then
        compose ps >&2
        printf 'Required service %s is unhealthy or restarted during startup.\n' \
            "$service" >&2
        exit 1
    fi
done

memory_usage=$(compose ps -q | xargs docker stats --no-stream --format '{{.MemUsage}}')
steady_state_memory_bytes=$(printf '%s\n' "$memory_usage" | python3 -c '
import re
import sys

units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
total = 0
for line in sys.stdin:
    value = line.split("/", 1)[0].strip()
    match = re.fullmatch(r"([0-9.]+)(B|KiB|MiB|GiB)", value)
    if not match:
        raise SystemExit(f"Unsupported Docker memory value: {value}")
    total += int(float(match.group(1)) * units[match.group(2)])
print(total)
')
disk_used_after_start=$(df -B1 --output=used "$disk_path" | awk 'NR == 2 { print $1 }')
disk_delta_bytes=$((disk_used_after_start - disk_used_before_pull))
available_memory_bytes=$(awk '/^MemAvailable:/ { printf "%.0f", $2 * 1024 }' /proc/meminfo)
cgroup_available_bytes=$((memory_bytes - steady_state_memory_bytes))
test "$cgroup_available_bytes" -ge "$available_memory_bytes" || \
    available_memory_bytes=$cgroup_available_bytes
source_revision=${ROWSET_BENCHMARK_SOURCE_REVISION:-$(
    git -C "$root" rev-parse HEAD 2>/dev/null || printf unknown
)}
provider=${ROWSET_BENCHMARK_PROVIDER:-unknown}
server_type=${ROWSET_BENCHMARK_SERVER_TYPE:-unknown}
benchmark_run_id=${ROWSET_BENCHMARK_RUN_ID:-$image_tag}
docker_version=$(docker version --format '{{.Server.Version}}')
measured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
services=$(compose config --services | sort | python3 -c '
import json
import sys

print(json.dumps([line.strip() for line in sys.stdin if line.strip()]))
')

python3 - "$output" \
    --platform "$platform" \
    --os-id "$os_id" \
    --os-version "$os_version" \
    --cpu-cores "$cpu_cores" \
    --memory-bytes "$memory_bytes" \
    --disk-bytes "$disk_bytes" \
    --provider "$provider" \
    --server-type "$server_type" \
    --benchmark-run-id "$benchmark_run_id" \
    --image-reference "$image" \
    --image-digest "$image_digest" \
    --image-indexes "$image_indexes" \
    --source-revision "$source_revision" \
    --docker-version "$docker_version" \
    --pull-seconds "$pull_seconds" \
    --cold-start-seconds "$cold_start_seconds" \
    --image-logical-bytes "$image_logical_bytes" \
    --disk-delta-bytes "$disk_delta_bytes" \
    --steady-state-memory-bytes "$steady_state_memory_bytes" \
    --available-memory-bytes "$available_memory_bytes" \
    --measured-at "$measured_at" \
    --services "$services" <<'PY'
import argparse
import json
import sys

output = sys.argv[1]
parser = argparse.ArgumentParser()
parser.add_argument("--platform", required=True)
parser.add_argument("--os-id", required=True)
parser.add_argument("--os-version", required=True)
parser.add_argument("--cpu-cores", type=int, required=True)
parser.add_argument("--memory-bytes", type=int, required=True)
parser.add_argument("--disk-bytes", type=int, required=True)
parser.add_argument("--provider", required=True)
parser.add_argument("--server-type", required=True)
parser.add_argument("--benchmark-run-id", required=True)
parser.add_argument("--image-reference", required=True)
parser.add_argument("--image-digest", required=True)
parser.add_argument("--image-indexes", type=json.loads, required=True)
parser.add_argument("--source-revision", required=True)
parser.add_argument("--docker-version", required=True)
parser.add_argument("--pull-seconds", type=int, required=True)
parser.add_argument("--cold-start-seconds", type=int, required=True)
parser.add_argument("--image-logical-bytes", type=int, required=True)
parser.add_argument("--disk-delta-bytes", type=int, required=True)
parser.add_argument("--steady-state-memory-bytes", type=int, required=True)
parser.add_argument("--available-memory-bytes", type=int, required=True)
parser.add_argument("--measured-at", required=True)
parser.add_argument("--services", type=json.loads, required=True)
args = parser.parse_args(sys.argv[2:])
document = {
    "schema_version": 1,
    "benchmark_run_id": args.benchmark_run_id,
    "measured_at": args.measured_at,
    "platform": args.platform,
    "operating_system": {"id": args.os_id, "version": args.os_version},
    "host": {
        "provider": args.provider,
        "server_type": args.server_type,
        "cpu_cores": args.cpu_cores,
        "memory_bytes": args.memory_bytes,
        "disk_bytes": args.disk_bytes,
    },
    "image_reference": args.image_reference,
    "image_digest": args.image_digest,
    "image_indexes": args.image_indexes,
    "source_revision": args.source_revision,
    "docker_version": args.docker_version,
    "services": args.services,
    "measurements": {
        "image_pull_seconds": args.pull_seconds,
        "cold_start_seconds": args.cold_start_seconds,
        "image_logical_bytes": args.image_logical_bytes,
        "disk_delta_bytes": args.disk_delta_bytes,
        "steady_state_memory_bytes": args.steady_state_memory_bytes,
        "available_memory_after_start_bytes": args.available_memory_bytes,
    },
}
with open(output, "w", encoding="utf-8") as stream:
    json.dump(document, stream, indent=2)
    stream.write("\n")
PY

printf 'Benchmark written to %s\n' "$output"
