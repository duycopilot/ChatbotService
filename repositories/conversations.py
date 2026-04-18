"""
Purpose: Repository for conversations table
"""
import asyncpg
from typing import Optional


async def insert(conn: asyncpg.Connection, user_id: Optional[str], title: Optional[str]) -> dict:
    sql = """
        INSERT INTO conversations (user_id, title)
        VALUES ($1, $2)
        RETURNING *
    """
    row = await conn.fetchrow(sql, user_id, title)
    return dict(row)


async def get_all(conn: asyncpg.Connection, user_id: Optional[str] = None) -> list[dict]:
    if user_id:
        sql = """
            SELECT
                c.id,
                c.user_id,
                c.title,
                c.created_at,
                c.updated_at,
                COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.user_id = $1
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """
        rows = await conn.fetch(sql, user_id)
    else:
        sql = """
            SELECT
                c.id,
                c.user_id,
                c.title,
                c.created_at,
                c.updated_at,
                COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """
        rows = await conn.fetch(sql)
    return [dict(row) for row in rows]


async def get_by_id(conn: asyncpg.Connection, conversation_id: str) -> Optional[dict]:
    sql = "SELECT * FROM conversations WHERE id = $1::uuid"
    row = await conn.fetchrow(sql, conversation_id)
    return dict(row) if row else None


async def update(conn: asyncpg.Connection, conversation_id: str, title: str) -> Optional[dict]:
    sql = """
        UPDATE conversations
        SET title = $1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $2::uuid
        RETURNING *
    """
    row = await conn.fetchrow(sql, title, conversation_id)
    return dict(row) if row else None


async def delete(conn: asyncpg.Connection, conversation_id: str) -> bool:
    sql = "DELETE FROM conversations WHERE id = $1::uuid"
    result = await conn.execute(sql, conversation_id)
    # result format: "DELETE <count>"
    return result.split()[-1] != "0"
