#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 EXPECTED_DIGEST IMAGE [IMAGE ...]" >&2
    exit 2
}

[ "$#" -ge 2 ] || usage

expected_digest="$1"
shift

case "$expected_digest" in
    sha256:*) ;;
    *)
        echo "Expected digest must use the sha256:<digest> form." >&2
        exit 2
        ;;
esac

# Remove the workflow login, then force every remaining Docker command to use
# a new config with no credential helpers or cached registry authentication.
original_docker_config="${DOCKER_CONFIG:-$HOME/.docker}"
if ! docker logout ghcr.io >/dev/null 2>&1; then
    echo "Could not remove the GHCR login; refusing to run an anonymous release check." >&2
    exit 1
fi
anonymous_config="$(mktemp -d)"
trap 'rm -rf "$anonymous_config"' EXIT HUP INT TERM
printf '{"auths":{}}\n' > "$anonymous_config/config.json"
if [ -d "$original_docker_config/cli-plugins" ]; then
    ln -s "$original_docker_config/cli-plugins" "$anonymous_config/cli-plugins"
fi
export DOCKER_CONFIG="$anonymous_config"

if ! docker buildx version >/dev/null 2>&1; then
    echo "Docker Buildx is required to verify anonymous image availability." >&2
    exit 1
fi

for image in "$@"; do
    if ! manifest="$(docker buildx imagetools inspect "$image" 2>&1)"; then
        echo "Image $image is not anonymously inspectable." >&2
        echo "Change the GHCR package visibility to public before promoting this release." >&2
        printf '%s\n' "$manifest" >&2
        exit 1
    fi

    resolved_digest="$(printf '%s\n' "$manifest" | awk '$1 == "Digest:" { print $2; exit }')"
    if [ -z "$resolved_digest" ]; then
        echo "Could not determine the registry digest for $image." >&2
        exit 1
    fi
    if [ "$resolved_digest" != "$expected_digest" ]; then
        echo "Image $image resolved to $resolved_digest; expected $expected_digest." >&2
        exit 1
    fi
    pinned_image="$image@$expected_digest"

    manifest_file="$anonymous_config/manifest.txt"
    printf '%s\n' "$manifest" > "$manifest_file"
    deployment/verify-image-platforms.sh \
        --manifest-file "$manifest_file" \
        "$image" \
        linux/amd64 \
        linux/arm64

    for platform in linux/amd64 linux/arm64; do
        docker image rm -f "$pinned_image" >/dev/null 2>&1 || true
        if ! docker pull --platform "$platform" "$pinned_image"; then
            echo "Image $image could not be pulled anonymously for $platform." >&2
            echo "Change the GHCR package visibility to public before promoting this release." >&2
            exit 1
        fi
        echo "Pulled $image anonymously for $platform."
    done
    docker image rm -f "$pinned_image" >/dev/null 2>&1 || true

    echo "Verified $image resolves anonymously to $expected_digest."
done
