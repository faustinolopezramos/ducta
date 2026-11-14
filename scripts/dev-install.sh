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

# Two packages from this repository: `ducta` (engine + CLI, the root) and
# `ducta-server` (API + web app, server/). `poetry build` only packages what is
# already in server/src/ducta_server/ui_dist; it never compiles the web app.
# Build it first, as the release workflow does.
echo "=== Building web UI ==="
if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm not found; it is needed to build the web UI (server/ui)" >&2
    exit 1
fi
(
    cd server/ui
    npm ci
    npm run build
)
if [[ ! -f server/src/ducta_server/ui_dist/index.html ]]; then
    echo "ERROR: the web UI build produced no server/src/ducta_server/ui_dist/index.html" >&2
    exit 1
fi

echo ""
echo "=== Building wheels ==="
poetry build
(cd server && poetry build -o ../dist)

VERSION="$(poetry version --short)"
WHEEL="dist/ducta-${VERSION}-py3-none-any.whl"
SERVER_WHEEL="dist/ducta_server-${VERSION}-py3-none-any.whl"

for wheel in "$WHEEL" "$SERVER_WHEEL"; do
    if [[ ! -f "$wheel" ]]; then
        echo "ERROR: wheel not found: $wheel" >&2
        exit 1
    fi
done

echo ""
echo "=== Uninstalling ducta and ducta-server ==="
poetry run pip uninstall ducta ducta-server -y

echo ""
echo "=== Installing dependencies ==="
echo "Poetry environment: $(poetry env info -p)"
poetry install --no-root --with server

echo ""
echo "=== Installing $WHEEL and $SERVER_WHEEL ==="
echo "Python target: $(poetry run python -c 'import sys; print(sys.executable)')"
poetry run pip install "$WHEEL" "$SERVER_WHEEL"

echo ""
echo "=== Done ==="
echo "To use ducta and ducta-server in your terminal: conda activate $CONDA_DEFAULT_ENV"
