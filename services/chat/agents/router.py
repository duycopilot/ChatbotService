"""
Purpose: Route classified intent to the appropriate agent handler
"""
from collections.abc import Awaitable, Callable

from configs.config import settings
from services.chat.agents import action, chitchat, rag
from services.chat.agents.context import AgentContext
from services.chat.intent.classifier import Intent, classify


Handler = Callable[[str, AgentContext], Awaitable[str]]
HANDLERS: dict[Intent, Handler] = {
    Intent.CHITCHAT: chitchat.handle,
    Intent.RAG: rag.handle,
    Intent.ACTION: action.handle,
}


async def route(message: str, context: AgentContext) -> str:
    """
    Classify intent then dispatch to the matching agent.
    Returns assistant reply string.
    """
    intent = await classify(message, context.classifier_llm)
    print(f"Classified intent: {intent}")

    enabled = set(settings.ENABLED_INTENTS)
    if intent.value not in enabled:
        return await chitchat.handle(message, context)

    handler = HANDLERS.get(intent)
    if not handler:
        return await chitchat.handle(message, context)

    return await handler(message, context)
