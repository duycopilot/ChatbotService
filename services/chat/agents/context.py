"""Shared context object for agent handlers."""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg
from langchain_openai import ChatOpenAI

from services.chat.memory import MemoryTurn


@dataclass(slots=True)
class AgentContext:
    conn: asyncpg.Connection
    conversation_id: str
    llm: ChatOpenAI
    classifier_llm: ChatOpenAI
    recent_turns: list[MemoryTurn]
    long_term_memories: list[str] = field(default_factory=list)
