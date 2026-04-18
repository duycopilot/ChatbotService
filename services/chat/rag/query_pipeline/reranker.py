"""Rerank retrieved documents by final relevance using Cohere Rerank API."""

from __future__ import annotations

import asyncio
from typing import Any

from configs.config import settings
from integrations.rerankers.cohere import rerank_with_cohere
from services.observability import langfuse_client


def _extract_doc_text(doc: dict[str, Any]) -> str:
    return (
        doc.get("page_content")
        or doc.get("content")
        or doc.get("text")
        or doc.get("chunk")
        or ""
    )


def _doc_preview(doc: dict[str, Any], max_chars: int = 500) -> dict[str, Any]:
    return {
        "doc_id": doc.get("doc_id") or doc.get("id") or doc.get("metadata", {}).get("doc_id"),
        "score": doc.get("score"),
        "rerank_score": doc.get("rerank_score"),
        "rerank_rank": doc.get("rerank_rank"),
        "metadata": doc.get("metadata", {}),
        "raw_text": _extract_doc_text(doc)[:max_chars],
    }


async def rerank(query: str, documents: list[dict]) -> list[dict]:
    """Rerank documents with configured provider settings."""
    with langfuse_client.span(
        "rerank",
        as_type="chain",
        input={"query": query, "documents_count": len(documents)},
        metadata={
            "enabled": settings.RERANK_ENABLED,
            "model": settings.RERANK_MODEL,
            "top_k": settings.RERANK_TOP_K,
            "score_threshold": settings.RERANK_SCORE_THRESHOLD,
            "timeout_sec": settings.RERANK_TIMEOUT_SEC,
        },
    ) as obs:
        if not documents:
            if obs is not None:
                obs.update(output={"reranked_count": 0, "raw_reranked_sample": []})
            return []

        if not settings.RERANK_ENABLED:
            if obs is not None:
                obs.update(
                    output={
                        "reranked_count": len(documents),
                        "rerank_enabled": False,
                        "raw_reranked_sample": [_doc_preview(doc) for doc in documents[:3]],
                    }
                )
            return documents

        api_key = settings.RERANK_API_KEY
        if not api_key:
            # Keep pipeline alive when key is missing.
            if obs is not None:
                obs.update(
                    output={
                        "reranked_count": len(documents),
                        "rerank_skipped": "missing_api_key",
                        "raw_reranked_sample": [_doc_preview(doc) for doc in documents[:3]],
                    }
                )
            return documents

        model = settings.RERANK_MODEL
        timeout_sec = settings.RERANK_TIMEOUT_SEC
        url = settings.RERANK_URL

        doc_texts = [_extract_doc_text(doc) for doc in documents]
        top_n = min(len(documents), settings.RERANK_TOP_K)

        try:
            results = await asyncio.to_thread(
                rerank_with_cohere,
                api_key=api_key,
                model=model,
                query=query,
                documents=doc_texts,
                top_n=top_n,
                timeout_sec=timeout_sec,
                url=url,
            )
        except Exception as exc:
            # Keep the chat response alive when Cohere is rate-limited or temporarily unavailable.
            if obs is not None:
                obs.update(
                    output={
                        "reranked_count": len(documents),
                        "rerank_failed": True,
                        "rerank_error": str(exc)[:400],
                        "fallback_to_original": True,
                        "raw_reranked_sample": [_doc_preview(doc) for doc in documents[:3]],
                    }
                )
            return documents

        if not results:
            if obs is not None:
                obs.update(
                    output={
                        "reranked_count": len(documents),
                        "rerank_results_count": 0,
                        "raw_reranked_sample": [_doc_preview(doc) for doc in documents[:3]],
                    }
                )
            return documents

        reranked: list[dict[str, Any]] = []
        for rank, item in enumerate(results, start=1):
            index = item.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(documents):
                continue

            out = dict(documents[index])
            relevance_score = float(item.get("relevance_score", 0.0))
            if relevance_score < settings.RERANK_SCORE_THRESHOLD:
                continue
            out["rerank_score"] = relevance_score
            out["rerank_rank"] = rank
            reranked.append(out)

        if not reranked:
            if obs is not None:
                obs.update(
                    output={
                        "reranked_count": len(documents),
                        "rerank_filtered_out": True,
                        "raw_reranked_sample": [_doc_preview(doc) for doc in documents[:3]],
                    }
                )
            return documents

        if obs is not None:
            obs.update(
                output={
                    "reranked_count": len(reranked),
                    "rerank_results_count": len(results),
                    "raw_reranked_sample": [_doc_preview(doc) for doc in reranked[:3]],
                }
            )
        return reranked
