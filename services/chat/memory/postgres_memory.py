"""PostgreSQL implementation of chat short-term memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from services.chat.memory.base import ChatMemory, MemoryTurn
from services.chat.memory.token_aware import (
    TokenAwareMemoryManager,
    TokenBudget,
    HistorySummarizer,
)


class PostgresChatMemory(ChatMemory):
    """Short-term memory backend reading/writing from messages table."""

    def __init__(
        self,
        conn: asyncpg.Connection,
        include_roles: tuple[str, ...] = ("user", "assistant"),
        summary_llm=None,
        token_budget: TokenBudget | None = None,
        enable_summarization: bool = True,
        summarization_threshold: int = 2000,
        summary_prompt_template: str | None = None,
        tokenizer_model_name: str | None = None,
        tokenizer_strategy: str = "auto",
        hf_local_files_only: bool = True,
        keep_recent_turns: int = 2,
    ) -> None:
        self.conn = conn
        self.include_roles = include_roles
        
        # Token-aware memory management
        summarizer = HistorySummarizer(
            summary_llm=summary_llm,
            summary_prompt_template=summary_prompt_template,
            tokenizer_model_name=tokenizer_model_name,
            tokenizer_strategy=tokenizer_strategy,
            hf_local_files_only=hf_local_files_only,
        )
        self.token_manager = TokenAwareMemoryManager(
            token_budget=token_budget,
            summarizer=summarizer,
            summarization_threshold=summarization_threshold,
            keep_recent_turns=keep_recent_turns,
        )
        self.enable_summarization = enable_summarization

    async def get_context_with_summary(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Fetch recent memory from DB and apply token-aware summarization/truncation."""
        safe_limit = max(1, limit)
        sql = """
            SELECT role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1::uuid
              AND role = ANY($2::text[])
            ORDER BY created_at DESC
            LIMIT $3
        """
        rows = await self.conn.fetch(sql, conversation_id, list(self.include_roles), safe_limit)

        turns: list[MemoryTurn] = []
        for row in rows:
            metadata = row.get("metadata")
            created_at = row.get("created_at")
            turns.append(
                MemoryTurn(
                    role=row["role"],
                    content=row["content"],
                    metadata=self._normalize_metadata(metadata),
                    created_at=self._normalize_datetime(created_at),
                )
            )

        # Query is DESC for performance with LIMIT; reverse to oldest -> newest.
        turns.reverse()
        
        # Apply token-aware summarization if enabled
        if self.enable_summarization:
            turns = await self.token_manager.filter_turns(
                turns,
                max_turns=limit,
                apply_summarization=True,
            )
        
        return turns

    async def get_recent(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Backward-compatible alias for get_context_with_summary."""
        return await self.get_context_with_summary(conversation_id, limit)

    async def get_recent_context(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Backward-compatible alias for get_context_with_summary."""
        return await self.get_context_with_summary(conversation_id, limit)

    async def add_turn(self, conversation_id: str, turn: MemoryTurn) -> None:
        sql = """
            INSERT INTO messages (conversation_id, role, content, metadata)
            VALUES ($1::uuid, $2, $3, $4::jsonb)
        """
        await self.conn.execute(
            sql,
            conversation_id,
            turn.role,
            turn.content,
            self._normalize_metadata(turn.metadata),
        )

    async def clear(self, conversation_id: str) -> None:
        sql = """
            DELETE FROM messages
            WHERE conversation_id = $1::uuid
              AND role = ANY($2::text[])
        """
        await self.conn.execute(sql, conversation_id, list(self.include_roles))

    @staticmethod
    def _normalize_metadata(metadata: Any) -> dict[str, Any]:
        if isinstance(metadata, dict):
            return metadata
        return {}

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        return None
