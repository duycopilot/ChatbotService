"""Base contracts for chat short-term memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class MemoryTurn:
    """A single conversational turn used for short-term memory."""

    role: str
    content: str
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChatMemory(Protocol):
    """Interface for short-term memory backends."""

    async def get_context_with_summary(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Return prompt-ready memory context after token-aware summarization/truncation."""

    async def get_recent_context(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Backward-compatible alias of get_context_with_summary."""

    async def get_recent(self, conversation_id: str, limit: int = 12) -> list[MemoryTurn]:
        """Backward-compatible alias of get_context_with_summary."""

    async def add_turn(self, conversation_id: str, turn: MemoryTurn) -> None:
        """Append a turn to memory backend."""

    async def clear(self, conversation_id: str) -> None:
        """Clear all short-term turns for a conversation."""
