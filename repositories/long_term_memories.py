"""Repository helpers for long-term memory records."""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


async def upsert(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    conversation_id: Optional[str],
    source_message_id: Optional[str],
    entity_type: str,
    entity_key: str,
    attribute_key: str,
    value_text: Optional[str],
    value_json: dict[str, Any] | list[Any] | None,
    canonical_value: str,
    unit: Optional[str],
    vector_id: str,
    category: str,
    clinical_status: Optional[str],
    verification_status: str,
    content: str,
    confidence: float,
    observed_at,
    is_active: bool = True,
    metadata: Optional[dict] = None,
) -> dict:
    sql = """
        INSERT INTO user_health_facts (
            user_id,
            conversation_id,
            source_message_id,
            entity_type,
            entity_key,
            attribute_key,
            value_text,
            value_json,
            canonical_value,
            unit,
            vector_id,
            category,
            clinical_status,
            verification_status,
            content,
            confidence,
            observed_at,
            is_active,
            metadata
        )
        VALUES (
            $1,
            $2::uuid,
            $3::uuid,
            $4,
            $5,
            $6,
            $7,
            $8::jsonb,
            $9,
            $10,
            $11::uuid,
            $12,
            $13,
            $14,
            $15,
            $16,
            $17,
            $18,
            $19::jsonb
        )
        ON CONFLICT (user_id, entity_type, entity_key, attribute_key, canonical_value)
        DO UPDATE SET
            conversation_id = COALESCE(EXCLUDED.conversation_id, user_health_facts.conversation_id),
            source_message_id = COALESCE(EXCLUDED.source_message_id, user_health_facts.source_message_id),
            value_text = COALESCE(EXCLUDED.value_text, user_health_facts.value_text),
            value_json = COALESCE(EXCLUDED.value_json, user_health_facts.value_json),
            unit = COALESCE(EXCLUDED.unit, user_health_facts.unit),
            vector_id = EXCLUDED.vector_id,
            category = EXCLUDED.category,
            clinical_status = COALESCE(EXCLUDED.clinical_status, user_health_facts.clinical_status),
            verification_status = COALESCE(EXCLUDED.verification_status, user_health_facts.verification_status),
            content = EXCLUDED.content,
            confidence = GREATEST(user_health_facts.confidence, EXCLUDED.confidence),
            observed_at = COALESCE(EXCLUDED.observed_at, user_health_facts.observed_at),
            is_active = EXCLUDED.is_active,
            metadata = COALESCE(user_health_facts.metadata, '{}'::jsonb) || EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP,
            last_accessed_at = CURRENT_TIMESTAMP
        RETURNING *
    """
    row = await conn.fetchrow(
        sql,
        user_id,
        conversation_id,
        source_message_id,
        entity_type,
        entity_key,
        attribute_key,
        value_text,
        json.dumps(value_json) if value_json is not None else None,
        canonical_value,
        unit,
        vector_id,
        category,
        clinical_status,
        verification_status,
        content,
        confidence,
        observed_at,
        is_active,
        json.dumps(metadata or {}),
    )
    return dict(row)


async def get_by_vector_ids(conn: asyncpg.Connection, vector_ids: list[str]) -> list[dict]:
    if not vector_ids:
        return []

    sql = """
        SELECT *
        FROM user_health_facts
        WHERE vector_id = ANY($1::uuid[])
          AND is_active = TRUE
    """
    rows = await conn.fetch(sql, vector_ids)
    by_vector_id = {str(row["vector_id"]): dict(row) for row in rows}
    return [by_vector_id[vector_id] for vector_id in vector_ids if vector_id in by_vector_id]


async def list_recent_by_user(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    limit: int,
) -> list[dict]:
    sql = """
        SELECT *
        FROM user_health_facts
                WHERE user_id = $1
                    AND is_active = TRUE
        ORDER BY COALESCE(last_accessed_at, updated_at, created_at) DESC
        LIMIT $2
    """
    rows = await conn.fetch(sql, user_id, limit)
    return [dict(row) for row in rows]


async def touch(conn: asyncpg.Connection, vector_ids: list[str]) -> None:
    if not vector_ids:
        return

    sql = """
        UPDATE user_health_facts
        SET last_accessed_at = CURRENT_TIMESTAMP
        WHERE vector_id = ANY($1::uuid[])
    """
    await conn.execute(sql, vector_ids)


async def deactivate_by_attribute(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    entity_type: str,
    entity_key: str,
    attribute_key: str,
    exclude_canonical_value: str | None = None,
) -> list[str]:
    sql = """
        UPDATE user_health_facts
        SET is_active = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = $1
          AND entity_type = $2
          AND entity_key = $3
          AND attribute_key = $4
          AND is_active = TRUE
          AND ($5::text IS NULL OR canonical_value <> $5)
        RETURNING vector_id
    """
    rows = await conn.fetch(
        sql,
        user_id,
        entity_type,
        entity_key,
        attribute_key,
        exclude_canonical_value,
    )
    return [str(row["vector_id"]) for row in rows]