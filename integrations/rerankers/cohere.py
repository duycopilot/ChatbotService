"""Cohere reranker integration."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request


def _read_http_error_body(exc: error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

    try:
        parsed = json.loads(body)
    except Exception:
        return body.strip()

    if isinstance(parsed, dict):
        message = parsed.get("message") or parsed.get("error") or parsed.get("detail")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(parsed, ensure_ascii=False)
    return body.strip()


def rerank_with_cohere(
    *,
    api_key: str,
    model: str,
    query: str,
    documents: list[str],
    top_n: int,
    timeout_sec: float,
    url: str,
) -> list[dict[str, Any]]:
    """Call Cohere rerank API and return raw results list."""
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": top_n,
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except error.HTTPError as exc:
        detail = _read_http_error_body(exc)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Cohere rerank HTTP error: {exc.code}{suffix}") from exc
    except error.URLError as exc:
        raise RuntimeError("Cohere rerank connection error") from exc

    results = data.get("results")
    if not isinstance(results, list):
        return []
    return results
