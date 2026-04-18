"""Data ingestion package for RAG."""

from services.chat.rag.data_ingestion.parser import ingest_documents
from services.chat.rag.data_ingestion.chunking import chunk_documents
from services.chat.rag.data_ingestion.embedding import embed_chunks
from services.chat.rag.data_ingestion.index import index_embedded_chunks_qdrant
from services.chat.rag.data_ingestion.pipeline import run_data_ingestion_pipeline

__all__ = [
	"ingest_documents",
	"chunk_documents",
	"embed_chunks",
	"index_embedded_chunks_qdrant",
	"run_data_ingestion_pipeline",
]
