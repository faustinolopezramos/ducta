#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Activate the conda environment if it's not already active
if [[ "${CONDA_DEFAULT_ENV:-}" != "ducta" ]]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate ducta
fi

echo "=== Environment: conda \"$CONDA_DEFAULT_ENV\" ($(conda info --base)/envs/$CONDA_DEFAULT_ENV) ==="

# `poetry build` only packages what is already in src/ducta/ui/dist; it never
# compiles the web app. Build it first, as the release workflow does.
echo "=== Building web UI ==="
if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm not found; it is needed to build the web UI (src/ducta/ui)" >&2
    exit 1
fi
(
    cd src/ducta/ui
    npm ci
    npm run build
)
if [[ ! -f src/ducta/ui/dist/index.html ]]; then
    echo "ERROR: the web UI build produced no src/ducta/ui/dist/index.html" >&2
    exit 1
fi

echo ""
echo "=== Building wheel ==="
poetry build

VERSION="$(poetry version --short)"
WHEEL="dist/ducta-${VERSION}-py3-none-any.whl"

if [[ ! -f "$WHEEL" ]]; then
    echo "ERROR: wheel not found: $WHEEL" >&2
    exit 1
fi

echo ""
echo "=== Uninstalling ducta ==="
poetry run pip uninstall ducta -y

echo ""
echo "=== Installing dependencies ==="
echo "Poetry environment: $(poetry env info -p)"
poetry install --no-root

echo ""
echo "=== Installing $WHEEL ==="
echo "Python target: $(poetry run python -c 'import sys; print(sys.executable)')"
poetry run pip install "$WHEEL"

echo ""
echo "=== Done ==="
echo "To use ducta in your terminal: conda activate $CONDA_DEFAULT_ENV"
