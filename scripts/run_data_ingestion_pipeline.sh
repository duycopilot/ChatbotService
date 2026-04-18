#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV="${CONDA_ENV:-hpert}"

cd "$ROOT_DIR"

if command -v conda >/dev/null 2>&1; then
	PYTHONPATH=. conda run --no-capture-output -n "$CONDA_ENV" python "$ROOT_DIR/services/chat/rag/data_ingestion/pipeline.py" "$@"
else
	PYTHONPATH=. python3 "$ROOT_DIR/services/chat/rag/data_ingestion/pipeline.py" "$@"
fi
