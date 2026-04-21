"""Index embedded chunks into Qdrant and Elasticsearch."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from configs.config import settings


def _sanitize_payload(value: Any) -> Any:
	"""Convert payload values to Qdrant-safe scalar types."""
	if isinstance(value, (str, int, float, bool)) or value is None:
		return value
	return str(value)


def index_embedded_chunks_qdrant(
	embedded_chunks: list[dict],
	collection_name: str = "refined_chatbot_chunks",
	qdrant_url: str | None = None,
	qdrant_api_key: str | None = None,
	batch_size: int = 128,
	distance: str = "cosine",
) -> dict[str, Any]:
	"""Upsert embedded chunks into Qdrant collection.

	Expected chunk schema per item:
	- content or page_content: str
	- metadata: dict
	- embedding: list[float]
	"""
	if not embedded_chunks:
		return {
			"collection_name": collection_name,
			"qdrant_url": qdrant_url or settings.QDRANT_URL,
			"upserted": 0,
		}

	try:
		from qdrant_client import QdrantClient
		from qdrant_client.http.models import Distance, PointStruct, VectorParams
	except ImportError as exc:  # pragma: no cover
		raise ImportError(
			"qdrant-client is not installed. Install with: pip install qdrant-client"
		) from exc

	endpoint = qdrant_url or settings.QDRANT_URL
	api_key = qdrant_api_key or settings.QDRANT_API_KEY

	client = QdrantClient(url=endpoint, api_key=api_key)

	first_embedding = embedded_chunks[0].get("embedding")
	if not isinstance(first_embedding, list) or not first_embedding:
		raise ValueError("First embedded chunk has invalid embedding")
	vector_size = len(first_embedding)

	distance_map = {
		"cosine": Distance.COSINE,
		"dot": Distance.DOT,
		"euclid": Distance.EUCLID,
	}
	distance_metric = distance_map.get(distance.lower(), Distance.COSINE)

	collection_exists = client.collection_exists(collection_name=collection_name)
	if not collection_exists:
		client.create_collection(
			collection_name=collection_name,
			vectors_config=VectorParams(size=vector_size, distance=distance_metric),
		)

	upserted = 0
	for start in range(0, len(embedded_chunks), batch_size):
		batch = embedded_chunks[start : start + batch_size]
		points: list[PointStruct] = []

		for item in batch:
			embedding = item.get("embedding")
			if not isinstance(embedding, list) or not embedding:
				continue

			content = item.get("content") or item.get("page_content") or ""

			metadata = item.get("metadata", {}) or {}
			payload = {
				"content": content,
				"page_content": content,
				"metadata": {
					key: _sanitize_payload(value)
					for key, value in metadata.items()
				},
			}

			points.append(
				PointStruct(
					id=str(uuid4()),
					vector=embedding,
					payload=payload,
				)
			)

		if points:
			client.upsert(collection_name=collection_name, points=points)
			upserted += len(points)

	result = {
		"collection_name": collection_name,
		"qdrant_url": endpoint,
		"upserted": upserted,
	}
	return result


def index_embedded_chunks_elasticsearch(
	embedded_chunks: list[dict],
	index_name: str = "refined_chatbot_chunks",
	es_url: str | None = None,
	batch_size: int = 128,
	request_timeout: float = 60.0,
) -> dict[str, Any]:
	"""Bulk-index chunks into Elasticsearch for BM25 search.

	Expected chunk schema per item:
	- content or page_content: str
	- metadata: dict
	"""
	if not embedded_chunks:
		return {"index_name": index_name, "indexed": 0}

	try:
		from elasticsearch import Elasticsearch, __versionstr__ as es_client_version, helpers
	except ImportError as exc:
		raise ImportError(
			"elasticsearch is not installed. Install with: pip install elasticsearch"
		) from exc

	endpoint = es_url or settings.ELASTICSEARCH_URL
	client = Elasticsearch(
		endpoint,
		request_timeout=request_timeout,
		retry_on_timeout=True,
		max_retries=3,
	)

	try:
		server_info = client.info()
		server_version = str(server_info.get("version", {}).get("number", ""))
		server_major = int(server_version.split(".")[0]) if server_version else None
		client_major = int(str(es_client_version).split(".")[0])
		if server_major is not None and client_major != server_major:
			raise RuntimeError(
				"Elasticsearch client/server major version mismatch. "
				f"Client: {es_client_version}, Server: {server_version}. "
				"Please install elasticsearch package with matching major version "
				"(for Elasticsearch 8.x use: pip install 'elasticsearch>=8,<9')."
			)
	except ValueError as exc:
		raise RuntimeError("Unable to parse Elasticsearch version information") from exc

	if not client.indices.exists(index=index_name):
		client.indices.create(
			index=index_name,
			settings={"number_of_replicas": 0},
			mappings={
				"properties": {
					"content": {"type": "text", "analyzer": "standard"},
					"page_content": {"type": "text", "analyzer": "standard"},
					"metadata": {"type": "object", "dynamic": True},
				}
			},
			wait_for_active_shards="1",
		)

	indexed = 0
	for start in range(0, len(embedded_chunks), batch_size):
		batch = embedded_chunks[start : start + batch_size]
		actions = [
			{
				"_index": index_name,
				"_id": str(uuid4()),
				"_source": {
					"content": item.get("content") or item.get("page_content", ""),
					"page_content": item.get("content") or item.get("page_content", ""),
					"metadata": item.get("metadata", {}),
				},
			}
			for item in batch
		]
		_, errors = helpers.bulk(
			client,
			actions,
			raise_on_error=False,
			request_timeout=request_timeout,
		)
		if errors:
			raise RuntimeError(f"Elasticsearch bulk indexing errors: {errors}")
		indexed += len(actions)

	return {
		"index_name": index_name,
		"es_url": endpoint,
		"indexed": indexed,
		"request_timeout": request_timeout,
	}
