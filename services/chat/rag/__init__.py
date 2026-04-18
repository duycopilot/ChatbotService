"""RAG service package.

Structure:
- data_ingestion: parser, preprocessing, chunking, indexing prep
- query_pipeline: rewrite, retrieve, rerank, merge, feedback
"""

from services.chat.rag.query_pipeline.pipeline import handle

__all__ = ["handle"]
