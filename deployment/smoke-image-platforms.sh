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
    set -- linux/amd64 linux/arm64
fi

for platform in "$@"; do
    case "$platform" in
        linux/amd64) expected_machine=x86_64 ;;
        linux/arm64) expected_machine=aarch64 ;;
        *)
            echo "Unsupported Rowset image platform: $platform" >&2
            exit 1
            ;;
    esac

    docker run \
        --rm \
        --platform "$platform" \
        --entrypoint /opt/venv/bin/python \
        "$image" \
        -m deployment.platform_smoke \
        "$expected_machine"

    echo "Executed Rowset on $platform."
done
