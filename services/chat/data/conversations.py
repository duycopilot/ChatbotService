"""Conversation service: CRUD conversation use-cases."""

from typing import Optional

import asyncpg

from models.exceptions import NotFoundError
from models.request import ConversationCreate, ConversationUpdate
from repositories import conversations as conversation_repo
from repositories import user as user_repo


async def create_conversation(conn: asyncpg.Connection, data: ConversationCreate) -> dict:
    if not data.title:
        data.title = "New Conversation"
    user = await user_repo.get_by_id(conn, data.user_id)
    if not user:
        raise NotFoundError(f"User {data.user_id} not found")
    return await conversation_repo.insert(conn, data.user_id, data.title)


async def list_conversations(conn: asyncpg.Connection, user_id: Optional[str] = None) -> list[dict]:
    return await conversation_repo.get_all(conn, user_id)


async def get_conversation(conn: asyncpg.Connection, conversation_id: str) -> dict:
    result = await conversation_repo.get_by_id(conn, conversation_id)
    if not result:
        raise NotFoundError(f"Conversation {conversation_id} not found")
    return result


async def update_conversation(
    conn: asyncpg.Connection,
    conversation_id: str,
    data: ConversationUpdate,
) -> dict:
    result = await conversation_repo.update(conn, conversation_id, data.title)
    if not result:
        raise NotFoundError(f"Conversation {conversation_id} not found")
    return result


async def delete_conversation(conn: asyncpg.Connection, conversation_id: str) -> None:
    deleted = await conversation_repo.delete(conn, conversation_id)
    if not deleted:
        raise NotFoundError(f"Conversation {conversation_id} not found")
