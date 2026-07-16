#!/bin/sh
set -eu

if test "$#" -ne 5; then
    printf 'Usage: %s VERSION COMMIT IMAGE DIGEST OUTPUT_DIR\n' "$0" >&2
    exit 2
fi

version=$1
commit=$2
image=$3
digest=$4
output_dir=$5
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/.." && pwd)

printf '%s\n' "$version" | grep -Eq '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]+$' || {
    printf 'Release version must match YYYY.MM.DD-N.\n' >&2
    exit 1
}
printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$' || {
    printf 'Release commit must be a full lowercase Git SHA.\n' >&2
    exit 1
}
test "$image" = "ghcr.io/lvtd-llc/rowset:$version" || {
    printf 'Release image must use the matching Rowset release tag.\n' >&2
    exit 1
}
printf '%s\n' "$digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || {
    printf 'Release digest must use the sha256:<digest> form.\n' >&2
    exit 1
}

mkdir -p "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT HUP INT TERM
bundle_root="$staging/rowset-self-host"
mkdir -p "$bundle_root/deployment"

cp "$root/SELF_HOSTING.md" "$root/docker-compose-prod.yml" "$bundle_root/"
cp -R "$root/deployment/self-host" "$bundle_root/deployment/"
cp "$root/deployment/verify-image-platforms.sh" "$bundle_root/deployment/"

cat > "$bundle_root/.rowset-release" <<EOF
ROWSET_RELEASE_VERSION=$version
ROWSET_RELEASE_COMMIT=$commit
ROWSET_RELEASE_IMAGE=$image
ROWSET_RELEASE_DIGEST=$digest
EOF

archive="rowset-self-host-$version.tar.gz"
tar -C "$bundle_root" -czf "$output_dir/$archive" .

if command -v sha256sum >/dev/null 2>&1; then
    checksum=$(sha256sum "$output_dir/$archive" | awk '{print $1}')
else
    checksum=$(shasum -a 256 "$output_dir/$archive" | awk '{print $1}')
fi
printf '%s  %s\n' "$checksum" "$archive" > "$output_dir/$archive.sha256"

sed "s/@ROWSET_RELEASE_VERSION@/$version/g" \
    "$root/scripts/install-rowset-self-host.sh" > "$output_dir/install-rowset-self-host.sh"
chmod 755 "$output_dir/install-rowset-self-host.sh"
