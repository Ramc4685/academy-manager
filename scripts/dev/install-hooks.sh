#!/usr/bin/env bash
# install-hooks.sh — run once after cloning to wire up git hooks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-push"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
exec "$(git rev-parse --show-toplevel)/scripts/dev/pre-push-checks.sh" "$@"
EOF
chmod +x "$HOOK"
chmod +x "$ROOT/scripts/dev/pre-push-checks.sh"
echo "✓ pre-push hook installed"
