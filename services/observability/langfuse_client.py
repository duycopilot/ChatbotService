"""Langfuse observability helpers for manual span-based tracing (v4 SDK)."""

from __future__ import annotations

import logging
import os
from urllib import error as urllib_error
from urllib import request as urllib_request
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

logger = logging.getLogger(__name__)

_initialized = False
_enabled = False


def _otel_endpoint_supported(host: str) -> bool:
    base = host.rstrip("/")
    url = f"{base}/api/public/otel/v1/traces"
    req = urllib_request.Request(url=url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib_request.urlopen(req, timeout=2):
            return True
    except urllib_error.HTTPError as exc:
        # Endpoint exists but request is unauthorized/invalid -> compatible.
        return exc.code in (400, 401, 403, 405)
    except Exception:
        return False


def init() -> None:
    """Initialize Langfuse credentials in env vars.

    Safe to call multiple times.
    """
    global _initialized, _enabled
    if _initialized:
        return

    from configs.config import settings  # local import avoids circulars

    if not settings.LANGFUSE_ENABLED:
        logger.debug("Langfuse tracing disabled")
        _initialized = True
        _enabled = False
        return

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse enabled but keys are missing; tracing is disabled")
        _initialized = True
        _enabled = False
        return

    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY)
    os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_HOST)

    if not _otel_endpoint_supported(settings.LANGFUSE_HOST):
        logger.warning(
            "Langfuse OTEL endpoint is unavailable at %s; tracing disabled",
            settings.LANGFUSE_HOST,
        )
        _initialized = True
        _enabled = False
        return

    logger.info("Langfuse initialized -> %s", settings.LANGFUSE_HOST)
    _initialized = True
    _enabled = True


def is_enabled() -> bool:
    return _enabled


def _get_client():
    if not _enabled:
        return None
    try:
        from langfuse import get_client  # type: ignore[import]

        return get_client()
    except Exception:
        return None


@contextmanager
def trace_context(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    trace_name: str | None = None,
) -> Generator[None, None, None]:
    """Attach user/session metadata to all child spans in this context."""
    if not _enabled:
        yield
        return

    try:
        from langfuse import propagate_attributes  # type: ignore[import]

    except Exception:
        yield
        return

    with propagate_attributes(
        user_id=user_id,
        session_id=session_id,
        tags=tags,
        trace_name=trace_name,
    ):
        yield


@contextmanager
def span(
    name: str,
    *,
    as_type: str = "span",
    input: Any = None,
    metadata: Any = None,
) -> Generator[Any, None, None]:
    """Create a manual Langfuse span around a block."""
    client = _get_client()
    if client is None:
        yield None
        return

    try:
        observation_context = client.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=input,
            metadata=metadata,
            end_on_exit=True,
        )
    except Exception:
        yield None
        return

    with observation_context as observation:
        yield observation


def set_trace_io(*, input: Any = None, output: Any = None) -> None:
    """Set root trace input/output safely."""
    client = _get_client()
    if client is None:
        return
    try:
        client.set_current_trace_io(input=input, output=output)
    except Exception:
        return


def get_langchain_handler():
    """Return LangChain callback handler bound to current trace+span."""
    client = _get_client()
    if client is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler  # type: ignore[import]
        from langfuse.types import TraceContext  # type: ignore[import]

        trace_id = client.get_current_trace_id()
        if not trace_id:
            return None
        span_id = client.get_current_observation_id()
        context = (
            TraceContext(trace_id=trace_id, parent_span_id=span_id)
            if span_id
            else TraceContext(trace_id=trace_id)
        )
        return CallbackHandler(trace_context=context)
    except Exception:
        return None


def flush() -> None:
    """Flush pending traces safely on shutdown."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        return
