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

download_asset() {
  local asset_name destination
  asset_name="$1"
  destination="$2"
  curl -fsSL "$(asset_url "$asset_name")" -o "$destination"
}

source_archive_url() {
  if [[ "$VERSION" == "latest" ]]; then
    printf 'https://github.com/%s/archive/refs/heads/main.zip\n' "$REPO"
  else
    printf 'https://github.com/%s/archive/refs/tags/%s.zip\n' "$REPO" "$VERSION"
  fi
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

is_linux_native_asset() {
  [[ "$1" == "au-linux-x86_64" ]]
}

glibc_incompatibility_output() {
  local output
  output="$1"
  [[ "$output" == *"GLIBC_"* ]] || [[ "$output" == *"glibc"* ]] || [[ "$output" == *"libc.so"* ]] || [[ "$output" == *"libm.so"* ]]
}

python_runtime_incompatibility_output() {
  local output
  output="$1"
  [[ "$output" == *"No module named 'tomllib'"* ]] || [[ "$output" == *"requires Python 3.11"* ]] || [[ "$output" == *"Python 3.11"* ]]
}

native_asset_requires_portable_fallback() {
  local asset_name path output status
  asset_name="$1"
  path="$2"

  if ! is_linux_native_asset "$asset_name"; then
    return 1
  fi

  chmod 0755 "$path"

  set +e
  output="$("$path" -v 2>&1)"
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    return 1
  fi

  if glibc_incompatibility_output "$output"; then
    printf 'Native Linux release asset is incompatible with this system; falling back to the portable Python artifact.\n' >&2
    return 0
  fi

  printf 'Failed to validate native Linux release asset.\n%s\n' "$output" >&2
  exit 1
}

portable_asset_requires_source_fallback() {
  local asset_name path output status
  asset_name="$1"
  path="$2"

  if ! requires_python3 "$asset_name"; then
    return 1
  fi

  chmod 0755 "$path"

  set +e
  output="$("$path" -v 2>&1)"
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    return 1
  fi

  if python_runtime_incompatibility_output "$output" && [[ "$VERSION" == "latest" ]]; then
    printf 'Portable release artifact is incompatible with this Python runtime; building from the main branch source archive instead.\n' >&2
    return 0
  fi

  printf 'Failed to validate portable release artifact.\n%s\n' "$output" >&2
  exit 1
}

install_from_source_archive() {
  local archive tmpdir root
  archive="$(mktemp)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$BIN_DIR"

  curl -fsSL "$(source_archive_url)" -o "$archive"
  python3 - "$archive" "$tmpdir" <<'PY'
import sys
import zipfile

archive, destination = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as bundle:
    bundle.extractall(destination)
PY

  root=""
  for candidate in "$tmpdir"/*; do
    if [[ -d "$candidate" ]]; then
      root="$candidate"
      break
    fi
  done

  if [[ -z "$root" ]]; then
    printf 'Failed to unpack source archive from %s.\n' "$(source_archive_url)" >&2
    rm -f "$archive"
    rm -rf "$tmpdir"
    exit 1
  fi

  python3 "$root/scripts/build_zipapp.py" >/dev/null
  install -m 0755 "$root/dist/au" "$BIN_DIR/au"
  rm -f "$archive"
  rm -rf "$tmpdir"
  ln -sf "$BIN_DIR/au" "$BIN_DIR/agent-usage"
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
  local asset_name tmp
  asset_name="$(resolve_asset_name)"
  ensure_runtime_for_asset "$asset_name"
  tmp="$(mktemp)"
  mkdir -p "$BIN_DIR"
  download_asset "$asset_name" "$tmp"

  if native_asset_requires_portable_fallback "$asset_name" "$tmp"; then
    rm -f "$tmp"
    asset_name="au"
    ensure_runtime_for_asset "$asset_name"
    tmp="$(mktemp)"
    download_asset "$asset_name" "$tmp"
  fi

  if portable_asset_requires_source_fallback "$asset_name" "$tmp"; then
    rm -f "$tmp"
    install_from_source_archive
    return
  fi

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
