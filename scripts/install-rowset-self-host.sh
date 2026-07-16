#!/bin/sh
set -eu

default_version=@ROWSET_RELEASE_VERSION@
install_dir=${ROWSET_INSTALL_DIR:-"$HOME/rowset"}
state_file="$install_dir/.rowset-release"

state_value() {
    key=$1
    file=$2
    awk -F= -v key="$key" '$1 == key { print substr($0, length(key) + 2); found = 1; exit } END { exit !found }' "$file"
}

installed_version=
if test -f "$state_file"; then
    installed_version=$(state_value ROWSET_RELEASE_VERSION "$state_file") || {
        printf 'Installed release metadata is invalid.\n' >&2
        exit 1
    }
fi

if test -n "${ROWSET_VERSION:-}"; then
    version=$ROWSET_VERSION
elif test -n "$installed_version"; then
    version=$installed_version
else
    version=$default_version
fi

printf '%s\n' "$version" | grep -Eq '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]+$' || {
    printf 'ROWSET_VERSION must match YYYY.MM.DD-N.\n' >&2
    exit 1
}
if test -n "$installed_version" && test "$version" != "$installed_version"; then
    printf 'The bootstrap installer does not update or roll back an existing release.\n' >&2
    exit 1
fi

base_url=${ROWSET_RELEASE_BASE_URL:-"https://github.com/LVTD-LLC/rowset/releases/download/$version"}
archive="rowset-self-host-$version.tar.gz"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

curl -fsSL "$base_url/$archive" -o "$temporary/$archive"
curl -fsSL "$base_url/$archive.sha256" -o "$temporary/$archive.sha256"

expected=$(awk -v archive="$archive" '$2 == archive { print $1; found = 1; exit } END { exit !found }' "$temporary/$archive.sha256") || {
    printf 'Release checksum does not name %s.\n' "$archive" >&2
    exit 1
}
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$temporary/$archive" | awk '{print $1}')
else
    actual=$(shasum -a 256 "$temporary/$archive" | awk '{print $1}')
fi
test "$actual" = "$expected" || {
    printf 'Release bundle checksum verification failed.\n' >&2
    exit 1
}

mkdir "$temporary/extracted"
tar -C "$temporary/extracted" -xzf "$temporary/$archive"
release_file="$temporary/extracted/.rowset-release"
test -f "$release_file" || {
    printf 'Release bundle is missing .rowset-release.\n' >&2
    exit 1
}
bundle_version=$(state_value ROWSET_RELEASE_VERSION "$release_file")
bundle_image=$(state_value ROWSET_RELEASE_IMAGE "$release_file")
bundle_digest=$(state_value ROWSET_RELEASE_DIGEST "$release_file")
test "$bundle_version" = "$version" || {
    printf 'Release bundle version does not match the requested version.\n' >&2
    exit 1
}
test "$bundle_image" = "ghcr.io/lvtd-llc/rowset:$version" || {
    printf 'Release bundle image does not match the requested version.\n' >&2
    exit 1
}
printf '%s\n' "$bundle_digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || {
    printf 'Release bundle digest is invalid.\n' >&2
    exit 1
}

mkdir -p "$install_dir"
cp -R "$temporary/extracted/." "$install_dir/"

printf 'Installed Rowset self-host release %s in %s.\n' "$version" "$install_dir"
printf 'Run %s/deployment/self-host/version.sh to inspect the installed release.\n' "$install_dir"
