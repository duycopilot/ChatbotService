"""OpenAI embeddings model initialization."""

from __future__ import annotations

from typing import Any

from configs.config import settings

try:
    from langchain_openai import OpenAIEmbeddings
except ImportError:  # pragma: no cover
    OpenAIEmbeddings = None


def get_openai_embeddings() -> OpenAIEmbeddings:
    """Initialize and return OpenAI embeddings model."""
    if OpenAIEmbeddings is None:
        raise ImportError("langchain-openai package is not installed")

    if not settings.EMBEDDINGS_API_KEY:
        raise ValueError("EMBEDDINGS_API_KEY is not configured")

    kwargs: dict[str, Any] = {
        "model": settings.EMBEDDINGS_MODEL,
        "api_key": settings.EMBEDDINGS_API_KEY,
    }

    if settings.EMBEDDINGS_BASE_URL:
        kwargs["base_url"] = settings.EMBEDDINGS_BASE_URL

    return OpenAIEmbeddings(**kwargs)
