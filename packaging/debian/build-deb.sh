#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.1}"
ARCH="${2:-all}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_ROOT="$ROOT/dist/deb/au_${VERSION}_${ARCH}"

rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/DEBIAN" "$PKG_ROOT/usr/lib/au" "$PKG_ROOT/usr/bin"

cp -R "$ROOT/agent_usage_cli" "$PKG_ROOT/usr/lib/au/"

cat > "$PKG_ROOT/usr/bin/au" <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/usr/lib/au${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m agent_usage_cli "$@"
EOF
chmod 0755 "$PKG_ROOT/usr/bin/au"
ln -sf au "$PKG_ROOT/usr/bin/agent-usage"

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: au
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Yunxiao Song <maintainer@example.com>
Depends: python3 (>= 3.11)
Description: Inspect local auth state and usage context for Codex, Claude Code, and Cursor Agent
EOF

dpkg-deb --build "$PKG_ROOT"
echo "$PKG_ROOT.deb"
