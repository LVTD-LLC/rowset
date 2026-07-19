#!/bin/sh
set -eu

if test "$#" -ne 1; then
    printf 'Usage: %s DISK_PATH\n' "$0" >&2
    exit 2
fi

disk_capacity_bytes=${ROWSET_BENCHMARK_DISK_CAPACITY_BYTES:-}
disk_free_bytes=${ROWSET_BENCHMARK_DISK_FREE_BYTES:-}
if test -z "$disk_capacity_bytes" || test -z "$disk_free_bytes"; then
    disk_usage=$(df -B1 --output=size,avail "$1" | awk 'NR == 2 { print $1, $2 }')
    detected_disk_capacity_bytes=${disk_usage%% *}
    detected_disk_free_bytes=${disk_usage##* }
    disk_capacity_bytes=${disk_capacity_bytes:-$detected_disk_capacity_bytes}
    disk_free_bytes=${disk_free_bytes:-$detected_disk_free_bytes}
fi

printf '%s %s\n' "$disk_capacity_bytes" "$disk_free_bytes"
