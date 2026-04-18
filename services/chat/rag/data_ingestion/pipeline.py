"""End-to-end data ingestion pipeline for RAG indexing."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from configs.config import settings
from services.observability import langfuse_client


def _load_callable(module_path: Path, callable_name: str):
	"""Load a callable from a file path without importing service package roots."""
	spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
	if spec is None or spec.loader is None:
		raise ImportError(f"Cannot import module from {module_path}")

	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	if not hasattr(module, callable_name):
		raise AttributeError(f"{callable_name} not found in {module_path}")
	return getattr(module, callable_name)


def run_data_ingestion_pipeline(
	chunk_size: int = settings.INGESTION_CHUNK_SIZE,
	chunk_overlap: int = settings.INGESTION_CHUNK_OVERLAP,
	embed_batch_size: int = settings.INGESTION_EMBED_BATCH_SIZE,
	qdrant_batch_size: int = settings.INGESTION_QDRANT_BATCH_SIZE,
	collection_name: str = settings.QDRANT_COLLECTION_NAME,
	qdrant_url: str | None = None,
	qdrant_api_key: str | None = None,
	distance: str = settings.INGESTION_QDRANT_DISTANCE,
	es_url: str | None = None,
	es_index_name: str = settings.ELASTICSEARCH_INDEX_NAME,
	es_batch_size: int = settings.INGESTION_ES_BATCH_SIZE,
) -> dict[str, Any]:
	"""Run parse -> semantic chunk -> embed -> index(Qdrant + Elasticsearch)."""
	langfuse_client.init()

	root = Path(__file__).parent

	ingest_documents = _load_callable(root / "parser.py", "ingest_documents")
	chunk_documents = _load_callable(root / "chunking.py", "chunk_documents")
	embed_chunks = _load_callable(root / "embedding.py", "embed_chunks")
	index_embedded_chunks_qdrant = _load_callable(
		root / "index.py", "index_embedded_chunks_qdrant"
	)
	index_embedded_chunks_elasticsearch = _load_callable(
		root / "index.py", "index_embedded_chunks_elasticsearch"
	)

	pipeline_input = {
		"chunk_size": chunk_size,
		"chunk_overlap": chunk_overlap,
		"embed_batch_size": embed_batch_size,
		"collection_name": collection_name,
		"es_index_name": es_index_name,
		"distance": distance,
	}

	with langfuse_client.trace_context(tags=["ingestion"], trace_name="data_ingestion"):
		with langfuse_client.span(
			"ingest_pipeline", as_type="chain", input=pipeline_input
		) as root_obs:

			with langfuse_client.span(
				"parse",
				as_type="span",
				input={"text_passages_csv": "data/raw_files/passage.csv", "tables_dir": "data/temp_files/flatten_tables"},
			) as obs:
				documents = ingest_documents()
				if obs:
					obs.update(output={"documents_count": len(documents)})

			with langfuse_client.span(
				"chunk",
				as_type="span",
				input={"documents_count": len(documents), "chunk_size": chunk_size, "chunk_overlap": chunk_overlap},
			) as obs:
				chunks = chunk_documents(
					documents=documents,
					chunk_size=chunk_size,
					chunk_overlap=chunk_overlap,
					use_semantic=True,
				)
				if obs:
					obs.update(output={"chunks_count": len(chunks)})

			with langfuse_client.span(
				"embed",
				as_type="span",
				input={"chunks_count": len(chunks), "batch_size": embed_batch_size},
			) as obs:
				embedded_chunks = embed_chunks(chunks=chunks, batch_size=embed_batch_size)
				if obs:
					embedding_dim = len(embedded_chunks[0]["embedding"]) if embedded_chunks else 0
					obs.update(output={"embedded_count": len(embedded_chunks), "embedding_dim": embedding_dim})

			with langfuse_client.span(
				"index_qdrant",
				as_type="span",
				input={"chunks_count": len(embedded_chunks), "collection_name": collection_name, "distance": distance},
			) as obs:
				qdrant_result = index_embedded_chunks_qdrant(
					embedded_chunks=embedded_chunks,
					collection_name=collection_name,
					qdrant_url=qdrant_url or settings.QDRANT_URL,
					qdrant_api_key=qdrant_api_key or settings.QDRANT_API_KEY,
					batch_size=qdrant_batch_size,
					distance=distance,
				)
				if obs:
					obs.update(output=qdrant_result)

			with langfuse_client.span(
				"index_elasticsearch",
				as_type="span",
				input={"chunks_count": len(embedded_chunks), "index_name": es_index_name},
			) as obs:
				es_result = index_embedded_chunks_elasticsearch(
					embedded_chunks=embedded_chunks,
					index_name=es_index_name,
					es_url=es_url or settings.ELASTICSEARCH_URL,
					batch_size=es_batch_size,
				)
				if obs:
					obs.update(output=es_result)

			result = {
				"documents": len(documents),
				"chunks": len(chunks),
				"embedded_chunks": len(embedded_chunks),
				"qdrant_result": qdrant_result,
				"es_result": es_result,
			}
			if root_obs:
				root_obs.update(output=result)

	langfuse_client.flush()
	return result


def main() -> None:
	parser = argparse.ArgumentParser(description="Run ingestion pipeline to Qdrant.")
	parser.add_argument("--run-id", type=str, default=None)
	parser.add_argument("--chunk-size", type=int, default=settings.INGESTION_CHUNK_SIZE)
	parser.add_argument("--chunk-overlap", type=int, default=settings.INGESTION_CHUNK_OVERLAP)
	parser.add_argument("--embed-batch-size", type=int, default=settings.INGESTION_EMBED_BATCH_SIZE)
	parser.add_argument("--qdrant-batch-size", type=int, default=settings.INGESTION_QDRANT_BATCH_SIZE)
	parser.add_argument("--collection-name", type=str, default=settings.QDRANT_COLLECTION_NAME)
	parser.add_argument("--qdrant-url", type=str, default=None)
	parser.add_argument("--qdrant-api-key", type=str, default=None)
	parser.add_argument("--distance", type=str, default=settings.INGESTION_QDRANT_DISTANCE)
	parser.add_argument("--es-url", type=str, default=None)
	parser.add_argument("--es-index-name", type=str, default=settings.ELASTICSEARCH_INDEX_NAME)
	parser.add_argument("--es-batch-size", type=int, default=settings.INGESTION_ES_BATCH_SIZE)
	parser.add_argument(
		"--output",
		type=str,
		default="/home/duynt/Refined_Chatbot/data/temp_files/ingestion_result.json",
	)
	args = parser.parse_args()
	run_id = args.run_id or f"run_{datetime.now().isoformat()}"

	result = run_data_ingestion_pipeline(
		chunk_size=args.chunk_size,
		chunk_overlap=args.chunk_overlap,
		embed_batch_size=args.embed_batch_size,
		qdrant_batch_size=args.qdrant_batch_size,
		collection_name=args.collection_name,
		qdrant_url=args.qdrant_url,
		qdrant_api_key=args.qdrant_api_key,
		distance=args.distance,
		es_url=args.es_url,
		es_index_name=args.es_index_name,
		es_batch_size=args.es_batch_size,
	)

	output_path = Path(args.output)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with output_path.open("w", encoding="utf-8") as output_file:
		json.dump(result, output_file, ensure_ascii=False, indent=2)

	print(json.dumps(result, ensure_ascii=False, indent=2))
	print(f"Saved result to: {output_path}")
	print(f"Run ID: {run_id}")
	print(f"Run logs: /home/duynt/Refined_Chatbot/logs/runs/{run_id}")


if __name__ == "__main__":
	main()
