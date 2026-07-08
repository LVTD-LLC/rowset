#!/usr/bin/env sh
set -eu

repo="${ROWSET_CLI_REPO:-LVTD-LLC/rowset}"
version="${ROWSET_CLI_VERSION:-latest}"
install_dir="${ROWSET_INSTALL_DIR:-}"
default_latest_url="https://github.com/LVTD-LLC/rowset/releases/latest/download"

detect_os() {
	case "$(uname -s)" in
		Linux) printf "linux" ;;
		Darwin) printf "darwin" ;;
		*) printf "Unsupported OS: %s\n" "$(uname -s)" >&2; exit 1 ;;
	esac
}

detect_arch() {
	case "$(uname -m)" in
		x86_64 | amd64) printf "amd64" ;;
		arm64 | aarch64) printf "arm64" ;;
		*) printf "Unsupported architecture: %s\n" "$(uname -m)" >&2; exit 1 ;;
	esac
}

choose_install_dir() {
	if [ -n "$install_dir" ]; then
		printf "%s" "$install_dir"
		return
	fi

	if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
		printf "/usr/local/bin"
		return
	fi

	printf "%s/.local/bin" "$HOME"
}

download() {
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL "$1" -o "$2"
		return
	fi
	if command -v wget >/dev/null 2>&1; then
		wget -qO "$2" "$1"
		return
	fi
	printf "curl or wget is required to install rowset-cli.\n" >&2
	exit 1
}

os="$(detect_os)"
arch="$(detect_arch)"
asset="rowset-cli_${os}_${arch}.tar.gz"
if [ "$version" = "latest" ]; then
	if [ "$repo" = "LVTD-LLC/rowset" ]; then
		base_url="$default_latest_url"
	else
		base_url="https://github.com/${repo}/releases/latest/download"
	fi
else
	base_url="https://github.com/${repo}/releases/download/${version}"
fi
url="${base_url}/${asset}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

download "$url" "$tmp_dir/$asset"
tar -xzf "$tmp_dir/$asset" -C "$tmp_dir"

install_dir="$(choose_install_dir)"
mkdir -p "$install_dir"
install -m 0755 "$tmp_dir/rowset-cli" "$install_dir/rowset-cli"

printf "rowset-cli installed to %s/rowset-cli\n" "$install_dir"
case ":$PATH:" in
	*":$install_dir:"*) ;;
	*) printf "Add %s to PATH before running rowset-cli.\n" "$install_dir" ;;
esac
