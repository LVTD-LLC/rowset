#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 IMAGE_REFERENCE" >&2
  exit 2
fi

attempts="${IMAGE_DIGEST_RESOLVE_ATTEMPTS:-1}"
delay_seconds="${IMAGE_DIGEST_RESOLVE_DELAY_SECONDS:-0}"
if [[ ! "$attempts" =~ ^[1-9][0-9]*$ ]] || [[ ! "$delay_seconds" =~ ^[0-9]+$ ]]; then
  echo "Digest resolution attempts must be positive and delay seconds non-negative." >&2
  exit 2
fi

for ((attempt = 1; attempt <= attempts; attempt++)); do
  manifest="$(docker buildx imagetools inspect "$1" 2>&1)" || true
  digest="$(awk '$1 == "Digest:" { print $2; exit }' <<< "$manifest")"

  if [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf '%s\n' "$digest"
    exit 0
  fi

  if ((attempt < attempts)); then
    sleep "$delay_seconds"
  fi
done

echo "$manifest" >&2
echo "Could not resolve an image digest for $1 after $attempts attempt(s)." >&2
exit 1
