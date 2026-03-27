#!/usr/bin/env bash
set -euo pipefail

REPO="${AU_REPO:-supdub/au}"
VERSION="${AU_VERSION:-${AGENT_USAGE_VERSION:-latest}}"
BIN_DIR="${AU_BIN_DIR:-$HOME/.local/bin}"

usage() {
  cat <<'EOF'
Install au.

Usage:
  ./install.sh --from-local
  curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | bash

Environment:
  AU_REPO                GitHub repo in OWNER/REPO form
  AU_VERSION             Release tag or "latest"
  AGENT_USAGE_VERSION    Backward-compatible alias for AU_VERSION
  AU_BIN_DIR             Install directory, default ~/.local/bin
EOF
}

platform_os() {
  case "${AU_OS:-$(uname -s)}" in
    Linux)
      printf 'linux\n'
      ;;
    Darwin)
      printf 'macos\n'
      ;;
    *)
      printf 'unknown\n'
      ;;
  esac
}

platform_arch() {
  case "${AU_ARCH:-$(uname -m)}" in
    x86_64|amd64)
      printf 'x86_64\n'
      ;;
    arm64|aarch64)
      printf 'arm64\n'
      ;;
    *)
      printf 'unknown\n'
      ;;
  esac
}

preferred_asset_name() {
  local os arch
  os="$(platform_os)"
  arch="$(platform_arch)"

  case "$os:$arch" in
    linux:x86_64)
      printf 'au-linux-x86_64\n'
      ;;
    macos:arm64)
      printf 'au-macos-arm64\n'
      ;;
    macos:x86_64)
      printf 'au-macos-x86_64\n'
      ;;
    *)
      printf 'au\n'
      ;;
  esac
}

asset_url() {
  local asset_name
  asset_name="$1"

  if [[ "$VERSION" == "latest" ]]; then
    printf 'https://github.com/%s/releases/latest/download/%s\n' "$REPO" "$asset_name"
  else
    printf 'https://github.com/%s/releases/download/%s/%s\n' "$REPO" "$VERSION" "$asset_name"
  fi
}

asset_exists() {
  local url
  url="$1"
  curl -IfsSL "$url" >/dev/null 2>/dev/null
}

resolve_asset_name() {
  local preferred
  preferred="$(preferred_asset_name)"

  if [[ "$preferred" == "au" ]]; then
    printf 'au\n'
    return 0
  fi

  if [[ "${AU_SKIP_ASSET_PROBE:-0}" == "1" ]]; then
    printf '%s\n' "$preferred"
    return 0
  fi

  if asset_exists "$(asset_url "$preferred")"; then
    printf '%s\n' "$preferred"
    return 0
  fi

  printf 'au\n'
}

requires_python3() {
  [[ "$1" == "au" ]]
}

ensure_runtime_for_asset() {
  local asset_name
  asset_name="$1"

  if requires_python3 "$asset_name" && ! command -v python3 >/dev/null 2>&1; then
    printf 'No native release asset is available for %s/%s, and the portable artifact requires python3 on PATH.\n' "$(platform_os)" "$(platform_arch)" >&2
    exit 1
  fi
}

download_url() {
  asset_url "$(resolve_asset_name)"
}

install_local() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 "$root/scripts/build_zipapp.py" >/dev/null
  mkdir -p "$BIN_DIR"
  install -m 0755 "$root/dist/au" "$BIN_DIR/au"
  ln -sf "$BIN_DIR/au" "$BIN_DIR/agent-usage"
}

install_remote() {
  local asset_name tmp url
  asset_name="$(resolve_asset_name)"
  ensure_runtime_for_asset "$asset_name"
  url="$(asset_url "$asset_name")"
  tmp="$(mktemp)"
  mkdir -p "$BIN_DIR"
  curl -fsSL "$url" -o "$tmp"
  install -m 0755 "$tmp" "$BIN_DIR/au"
  rm -f "$tmp"
  ln -sf "$BIN_DIR/au" "$BIN_DIR/agent-usage"
}

main() {
  if [[ "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  if [[ "${1:-}" == "--print-download-url" ]]; then
    download_url
    exit 0
  fi

  if [[ "${1:-}" == "--from-local" ]]; then
    install_local
  else
    install_remote
  fi

  printf 'Installed au to %s/au\n' "$BIN_DIR"
  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    printf 'Add %s to PATH if needed.\n' "$BIN_DIR"
  fi
}

main "$@"
