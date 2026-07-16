#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 [--manifest-file FILE] IMAGE [linux/amd64|linux/arm64 ...]" >&2
    exit 2
}

manifest_file=""
if [ "${1:-}" = "--manifest-file" ]; then
    [ "$#" -ge 3 ] || usage
    manifest_file="$2"
    shift 2
fi

[ "$#" -ge 1 ] || usage
image="$1"
shift

if [ "$#" -eq 0 ]; then
    host_arch="$(uname -m)"
    case "$host_arch" in
        x86_64|amd64) set -- linux/amd64 ;;
        aarch64|arm64) set -- linux/arm64 ;;
        *)
            echo "Unsupported host architecture: $host_arch" >&2
            exit 1
            ;;
    esac
fi

if [ -z "$manifest_file" ] && ! docker buildx version >/dev/null 2>&1; then
    echo "Docker Buildx is required to inspect image platforms." >&2
    exit 1
fi

for platform in "$@"; do
    case "$platform" in
        linux/amd64|linux/arm64) ;;
        *)
            echo "Unsupported Rowset image platform: $platform" >&2
            exit 1
            ;;
    esac
done

if [ -n "$manifest_file" ]; then
    if ! manifest="$(cat "$manifest_file")"; then
        echo "Could not read image manifest from $manifest_file." >&2
        exit 1
    fi
else
    manifest="$(docker buildx imagetools inspect "$image")"
fi

for platform in "$@"; do
    if ! printf '%s\n' "$manifest" | grep -Eq "Platform:[[:space:]]+$platform([[:space:]]|$)"; then
        echo "Image $image does not publish $platform." >&2
        exit 1
    fi

    echo "Verified $image publishes $platform."
done
