"""Post-processing utilities for retrieval results."""

from __future__ import annotations

import hashlib
from typing import Any


def _stable_doc_id(doc: dict[str, Any]) -> str:
	"""Build stable doc id shared across semantic and BM25 results.

	Priority:
	1. explicit doc_id / id in payload
	2. metadata key (source + chunk_index)
	3. hash(page_content)
	"""
	explicit = doc.get("doc_id") or doc.get("id")
	if explicit:
		return str(explicit)

	metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
	source = metadata.get("source")
	chunk_index = metadata.get("chunk_index")
	if source is not None and chunk_index is not None:
		return f"{source}::{chunk_index}"

	content = doc.get("page_content") or doc.get("content") or doc.get("text") or ""
	digest = hashlib.sha1(str(content).encode("utf-8")).hexdigest()[:20]
	return f"content::{digest}"


def _extract_content(doc: dict[str, Any]) -> str:
	return (
		doc.get("page_content")
		or doc.get("content")
		or doc.get("text")
		or ""
	)


def merge_semantic_bm25_results(
	semantic_results: list[dict[str, Any]],
	bm25_results: list[dict[str, Any]],
	semantic_weight: float = 0.5,
	bm25_weight: float = 0.5,
	final_top_k: int | None = None,
) -> list[dict[str, Any]]:
	"""Merge two ranked lists using weighted reciprocal-rank scoring.

	Score formula per document id:
	- semantic contribution: semantic_weight * (1 / (semantic_rank + 1))
	- bm25 contribution: bm25_weight * (1 / (bm25_rank + 1))
	"""
	semantic_doc_ids = [_stable_doc_id(doc) for doc in semantic_results]
	bm25_doc_ids = [_stable_doc_id(doc) for doc in bm25_results]

	semantic_index_map = {doc_id: idx for idx, doc_id in enumerate(semantic_doc_ids)}
	bm25_index_map = {doc_id: idx for idx, doc_id in enumerate(bm25_doc_ids)}

	combined_ids = list(dict.fromkeys(semantic_doc_ids + bm25_doc_ids))

	combined_nodes: list[dict[str, Any]] = []
	semantic_count = 0
	bm25_count = 0
	both_count = 0

	for doc_id in combined_ids:
		score = 0.0
		content = ""
		base_doc: dict[str, Any] = {}

		if doc_id in semantic_index_map:
			index = semantic_index_map[doc_id]
			score += semantic_weight * (1.0 / (index + 1))
			base_doc = dict(semantic_results[index])
			content = _extract_content(base_doc)
			semantic_count += 1

		if doc_id in bm25_index_map:
			index = bm25_index_map[doc_id]
			score += bm25_weight * (1.0 / (index + 1))
			bm25_doc = bm25_results[index]

			if not content:
				content = _extract_content(bm25_doc)
				if not base_doc:
					base_doc = dict(bm25_doc)

			if not base_doc:
				base_doc = dict(bm25_doc)
			bm25_count += 1

		if doc_id in semantic_index_map and doc_id in bm25_index_map:
			both_count += 1

		merged_doc = dict(base_doc)
		merged_doc["doc_id"] = doc_id
		merged_doc["page_content"] = content
		merged_doc["score"] = score
		merged_doc["hybrid_score"] = score
		merged_doc["in_semantic"] = doc_id in semantic_index_map
		merged_doc["in_bm25"] = doc_id in bm25_index_map

		combined_nodes.append(merged_doc)

	combined_nodes.sort(key=lambda item: item.get("hybrid_score", 0.0), reverse=True)
	if final_top_k is not None and final_top_k > 0:
		combined_nodes = combined_nodes[:final_top_k]
	for rank, doc in enumerate(combined_nodes, start=1):
		doc["hybrid_rank"] = rank

	# Expose counters for quick debugging in caller logs if needed.
	if combined_nodes:
		combined_nodes[0]["_merge_stats"] = {
			"semantic_count": semantic_count,
			"bm25_count": bm25_count,
			"both_count": both_count,
			"combined_count": len(combined_nodes),
			"semantic_weight": semantic_weight,
			"bm25_weight": bm25_weight,
		}

	return combined_nodes