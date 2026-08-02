#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Extract version from pyproject.toml
VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
WHEEL="dist/ducta-${VERSION}-py3-none-any.whl"

echo "=== Uninstalling ducta ==="
pip uninstall ducta -y

echo ""
echo "=== Installing dependencies ==="
poetry install

echo ""
echo "=== Building package (Unified) ==="
./scripts/build.sh

echo ""
echo "=== Installing $WHEEL ==="
pip install "$WHEEL"

echo ""
echo "=== Done ==="
