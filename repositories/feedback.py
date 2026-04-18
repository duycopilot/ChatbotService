"""
Purpose: Repository for feedback table
"""
import asyncpg
from typing import Optional


async def insert(conn: asyncpg.Connection, message_id: str, is_liked: bool, comment: Optional[str] = None) -> dict:
    sql = """
        INSERT INTO feedback (message_id, is_liked, comment)
        VALUES ($1::uuid, $2, $3)
        RETURNING *
    """
    row = await conn.fetchrow(sql, message_id, is_liked, comment)
    return dict(row)
