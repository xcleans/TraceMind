#!/usr/bin/env bash
# TraceMind monorepo — install all Python packages in editable mode.
#
# Run once after cloning, or after changing any pyproject.toml:
#   ./dev-setup.sh           # uses pip
#   ./dev-setup.sh uv        # uses uv (faster)
#
# After this, all `import atrace_device`, `import atrace_analyzer`, etc.
# resolve via standard Python packaging — no sys.path hacks needed.

set -euo pipefail
cd "$(dirname "$0")"

INSTALLER="${1:-pip}"

PACKAGES=(
    atrace-device
    atrace-provision
    atrace-analyzer
    atrace-capture
    atrace-ai
    atrace-orchestrator
    atrace-mcp
    atrace-service
)

echo "Installing TraceMind packages in editable mode (installer: $INSTALLER)..."
for pkg in "${PACKAGES[@]}"; do
    if [ -d "$pkg" ]; then
        echo "  → $pkg"
        if [ "$INSTALLER" = "uv" ]; then
            uv pip install -e "./$pkg" --quiet 2>/dev/null || uv pip install -e "./$pkg"
        else
            pip install -e "./$pkg" --quiet 2>/dev/null || pip install -e "./$pkg"
        fi
    fi
done

echo ""
echo "Done. All packages installed as editable."
echo "You can now import any package (atrace_device, atrace_analyzer, etc.) without sys.path hacks."
