"""
Purpose: Repository for messages table
"""
import asyncpg
from typing import Optional


async def insert(conn: asyncpg.Connection, conversation_id: str, role: str, content: str, metadata: Optional[dict] = None) -> dict:
    sql = """
        INSERT INTO messages (conversation_id, role, content, metadata)
        VALUES ($1::uuid, $2, $3, $4::jsonb)
        RETURNING *
    """
    import json
    row = await conn.fetchrow(sql, conversation_id, role, content, json.dumps(metadata) if metadata else None)
    return dict(row)


async def get_by_conversation(conn: asyncpg.Connection, conversation_id: str) -> list[dict]:
    sql = """
        SELECT * FROM messages
        WHERE conversation_id = $1::uuid
        ORDER BY created_at ASC
    """
    rows = await conn.fetch(sql, conversation_id)
    return [dict(row) for row in rows]
