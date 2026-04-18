"""Feedback service: feedback use-cases."""

import asyncpg

from models.request import FeedbackCreate
from repositories import feedback as feedback_repo


async def create_feedback(conn: asyncpg.Connection, message_id: str, data: FeedbackCreate) -> dict:
    is_liked = data.type == "like"
    return await feedback_repo.insert(conn, message_id, is_liked, data.comment)
