"""Retrieve relevant documents from Qdrant or Elasticsearch."""

from __future__ import annotations

import asyncio
from configs.config import settings
from integrations.vector_db.elasticsearch import bm25_search_elasticsearch
from integrations.vector_db.qdrant import semantic_search_qdrant
from services.observability import langfuse_client


def _doc_preview(doc: dict, max_chars: int = 500) -> dict:
    text = (
        doc.get("page_content")
        or doc.get("content")
        or doc.get("text")
        or doc.get("chunk")
        or ""
    )
    return {
        "doc_id": doc.get("doc_id") or doc.get("id") or doc.get("metadata", {}).get("doc_id"),
        "score": doc.get("score"),
        "metadata": doc.get("metadata", {}),
        "raw_text": str(text)[:max_chars],
    }


def _retrieval_output_payload(results: list[dict]) -> dict:
    return {
        "results_count": len(results),
        "raw_results_sample": [_doc_preview(doc) for doc in results[:3]],
    }


async def retrieve_qdrant(
    query: str,
    top_k: int,
    collection_name: str,
    qdrant_url: str,
    qdrant_api_key: str | None = None,
    metadata_filter: dict | None = None,
) -> list[dict]:
    """Retrieve top-k documents from Qdrant semantic search."""
    with langfuse_client.span(
        "retrieve_qdrant",
        as_type="retriever",
        input={"query": query, "top_k": top_k, "collection_name": collection_name},
        metadata={
            "provider": "qdrant",
            "collection_name": collection_name,
            "top_k": top_k,
            "metadata_filter_set": bool(metadata_filter),
        },
    ) as obs:
        results = await asyncio.to_thread(
            semantic_search_qdrant,
            query=query,
            top_k=top_k,
            collection_name=collection_name,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            metadata_filter=metadata_filter,
        )
        if obs is not None:
            obs.update(output=_retrieval_output_payload(results))
        return results


async def retrieve_elasticsearch(
    query: str,
    top_k: int,
    index_name: str,
    es_url: str,
    boost_factor: float,
    match_type: str,
) -> list[dict]:
    """Retrieve top-k documents from Elasticsearch BM25 search."""
    with langfuse_client.span(
        "retrieve_elasticsearch",
        as_type="retriever",
        input={"query": query, "top_k": top_k, "index_name": index_name},
        metadata={
            "provider": "elasticsearch",
            "index_name": index_name,
            "top_k": top_k,
            "boost_factor": boost_factor,
            "match_type": match_type,
        },
    ) as obs:
        results = await asyncio.to_thread(
            bm25_search_elasticsearch,
            query=query,
            top_k=top_k,
            index_name=index_name,
            es_url=es_url,
            boost_factor=boost_factor,
            match_type=match_type,
        )
        if obs is not None:
            obs.update(output=_retrieval_output_payload(results))
        return results


async def retrieve(query: str, top_k: int | None = None) -> list[dict]:
    """Default retrieval using configured mode."""
    effective_top_k = top_k or settings.QDRANT_TOP_K
    if settings.RETRIEVAL_MODE == "semantic":
        return await retrieve_qdrant(
            query=query,
            top_k=effective_top_k,
            collection_name=settings.QDRANT_COLLECTION_NAME,
            qdrant_url=settings.QDRANT_URL,
            qdrant_api_key=settings.QDRANT_API_KEY,
        )
    return await retrieve_elasticsearch(
        query=query,
        top_k=effective_top_k,
        index_name=settings.ELASTICSEARCH_INDEX_NAME,
        es_url=settings.ELASTICSEARCH_URL,
        boost_factor=settings.ELASTICSEARCH_BOOST_FACTOR,
        match_type=settings.ELASTICSEARCH_MATCH_TYPE,
    )
