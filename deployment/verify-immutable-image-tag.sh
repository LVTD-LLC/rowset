#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 EXPECTED_DIGEST IMMUTABLE_IMAGE_REFERENCE" >&2
  exit 2
fi

expected_digest="$1"
image="$2"
inspection="$(mktemp)"
trap 'rm -f "$inspection"' EXIT

if docker buildx imagetools inspect "$image" > "$inspection" 2>&1; then
  resolved_digest="$(awk '$1 == "Digest:" { print $2; exit }' "$inspection")"
  if [[ "$resolved_digest" != "$expected_digest" ]]; then
    echo "$image is immutable but already resolves to $resolved_digest; expected $expected_digest." >&2
    exit 1
  fi
  exit 0
fi

if grep -Eiq 'manifest unknown|not found' "$inspection"; then
  exit 0
fi

cat "$inspection" >&2
echo "Could not determine whether immutable tag $image already exists; refusing promotion." >&2
exit 1
