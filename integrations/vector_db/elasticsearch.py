"""Elasticsearch integration for BM25 retrieval."""

from __future__ import annotations

from typing import Any


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    return {}


def bm25_search_elasticsearch(
    *,
    query: str,
    top_k: int,
    index_name: str,
    es_url: str,
    boost_factor: float = 1.0,
    match_type: str = "best_fields",
) -> list[dict]:
    """Run BM25 match query on Elasticsearch and normalize schema."""
    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:  # pragma: no cover
        raise ImportError("elasticsearch package is not installed") from exc

    client = Elasticsearch(es_url)
    search_fields = [
        "content^1.4",
        "page_content",
        "metadata.table_name^1.2",
        "metadata.header_path^1.2",
        "metadata.h1^1.1",
        "metadata.section",
        "metadata.title",
    ]
    search_kwargs: dict[str, Any] = {
        "index": index_name,
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": search_fields,
                "type": match_type,
                "boost": boost_factor,
            }
        },
    }
    if match_type not in {"best_fields", "most_fields", "cross_fields", "phrase", "phrase_prefix"}:
        search_kwargs["query"] = {
            "match": {
                "content": {
                    "query": query,
                    "boost": boost_factor,
                    "operator": "or",
                }
            }
        }

    response = client.search(**search_kwargs)

    hits = response.get("hits", {}).get("hits", [])
    results: list[dict] = []
    for hit in hits:
        source = hit.get("_source", {})
        score = float(hit.get("_score", 0.0))
        content = source.get("content") or source.get("page_content", "")
        results.append(
            {
                "id": str(hit.get("_id", "")),
                "source": "elasticsearch",
                "content": content,
                "page_content": content,
                "metadata": _normalize_metadata(source.get("metadata")),
                "score": score,
                "bm25_score": score,
            }
        )

    return results
