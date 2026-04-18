#!/usr/bin/env bash
set -euo pipefail

# ===== Config =====
HEALTHCHECK_TIMEOUT_SECONDS="${HEALTHCHECK_TIMEOUT_SECONDS:-5}"

# App endpoint
APP_HEALTH_URL="${APP_HEALTH_URL:-http://localhost:8111/health}"

# Core infra (default from docker-compose.yml)
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
QDRANT_HEALTH_URL="${QDRANT_HEALTH_URL:-http://localhost:6333/healthz}"
ELASTICSEARCH_HEALTH_URL="${ELASTICSEARCH_HEALTH_URL:-http://localhost:9200/_cluster/health}"

# Optional services
CHECK_LANGFUSE="${CHECK_LANGFUSE:-0}"
LANGFUSE_HEALTH_URL="${LANGFUSE_HEALTH_URL:-http://localhost:3000/api/public/health}"
CHECK_VLLM="${CHECK_VLLM:-0}"
VLLM_MODELS_URL="${VLLM_MODELS_URL:-http://localhost:8380/v1/models}"
VLLM_API_KEY="${VLLM_API_KEY:-dummy}"

failures=0

check_http() {
  local name="$1"
  local url="$2"
  local header="${3:-}"

  local response
  if [[ -n "${header}" ]]; then
    response="$(curl -fsS --max-time "${HEALTHCHECK_TIMEOUT_SECONDS}" -H "${header}" "${url}")" || {
      echo "[healthcheck] FAIL: ${name} -> cannot reach ${url}" >&2
      failures=$((failures + 1))
      return
    }
  else
    response="$(curl -fsS --max-time "${HEALTHCHECK_TIMEOUT_SECONDS}" "${url}")" || {
      echo "[healthcheck] FAIL: ${name} -> cannot reach ${url}" >&2
      failures=$((failures + 1))
      return
    }
  fi

  echo "[healthcheck] OK: ${name}"
}

check_tcp() {
  local name="$1"
  local host="$2"
  local port="$3"

  timeout "${HEALTHCHECK_TIMEOUT_SECONDS}" bash -c "</dev/tcp/${host}/${port}" >/dev/null 2>&1 || {
    echo "[healthcheck] FAIL: ${name} -> cannot connect ${host}:${port}" >&2
    failures=$((failures + 1))
    return
  }

  echo "[healthcheck] OK: ${name}"
}

# ===== Required checks =====
check_http "FastAPI" "${APP_HEALTH_URL}"
check_tcp "PostgreSQL" "${POSTGRES_HOST}" "${POSTGRES_PORT}"
check_tcp "Redis" "${REDIS_HOST}" "${REDIS_PORT}"
check_http "Qdrant" "${QDRANT_HEALTH_URL}"
check_http "Elasticsearch" "${ELASTICSEARCH_HEALTH_URL}"

# ===== Optional checks =====
if [[ "${CHECK_LANGFUSE}" == "1" ]]; then
  check_http "Langfuse" "${LANGFUSE_HEALTH_URL}"
fi

if [[ "${CHECK_VLLM}" == "1" ]]; then
  check_http "vLLM" "${VLLM_MODELS_URL}" "Authorization: Bearer ${VLLM_API_KEY}"
fi

if [[ "${failures}" -gt 0 ]]; then
  echo "[healthcheck] FAIL: ${failures} check(s) failed" >&2
  exit 1
fi

echo "[healthcheck] OK: all checks passed"
exit 0
