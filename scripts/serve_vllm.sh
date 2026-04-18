#!/usr/bin/env bash
set -euo pipefail

# vLLM serve launcher (OpenAI-compatible frontend)
# Docs: https://docs.vllm.ai/en/latest/cli/serve/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV="${CONDA_ENV:-hpert}"

MODEL="${VLLM_MODEL:-cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8380}"
API_KEY="${VLLM_API_KEY:-dummy}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-${MODEL}}"
TENSOR_PARALLEL_SIZE="${VLLM_TP_SIZE:-2}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.8}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8000}" #16k
TRUST_REMOTE_CODE="${VLLM_TRUST_REMOTE_CODE:-1}"
CUDA_VISIBLE_DEVICES="${VLLM_CUDA_VISIBLE_DEVICES:-1,2}"
MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-2}"
QUANTIZATION="${VLLM_QUANTIZATION:-}"

cd "$ROOT_DIR"

VLLM_CMD=(
  vllm serve "$MODEL"
  --host "$HOST"
  --port "$PORT"
  --api-key "$API_KEY"
  --served-model-name "$SERVED_MODEL_NAME"
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --max-model-len "$MAX_MODEL_LEN"
  --max-num-seqs "$MAX_NUM_SEQS"

)

if [[ "$TRUST_REMOTE_CODE" == "1" || "$TRUST_REMOTE_CODE" == "true" || "$TRUST_REMOTE_CODE" == "yes" ]]; then
  VLLM_CMD+=(--trust-remote-code)
fi

if [[ -n "${QUANTIZATION:-}" ]]; then
  VLLM_CMD+=(--quantization "$QUANTIZATION")
fi

# Allow extra flags from env and CLI args
if [[ -n "${VLLM_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS=( ${VLLM_EXTRA_ARGS} )
  VLLM_CMD+=("${EXTRA_ARGS[@]}")
fi

VLLM_CMD+=("$@")

printf 'CUDA_VISIBLE_DEVICES=%s\n' "$CUDA_VISIBLE_DEVICES"
printf 'Starting vLLM with command:\n%s\n\n' "${VLLM_CMD[*]}"

if command -v conda >/dev/null 2>&1; then
  exec env CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" conda run --no-capture-output -n "$CONDA_ENV" "${VLLM_CMD[@]}"
else
  exec env CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" "${VLLM_CMD[@]}"
fi
