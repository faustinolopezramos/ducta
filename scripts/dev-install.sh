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
