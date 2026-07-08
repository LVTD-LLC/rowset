#!/usr/bin/env bash
set -euo pipefail

date_part="${1:-$(date -u +%Y.%m.%d)}"
if [[ ! "$date_part" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$ ]]; then
	printf "Usage: %s [YYYY.MM.DD]\n" "$0" >&2
	exit 2
fi

if git remote get-url origin >/dev/null 2>&1; then
	git fetch --tags origin "+refs/tags/${date_part}-*:refs/tags/${date_part}-*" >/dev/null 2>&1 || true
fi

max_suffix=-1
while IFS= read -r tag; do
	suffix="${tag##*-}"
	if [[ "$suffix" =~ ^[0-9]+$ ]]; then
		suffix_number=$((10#$suffix))
		if ((suffix_number > max_suffix)); then
			max_suffix="$suffix_number"
		fi
	fi
done < <(git tag -l "${date_part}-*")

printf "%s-%d\n" "$date_part" "$((max_suffix + 1))"
