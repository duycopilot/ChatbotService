"""Embedding utilities for chunked documents."""

from __future__ import annotations

from langchain_core.documents import Document

from configs.config import settings
from integrations.embeds.openai import get_openai_embeddings


def embed_chunks(chunks: list[Document], batch_size: int | None = None) -> list[dict]:
	"""Embed chunked documents and return payloads ready for indexing."""
	batch_size = batch_size or settings.INGESTION_EMBED_BATCH_SIZE

	if not chunks:
		return []

	embeddings = get_openai_embeddings()
	payloads: list[dict] = []

	for start in range(0, len(chunks), batch_size):
		batch = chunks[start : start + batch_size]
		vectors = embeddings.embed_documents([chunk.page_content for chunk in batch])

		for chunk, vector in zip(batch, vectors):
			payloads.append(
				{
					"page_content": chunk.page_content,
					"metadata": dict(chunk.metadata),
					"embedding": vector,
				}
			)

	return payloads
