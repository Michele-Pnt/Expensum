#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$PROJECT_DIR"

if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON="$PYTHON_BIN"
elif [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
else
    echo "Python non trovato. Crea prima l'ambiente virtuale o imposta PYTHON_BIN." >&2
    exit 1
fi

exec "$PYTHON" "$PROJECT_DIR/scheduler.py" "$@"
