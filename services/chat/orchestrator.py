"""Chat orchestration use-cases."""

import logging
import asyncpg
from fastapi import BackgroundTasks
from langchain_openai import ChatOpenAI

from configs.config import settings
from models.exceptions import NotFoundError
from models.request import MessageCreate
from repositories import conversations as conversation_repo
from services.chat.agents.context import AgentContext
from services.chat.agents.router import route
from services.chat.data import messages as message_service
from services.chat.llm.formatter import format_reply
from services.chat.llm.translator import translate_to_english, translate_to_vietnamese
from services.chat.memory import PostgresChatMemory
from services.chat.memory.long_term import LongTermMemoryService
from services.chat.memory.token_aware import TokenBudget
from services.observability import langfuse_client


logger = logging.getLogger(__name__)


def _turn_preview(turn, max_chars: int = 240) -> dict:
    return {
        "role": getattr(turn, "role", ""),
        "content": str(getattr(turn, "content", ""))[:max_chars],
    }


def _memory_preview(memory_record, max_chars: int = 240) -> dict:
    return {
        "attribute_key": getattr(memory_record, "attribute_key", None),
        "canonical_value": getattr(memory_record, "canonical_value", None),
        "confidence": getattr(memory_record, "confidence", None),
        "content": str(getattr(memory_record, "content", ""))[:max_chars],
    }


def _with_callback(llm: ChatOpenAI, handler) -> ChatOpenAI:
    """Return a copy of *llm* with Langfuse callback attached, or original."""
    if handler is None:
        return llm
    try:
        return llm.with_config(callbacks=[handler])
    except Exception:
        return llm


async def _remember_interaction_background(
    pool: asyncpg.Pool,
    summarizer_llm: ChatOpenAI,
    *,
    user_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    source_message_id: str | None,
) -> None:
    try:
        with langfuse_client.trace_context(
            user_id=str(user_id),
            session_id=str(conversation_id),
            tags=["chatbot", "memory", "background"],
            trace_name="memory_background",
        ):
            with langfuse_client.span(
                "memory_long_term_remember_background",
                as_type="chain",
                input={
                    "user_id": str(user_id),
                    "conversation_id": str(conversation_id),
                    "source_message_id": source_message_id,
                    "user_message": str(user_message)[:600],
                    "assistant_message": str(assistant_message)[:600],
                    "recent_turns_count": 0,
                    "extraction_mode": "query_only",
                },
            ) as obs:
                async with pool.acquire() as bg_conn:
                    long_term_memory = LongTermMemoryService(bg_conn, llm=summarizer_llm)
                    stored_memories = await long_term_memory.remember_interaction(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        user_message=user_message,
                        assistant_message=assistant_message,
                        recent_turns=[],
                        source_message_id=source_message_id,
                    )
                if obs is not None:
                    obs.update(
                        output={
                            "stored_count": len(stored_memories),
                            "stored_sample": [_memory_preview(memory) for memory in stored_memories[:3]],
                        }
                    )
    except Exception:
        logger.exception("Failed to save long-term memory in background task")


