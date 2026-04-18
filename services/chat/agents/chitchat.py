"""
Purpose: Chitchat agent — direct LLM call, no retrieval needed
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from configs.config import settings
from services.chat.agents.context import AgentContext
from services.chat.llm.prompt_builder import get_chitchat_system_prompt
from services.chat.memory import MemoryTurn


def _select_recent_turns(turns: list[MemoryTurn], limit: int = 4) -> list[MemoryTurn]:
    if limit <= 0:
        return []
    return turns[-limit:]


def _build_history_messages(context: AgentContext, max_turns: int = 4) -> list[HumanMessage | AIMessage]:
    history: list[HumanMessage | AIMessage] = []
    selected_turns = _select_recent_turns(context.recent_turns, limit=max_turns)
    for turn in selected_turns:
        content = str(turn.content).strip()
        if not content:
            continue

        role = str(turn.role).strip().lower()
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "assistant":
            history.append(AIMessage(content=content))

    return history


async def handle(message: str, context: AgentContext) -> str:
    history_messages = _build_history_messages(
        context,
        max_turns=settings.MEMORY_PROMPT_TURNS_LIMIT,
    )
    messages = [
        SystemMessage(content=get_chitchat_system_prompt(context.long_term_memories)),
        *history_messages,
        HumanMessage(content=message),
    ]
    response = await context.llm.ainvoke(messages)
    return response.content
