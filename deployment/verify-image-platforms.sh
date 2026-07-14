#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 IMAGE [linux/amd64|linux/arm64 ...]" >&2
    exit 2
}

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

if ! docker buildx version >/dev/null 2>&1; then
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

manifest="$(docker buildx imagetools inspect "$image")"

for platform in "$@"; do
    if ! printf '%s\n' "$manifest" | grep -Eq "Platform:[[:space:]]+$platform([[:space:]]|$)"; then
        echo "Image $image does not publish $platform." >&2
        exit 1
    fi

    echo "Verified $image publishes $platform."
done