async def create_message(
    conn: asyncpg.Connection,
    pool: asyncpg.Pool,
    conversation_id: str,
    data: MessageCreate,
    llm: ChatOpenAI,
    classifier_llm: ChatOpenAI,
    summarizer_llm: ChatOpenAI,
    background_tasks: BackgroundTasks,
) -> dict:
    conversation = await conversation_repo.get_by_id(conn, conversation_id)
    if not conversation:
        raise NotFoundError(f"Conversation {conversation_id} not found")

    with langfuse_client.trace_context(
        user_id=str(conversation.get("user_id", "")),
        session_id=str(conversation_id),
        tags=["chatbot", "production"],
        trace_name="chat_request",
    ):
        with langfuse_client.span(
            "chat_request",
            as_type="chain",
            input={"conversation_id": str(conversation_id), "message": data.content},
        ):
            langfuse_client.set_trace_io(input=data.content)

            lf_handler = langfuse_client.get_langchain_handler()
            llm_traced = _with_callback(llm, lf_handler)
            classifier_llm_traced = _with_callback(classifier_llm, lf_handler)
            summarizer_llm_traced = _with_callback(summarizer_llm, lf_handler)

            # Normalize input language early so long-term memory extraction can
            # operate on stable English text regardless of user language.
            normalized_user_message = data.content
            if settings.TRANSLATE_INPUT_ENABLED:
                normalized_user_message = await translate_to_english(data.content, llm_traced)

            tokenizer_model_name = (
                settings.MEMORY_TOKENIZER_MODEL_NAME
                or getattr(llm, "model_name", None)
                or getattr(llm, "model", None)
                or settings.LLM_MODEL
            )

            memory = PostgresChatMemory(
                conn,
                summary_llm=summarizer_llm_traced,
                token_budget=TokenBudget(
                    context_window=settings.LLM_CONTEXT_WINDOW,
                    max_output_tokens=settings.LLM_MAX_TOKENS,
                    reserve_tokens=settings.MEMORY_SUMMARIZATION_RESERVE_TOKENS,
                ),
                enable_summarization=settings.MEMORY_SUMMARIZATION_ENABLED,
                summarization_threshold=settings.MEMORY_SUMMARIZATION_THRESHOLD_TOKENS,
                summary_prompt_template=settings.MEMORY_SUMMARY_PROMPT_TEMPLATE,
                tokenizer_model_name=tokenizer_model_name,
                tokenizer_strategy=settings.MEMORY_TOKENIZER_STRATEGY,
                hf_local_files_only=settings.MEMORY_TOKENIZER_HF_LOCAL_FILES_ONLY,
                keep_recent_turns=settings.MEMORY_SUMMARIZATION_KEEP_RECENT_TURNS,
            )
            with langfuse_client.span(
                "memory_short_term_prepare",
                as_type="chain",
                input={
                    "conversation_id": str(conversation_id),
                    "limit": settings.MEMORY_RECENT_TURNS_LIMIT,
                    "summarization_enabled": settings.MEMORY_SUMMARIZATION_ENABLED,
                },
                metadata={
                    "max_recent_turns": settings.MEMORY_RECENT_TURNS_LIMIT,
                    "summarization_enabled": settings.MEMORY_SUMMARIZATION_ENABLED,
                    "summarization_threshold_tokens": settings.MEMORY_SUMMARIZATION_THRESHOLD_TOKENS,
                    "keep_recent_turns": settings.MEMORY_SUMMARIZATION_KEEP_RECENT_TURNS,
                },
            ) as memory_obs:
                recent_turns = await memory.get_context_with_summary(
                    conversation_id,
                    limit=settings.MEMORY_RECENT_TURNS_LIMIT,
                )
                if memory_obs is not None:
                    memory_obs.update(
                        output={
                            "recent_turns_count": len(recent_turns),
                            "recent_turns_sample": [_turn_preview(turn) for turn in recent_turns[-3:]],
                        }
                    )

            long_term_memory = LongTermMemoryService(conn, llm=summarizer_llm_traced)
            with langfuse_client.span(
                "memory_long_term_retrieve",
                as_type="retriever",
                input={
                    "user_id": str(conversation["user_id"]),
                    "query": str(normalized_user_message)[:600],
                    "provider": settings.LONG_TERM_MEMORY_PROVIDER,
                    "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                    "top_k": settings.LONG_TERM_MEMORY_TOP_K,
                },
                metadata={
                    "provider": settings.LONG_TERM_MEMORY_PROVIDER,
                    "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                    "top_k": settings.LONG_TERM_MEMORY_TOP_K,
                },
            ) as ltm_obs:
                try:
                    retrieved_memories = await long_term_memory.retrieve(
                        user_id=conversation["user_id"],
                        query=normalized_user_message,
                    )
                except Exception as exc:
                    retrieved_memories = []
                    if ltm_obs is not None:
                        ltm_obs.update(output={"retrieved_count": 0, "error": str(exc)[:400]})
                else:
                    if ltm_obs is not None:
                        ltm_obs.update(
                            output={
                                "retrieved_count": len(retrieved_memories),
                                "retrieved_sample": [_memory_preview(memory) for memory in retrieved_memories[:3]],
                            }
                        )

            await message_service.create_user_message(conn, conversation_id, data)

            context = AgentContext(
                conn=conn,
                conversation_id=conversation_id,
                llm=llm_traced,
                classifier_llm=classifier_llm_traced,
                recent_turns=recent_turns,
                long_term_memories=[memory.content for memory in retrieved_memories],
            )
            raw_reply = await route(message=data.content, context=context)
            assistant_reply = format_reply(raw_reply)
            if settings.TRANSLATE_OUTPUT_ENABLED:
                assistant_reply = await translate_to_vietnamese(assistant_reply, llm_traced)

            assistant_message = await message_service.create_assistant_message(
                conn,
                conversation_id,
                assistant_reply,
            )

            langfuse_client.set_trace_io(output=assistant_reply)

            background_tasks.add_task(
                _remember_interaction_background,
                pool,
                summarizer_llm_traced,
                user_id=conversation["user_id"],
                conversation_id=str(conversation["id"]),
                user_message=normalized_user_message,
                assistant_message=assistant_reply,
                source_message_id=str(assistant_message.get("id")),
            )

            return assistant_message
