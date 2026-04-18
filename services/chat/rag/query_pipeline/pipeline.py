"""RAG pipeline: retrieve -> merge -> rerank -> generate."""

import asyncio

from langchain_openai import ChatOpenAI
from configs.config import settings
from services.chat.memory import MemoryTurn
from services.observability import langfuse_client

from services.chat.rag.query_pipeline.generation import generate_answer
from services.chat.rag.query_pipeline.postprocessor import merge_semantic_bm25_results
from services.chat.rag.query_pipeline.retriever import retrieve_elasticsearch, retrieve_qdrant
from services.chat.rag.query_pipeline.reranker import rerank


def _doc_preview(doc: dict, max_chars: int = 400) -> dict:
    text = doc.get("page_content") or doc.get("content") or doc.get("text") or ""
    return {
        "doc_id": doc.get("doc_id") or doc.get("id") or doc.get("metadata", {}).get("doc_id"),
        "score": doc.get("score"),
        "hybrid_score": doc.get("hybrid_score"),
        "rerank_score": doc.get("rerank_score"),
        "metadata": doc.get("metadata", {}),
        "raw_text": str(text)[:max_chars],
    }


async def handle(
    message: str,
    llm: ChatOpenAI | None = None,
    recent_turns: list[MemoryTurn] | None = None,
    long_term_memories: list[str] | None = None,
) -> str:
    """Run the query pipeline and return final answer text."""
    _ = llm
    
    with langfuse_client.span(
        "rag_pipeline",
        as_type="chain",
        input={
            "message": message,
            "retrieval_mode": settings.RETRIEVAL_MODE,
        },
        metadata={
            "retrieval_mode": settings.RETRIEVAL_MODE,
            "qdrant_top_k": settings.QDRANT_TOP_K,
            "elasticsearch_top_k": settings.ELASTICSEARCH_TOP_K,
            "fusion_method": settings.FUSION_METHOD,
            "rerank_enabled": settings.RERANK_ENABLED,
        },
    ) as pipeline_obs:
        if settings.RETRIEVAL_MODE == "semantic":
            merged_docs = await retrieve_qdrant(
                query=message,
                top_k=settings.QDRANT_TOP_K,
                collection_name=settings.QDRANT_COLLECTION_NAME,
                qdrant_url=settings.QDRANT_URL,
                qdrant_api_key=settings.QDRANT_API_KEY,
            )
        else:
            semantic_docs, bm25_docs = await asyncio.gather(
                retrieve_qdrant(
                    query=message,
                    top_k=settings.QDRANT_TOP_K,
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    qdrant_url=settings.QDRANT_URL,
                    qdrant_api_key=settings.QDRANT_API_KEY,
                ),
                retrieve_elasticsearch(
                    query=message,
                    top_k=settings.ELASTICSEARCH_TOP_K,
                    index_name=settings.ELASTICSEARCH_INDEX_NAME,
                    es_url=settings.ELASTICSEARCH_URL,
                    boost_factor=settings.ELASTICSEARCH_BOOST_FACTOR,
                    match_type=settings.ELASTICSEARCH_MATCH_TYPE,
                ),
            )

            with langfuse_client.span(
                "merge_results",
                as_type="chain",
                input={
                    "semantic_count": len(semantic_docs),
                    "bm25_count": len(bm25_docs),
                    "semantic_sample": [_doc_preview(doc) for doc in semantic_docs[:2]],
                    "bm25_sample": [_doc_preview(doc) for doc in bm25_docs[:2]],
                },
                metadata={
                    "method": settings.FUSION_METHOD,
                    "weight_dense": settings.FUSION_WEIGHT_DENSE,
                    "weight_sparse": settings.FUSION_WEIGHT_SPARSE,
                    "final_top_k": settings.FUSION_FINAL_TOP_K,
                },
            ) as merge_obs:
                merged_docs = merge_semantic_bm25_results(
                    semantic_results=semantic_docs,
                    bm25_results=bm25_docs,
                    semantic_weight=settings.FUSION_WEIGHT_DENSE,
                    bm25_weight=settings.FUSION_WEIGHT_SPARSE,
                    final_top_k=settings.FUSION_FINAL_TOP_K,
                )
                if merge_obs is not None:
                    merge_obs.update(
                        output={
                            "merged_count": len(merged_docs),
                            "merged_sample": [_doc_preview(doc) for doc in merged_docs[:3]],
                        }
                    )

        docs = await rerank(message, merged_docs)
        answer = await generate_answer(
            message,
            docs,
            llm=llm,
            recent_turns=recent_turns,
            long_term_memories=long_term_memories,
        )
        if pipeline_obs is not None:
            pipeline_obs.update(
                output={
                    "retrieved_count": len(merged_docs),
                    "reranked_count": len(docs),
                    "reranked_sample": [_doc_preview(doc) for doc in docs[:3]],
                    "answer_preview": str(answer)[:600],
                }
            )
        return answer
