# chat api
from fastapi import APIRouter, BackgroundTasks, Depends, Request
import asyncpg
from langchain_openai import ChatOpenAI
from uuid import UUID
from models.request import ConversationCreate, ConversationUpdate, FeedbackCreate, MessageCreate, UserCreate, UserUpdate
from api.dependencies import get_classifier_llm, get_db, get_llm, get_summarizer_llm
from services.chat.data import conversations as conversation_service
from services.chat.data import feedback as feedback_service
from services.chat.data import messages as message_service
from services.chat.data import users as user_service
from services.chat import orchestrator as chat_orchestrator

router = APIRouter(prefix="", tags=["Chat"])


# Users
@router.post("/users", status_code=201)
async def create_user(data: UserCreate, conn: asyncpg.Connection = Depends(get_db)):
    return await user_service.create_user(conn, data)


@router.get("/users", status_code=200)
async def list_users(conn: asyncpg.Connection = Depends(get_db)):
    return await user_service.list_users(conn)


@router.get("/users/{user_id}", status_code=200)
async def get_user(user_id: str, conn: asyncpg.Connection = Depends(get_db)):
    # TODO: validate user_id format if user IDs should follow a specific schema
    return await user_service.get_user(conn, user_id)


@router.patch("/users/{user_id}", status_code=200)
async def update_user(user_id: str, data: UserUpdate, conn: asyncpg.Connection = Depends(get_db)):
    # TODO: validate user_id format if user IDs should follow a specific schema
    return await user_service.update_user(conn, user_id, data)


# Conversation
@router.post("/conversations", status_code=201)
async def create_conversation(data: ConversationCreate, conn: asyncpg.Connection = Depends(get_db)):
    return await conversation_service.create_conversation(conn, data)


@router.get("/conversations", status_code=200)
async def list_conversations(user_id: str = None, conn: asyncpg.Connection = Depends(get_db)):
    return await conversation_service.list_conversations(conn, user_id)


@router.get("/conversations/{conversation_id}", status_code=200)
async def get_conversation(conversation_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    return await conversation_service.get_conversation(conn, str(conversation_id))


@router.patch("/conversations/{conversation_id}", status_code=200)
async def update_conversation(conversation_id: UUID, data: ConversationUpdate, conn: asyncpg.Connection = Depends(get_db)):
    return await conversation_service.update_conversation(conn, str(conversation_id), data)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    await conversation_service.delete_conversation(conn, str(conversation_id))


# Message
@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def create_message(
    request: Request,
    conversation_id: UUID,
    data: MessageCreate,
    background_tasks: BackgroundTasks,
    conn: asyncpg.Connection = Depends(get_db),
    llm: ChatOpenAI = Depends(get_llm),
    classifier_llm: ChatOpenAI = Depends(get_classifier_llm),
    summarizer_llm: ChatOpenAI = Depends(get_summarizer_llm),
):
    return await chat_orchestrator.create_message(
        conn,
        request.app.state.pool,
        str(conversation_id),  # Convert back to string for downstream
        data,
        llm,
        classifier_llm,
        summarizer_llm,
        background_tasks,
    )


@router.get("/conversations/{conversation_id}/messages", status_code=200)
async def list_messages(conversation_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    return await message_service.list_messages(conn, str(conversation_id))


# Feedback
@router.post("/messages/{message_id}/feedback", status_code=201)
async def create_feedback(message_id: UUID, data: FeedbackCreate, conn: asyncpg.Connection = Depends(get_db)):
    return await feedback_service.create_feedback(conn, str(message_id), data)


