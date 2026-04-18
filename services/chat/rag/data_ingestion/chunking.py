"""Preprocess and chunk raw documents for downstream indexing."""

from __future__ import annotations

from copy import deepcopy

from langchain_core.documents import Document


def _estimate_tokens(text: str) -> int:
    """Approximate token count without external tokenizer dependencies."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _split_text_with_overlap(text: str, size: int, overlap: int) -> list[str]:
    if not text:
        return []

    words = text.split()
    if not words:
        return []

    # Convert token budget to rough word budget (1 word ~ 1.3 tokens for VN/EN mixed text).
    words_per_chunk = max(1, int(size / 1.3))
    words_overlap = max(0, int(overlap / 1.3))
    step = max(1, words_per_chunk - words_overlap)

    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + words_per_chunk]
        if not window:
            break
        chunks.append(" ".join(window).strip())
        if start + words_per_chunk >= len(words):
            break
    return chunks


def _split_document(doc: Document, chunk_size: int, chunk_overlap: int) -> list[Document]:
    text = doc.page_content.strip()
    token_count = _estimate_tokens(text)

    metadata = dict(doc.metadata)
    source_type = str(metadata.get("source_type", "")).lower()
    content_type = str(metadata.get("content_type", "")).lower()
    is_table = source_type == "table_row" or content_type == "table"

    if is_table:
        target_size = 180
        target_overlap = int(target_size * 0.3)
    elif token_count < 250:
        metadata["token_count"] = token_count
        return [Document(page_content=text, metadata=metadata)]
    elif token_count <= 500:
        target_size = 350
        target_overlap = int(target_size * 0.5)
    else:
        target_size = chunk_size
        target_overlap = chunk_overlap

    parts = _split_text_with_overlap(text, target_size, target_overlap)
    if len(parts) <= 1:
        metadata["token_count"] = token_count
        return [Document(page_content=text, metadata=metadata)]

    chunked_docs: list[Document] = []
    for split_index, part in enumerate(parts):
        split_meta = deepcopy(metadata)
        split_meta["split_index"] = split_index
        split_meta["split_count"] = len(parts)
        split_meta["token_count"] = _estimate_tokens(part)
        chunked_docs.append(Document(page_content=part, metadata=split_meta))

    return chunked_docs


def _add_chunk_metadata(chunks: list[Document]) -> list[Document]:
    for index, chunk in enumerate(chunks):
        metadata = dict(chunk.metadata)
        metadata["chunk_index"] = index
        metadata["is_summary"] = bool(metadata.get("chunk_role") == "overview")
        chunk.metadata = metadata
    return chunks


def chunk_documents(
    documents: list[Document],
    chunk_size: int = 350,
    chunk_overlap: int = 105,
    use_semantic: bool = True,
) -> list[Document]:
    """Chunk documents using token-based rules aligned with ingestion spec."""

    if not documents:
        return []

    chunks: list[Document] = []
    for document in documents:
        chunks.extend(_split_document(document, chunk_size=chunk_size, chunk_overlap=chunk_overlap))

    chunks = _add_chunk_metadata(chunks)
    return chunks



