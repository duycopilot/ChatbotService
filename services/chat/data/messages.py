"""Message service: message persistence and retrieval use-cases."""

import asyncpg

from models.request import MessageCreate
from repositories import messages as message_repo


async def create_user_message(
    conn: asyncpg.Connection,
    conversation_id: str,
    data: MessageCreate,
) -> dict:
    return await message_repo.insert(conn, conversation_id, "user", data.content)


async def create_assistant_message(
    conn: asyncpg.Connection,
    conversation_id: str,
    content: str,
) -> dict:
    return await message_repo.insert(conn, conversation_id, "assistant", content)


async def list_messages(conn: asyncpg.Connection, conversation_id: str) -> list[dict]:
    return await message_repo.get_by_conversation(conn, conversation_id)
