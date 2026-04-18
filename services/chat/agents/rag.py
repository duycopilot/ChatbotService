"""RAG agent adapter exposing the unified agent handler contract."""

from configs.config import settings
from services.chat.memory import MemoryTurn
from services.chat.agents.context import AgentContext
from services.chat.rag.query_pipeline.pipeline import handle as run_rag_pipeline


def _select_recent_turns(turns: list[MemoryTurn], limit: int = 4) -> list[MemoryTurn]:
    if limit <= 0:
        return []
    return turns[-limit:]


async def handle(message: str, context: AgentContext) -> str:
    recent_turns = _select_recent_turns(
        context.recent_turns,
        limit=settings.MEMORY_PROMPT_TURNS_LIMIT,
    )
    return await run_rag_pipeline(
        message=message,
        llm=context.llm,
        recent_turns=recent_turns,
        long_term_memories=context.long_term_memories,
    )
