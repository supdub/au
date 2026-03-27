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

download_url() {
  if [[ "$VERSION" == "latest" ]]; then
    printf 'https://github.com/%s/releases/latest/download/au\n' "$REPO"
  else
    printf 'https://github.com/%s/releases/download/%s/au\n' "$REPO" "$VERSION"
  fi
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
  local url
  url="$(download_url)"
  mkdir -p "$BIN_DIR"
  curl -fsSL "$url" -o "$BIN_DIR/au"
  chmod 0755 "$BIN_DIR/au"
  ln -sf "$BIN_DIR/au" "$BIN_DIR/agent-usage"
}

main() {
  if [[ "${1:-}" == "--help" ]]; then
    usage
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
