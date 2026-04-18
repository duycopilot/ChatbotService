"""Qdrant integration for semantic retrieval."""

from __future__ import annotations

from typing import Any

from integrations.embeds.openai import get_openai_embeddings


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    return {}


def _build_qdrant_filter(metadata_filter: dict[str, Any] | None):
    if not metadata_filter:
        return None

    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    must_conditions = []
    for key, value in metadata_filter.items():
        if value is None:
            continue
        must_conditions.append(
            FieldCondition(
                key=f"metadata.{key}",
                match=MatchValue(value=value),
            )
        )

    if not must_conditions:
        return None
    return Filter(must=must_conditions)


def semantic_search_qdrant(
    *,
    query: str,
    top_k: int,
    collection_name: str,
    qdrant_url: str,
    qdrant_api_key: str | None,
    metadata_filter: dict[str, Any] | None = None,
) -> list[dict]:
    """Run semantic search on Qdrant and normalize to common schema."""
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover
        raise ImportError("qdrant-client is not installed") from exc

    embeddings = get_openai_embeddings()
    query_vector = embeddings.embed_query(query)
    query_filter = _build_qdrant_filter(metadata_filter)

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    hits: list[Any]
    if hasattr(client, "query_points"):
        points = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        hits = list(getattr(points, "points", []) or [])
    else:
        hits = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )

    results: list[dict] = []
    for hit in hits:
        payload = hit.payload or {}
        content = payload.get("content") or payload.get("page_content", "")
        metadata = _normalize_metadata(payload.get("metadata"))
        results.append(
            {
                "id": str(hit.id),
                "source": "qdrant",
                "content": content,
                "page_content": content,
                "metadata": metadata,
                "score": float(hit.score),
                "semantic_score": float(hit.score),
            }
        )

    return results
