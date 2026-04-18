"""Long-term memory orchestration using Postgres and Qdrant."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import asyncpg

from configs.config import settings
from integrations.embeds.openai import get_openai_embeddings
from repositories import long_term_memories as long_term_memory_repo
from services.chat.memory import MemoryTurn
from services.chat.memory.long_term.extractor import LongTermMemoryExtractor
from services.chat.memory.long_term.models import LongTermMemoryCandidate, LongTermMemoryRecord


_MUTABLE_FACT_ATTRIBUTE_KEYS = {
    "blood_pressure",
    "heart_rate",
    "respiratory_rate",
    "temperature",
    "spo2",
    "oxygen_saturation",
    "blood_sugar",
    "glucose_level",
    "weight",
    "weight_change",
    "bmi",
    "pain_score",
}

_SINGLETON_ATTRIBUTE_KEYS = {
    "communication_preference",
    "preferred_name",
}


class LongTermMemoryService:
    def __init__(self, conn: asyncpg.Connection, llm=None) -> None:
        self.conn = conn
        self.enabled = settings.LONG_TERM_MEMORY_ENABLED
        self.collection_name = settings.LONG_TERM_MEMORY_COLLECTION_NAME
        self.top_k = settings.LONG_TERM_MEMORY_TOP_K
        self.fallback_limit = settings.LONG_TERM_MEMORY_FALLBACK_LIMIT
        self.extractor = LongTermMemoryExtractor(
            llm=llm,
            prompt_template=settings.LONG_TERM_MEMORY_EXTRACTION_PROMPT_TEMPLATE,
            max_items=settings.LONG_TERM_MEMORY_MAX_WRITE_ITEMS,
            min_confidence=settings.LONG_TERM_MEMORY_MIN_CONFIDENCE,
            max_content_chars=settings.LONG_TERM_MEMORY_MAX_CONTENT_CHARS,
        )

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
    ) -> list[LongTermMemoryRecord]:
        if not self.enabled:
            return []

        if not user_id:
            raise ValueError("Long-term memory requires user_id")
        vector_ids: list[str] = []
        try:
            vector_ids = await asyncio.to_thread(
                self._search_vector_ids,
                query=query,
                user_id=user_id,
                top_k=self.top_k,
            )
        except Exception:
            vector_ids = []

        if vector_ids:
            rows = await long_term_memory_repo.get_by_vector_ids(self.conn, vector_ids)
            await long_term_memory_repo.touch(self.conn, vector_ids)
        else:
            rows = await long_term_memory_repo.list_recent_by_user(
                self.conn,
                user_id=user_id,
                limit=self.fallback_limit,
            )

        return [self._row_to_record(row) for row in rows]

    async def remember_interaction(
        self,
        *,
        user_id: str,
        conversation_id: str | None = None,
        user_message: str,
        assistant_message: str,
        recent_turns: list[MemoryTurn] | None = None,
        source_message_id: str | None = None,
    ) -> list[LongTermMemoryRecord]:
        if not self.enabled:
            return []

        candidates = await self.extractor.extract(
            user_message=user_message,
            assistant_message=assistant_message,
            recent_turns=recent_turns or [],
        )
        if not candidates:
            return []

        conversation_id = self._normalize_optional_text(conversation_id)

        contents = [candidate.content for candidate in candidates]
        vectors = await asyncio.to_thread(self._embed_texts, contents)

        stored_rows: list[dict[str, Any]] = []
        vector_payloads: list[dict[str, Any]] = []
        vectors_to_deactivate: set[str] = set()
        for candidate, vector in zip(candidates, vectors, strict=False):
            if self._should_overwrite_attribute(candidate.attribute_key):
                deactivated = await long_term_memory_repo.deactivate_by_attribute(
                    self.conn,
                    user_id=user_id,
                    entity_type=candidate.entity_type,
                    entity_key=candidate.entity_key,
                    attribute_key=candidate.attribute_key,
                    exclude_canonical_value=candidate.canonical_value,
                )
                vectors_to_deactivate.update(deactivated)

            vector_id = self._build_vector_id(user_id, candidate)
            row = await long_term_memory_repo.upsert(
                self.conn,
                user_id=user_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                entity_type=candidate.entity_type,
                entity_key=candidate.entity_key,
                attribute_key=candidate.attribute_key,
                value_text=candidate.value_text,
                value_json=candidate.value_json,
                canonical_value=candidate.canonical_value,
                unit=candidate.unit,
                vector_id=vector_id,
                category=candidate.category,
                clinical_status=candidate.clinical_status,
                verification_status=candidate.verification_status,
                content=candidate.content,
                confidence=candidate.confidence,
                observed_at=candidate.observed_at,
                metadata=candidate.metadata,
            )
            stored_rows.append(row)
            vector_payloads.append(
                {
                    "id": vector_id,
                    "vector": vector,
                    "payload": {
                        "vector_id": vector_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "entity_type": candidate.entity_type,
                        "entity_key": candidate.entity_key,
                        "attribute_key": candidate.attribute_key,
                        "canonical_value": candidate.canonical_value,
                        "category": candidate.category,
                        "clinical_status": candidate.clinical_status,
                        "verification_status": candidate.verification_status,
                        "content": candidate.content,
                        "confidence": candidate.confidence,
                        "is_active": True,
                    },
                }
            )

        try:
            await asyncio.to_thread(self._upsert_vectors, vector_payloads)
        except Exception:
            pass

        if vectors_to_deactivate:
            try:
                await asyncio.to_thread(self._deactivate_vectors, list(vectors_to_deactivate))
            except Exception:
                pass

        return [self._row_to_record(row) for row in stored_rows]

    @staticmethod
    def _should_overwrite_attribute(attribute_key: str) -> bool:
        normalized = str(attribute_key).strip().lower()
        return normalized in _MUTABLE_FACT_ATTRIBUTE_KEYS or normalized in _SINGLETON_ATTRIBUTE_KEYS

    @staticmethod
    def _normalize_optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _build_vector_id(user_id: str, candidate: LongTermMemoryCandidate) -> str:
        identity = "|".join(
            [
                user_id,
                candidate.entity_type,
                candidate.entity_key,
                candidate.attribute_key,
                candidate.canonical_value,
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> LongTermMemoryRecord:
        return LongTermMemoryRecord(
            id=str(row["id"]),
            user_id=LongTermMemoryService._normalize_optional_text(row.get("user_id")) or "",
            conversation_id=LongTermMemoryService._normalize_optional_text(row.get("conversation_id")),
            source_message_id=LongTermMemoryService._normalize_optional_text(row.get("source_message_id")),
            entity_type=str(row.get("entity_type") or "patient"),
            entity_key=str(row.get("entity_key") or "self"),
            attribute_key=str(row.get("attribute_key") or "general_fact"),
            value_text=LongTermMemoryService._normalize_optional_text(row.get("value_text")),
            value_json=row.get("value_json") if isinstance(row.get("value_json"), (dict, list)) else None,
            canonical_value=str(row.get("canonical_value") or ""),
            unit=LongTermMemoryService._normalize_optional_text(row.get("unit")),
            vector_id=str(row["vector_id"]),
            category=str(row.get("category") or "general"),
            clinical_status=LongTermMemoryService._normalize_optional_text(row.get("clinical_status")),
            verification_status=str(row.get("verification_status") or "self_reported"),
            content=str(row.get("content") or ""),
            confidence=float(row.get("confidence") or 0.0),
            observed_at=row.get("observed_at"),
            is_active=bool(row.get("is_active", True)),
            metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_accessed_at=row.get("last_accessed_at"),
        )

    @staticmethod
    def _embed_texts(texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = get_openai_embeddings()
        return embeddings.embed_documents(texts)

    def _search_vector_ids(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int,
    ) -> list[str]:
        client, rest = self._get_qdrant_client()
        if not self._collection_exists(client):
            return []

        embeddings = get_openai_embeddings()
        query_vector = embeddings.embed_query(query)
        query_filter = rest.Filter(
            must=[
                rest.FieldCondition(key="user_id", match=rest.MatchValue(value=user_id)),
                rest.FieldCondition(key="is_active", match=rest.MatchValue(value=True)),
            ]
        )

        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
            hits = list(getattr(response, "points", []) or [])
        else:
            hits = client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )

        vector_ids: list[str] = []
        for hit in hits:
            payload = getattr(hit, "payload", None) or {}
            vector_id = payload.get("vector_id") or str(getattr(hit, "id", "")).strip()
            if vector_id:
                vector_ids.append(str(vector_id))
        return vector_ids

    def _upsert_vectors(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return

        client, rest = self._get_qdrant_client()
        self._ensure_collection(client, rest)
        points = [
            rest.PointStruct(id=item["id"], vector=item["vector"], payload=item["payload"])
            for item in items
        ]
        client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def _deactivate_vectors(self, vector_ids: list[str]) -> None:
        if not vector_ids:
            return
        client, _ = self._get_qdrant_client()
        if not self._collection_exists(client):
            return

        try:
            client.set_payload(
                collection_name=self.collection_name,
                payload={"is_active": False},
                points=vector_ids,
                wait=True,
            )
        except TypeError:
            # Compatibility fallback for older qdrant-client signatures.
            client.set_payload(
                self.collection_name,
                {"is_active": False},
                vector_ids,
                wait=True,
            )

    def _ensure_collection(self, client, rest) -> None:
        if self._collection_exists(client):
            return

        client.create_collection(
            collection_name=self.collection_name,
            vectors_config=rest.VectorParams(
                size=settings.EMBEDDINGS_DIMENSION,
                distance=rest.Distance.COSINE,
            ),
        )

    def _collection_exists(self, client) -> bool:
        if hasattr(client, "collection_exists"):
            return bool(client.collection_exists(self.collection_name))
        collections = client.get_collections()
        return any(collection.name == self.collection_name for collection in collections.collections)

    @staticmethod
    def _get_qdrant_client():
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as rest
        except ImportError as exc:  # pragma: no cover
            raise ImportError("qdrant-client is not installed") from exc

        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        return client, rest