"""
Purpose: Build prompts for each flow (intent classification, chitchat, RAG)
"""
from configs.config import settings


def _format_memory_section(memories: list[str] | None) -> str:
    if not memories:
        return ""

    lines = [f"- {memory.strip()}" for memory in memories if str(memory).strip()]
    if not lines:
        return ""

    return "Known user context:\n" + "\n".join(lines)


def _build_intent_prompt(message: str) -> str:
    enabled = [intent for intent in settings.ENABLED_INTENTS if intent in settings.INTENT_DESCRIPTIONS]
    if not enabled:
        enabled = ["chitchat"]

    labels = ", ".join(enabled)
    intent_lines = "\n".join(
        f"- {intent}: {settings.INTENT_DESCRIPTIONS[intent]}"
        for intent in enabled
    )
    return settings.INTENT_PROMPT_TEMPLATE.format(
        intent_lines=intent_lines,
        labels=labels,
        message=message,
    )


def get_intent_classification_prompt(message: str) -> str:
    """Build local intent classification prompt."""
    return _build_intent_prompt(message)


def get_chitchat_system_prompt(memories: list[str] | None = None) -> str:
    """Return local chitchat system prompt."""
    memory_section = _format_memory_section(memories)
    if not memory_section:
        return settings.CHITCHAT_SYSTEM_PROMPT_TEMPLATE
    return f"{settings.CHITCHAT_SYSTEM_PROMPT_TEMPLATE}\n\n{memory_section}"


def build_rag_prompt(query: str, documents: list[dict], memories: list[str] | None = None) -> list[dict]:
    context = "\n\n".join(
        f"[{i+1}] {doc.get('page_content') or doc.get('content', '')}" for i, doc in enumerate(documents)
    )
    memory_section = _format_memory_section(memories)
    if memory_section:
        system = f"{settings.RAG_SYSTEM_PROMPT_TEMPLATE}\n\n{memory_section}\n\nContext:\n{context}"
    else:
        system = f"{settings.RAG_SYSTEM_PROMPT_TEMPLATE}\n\nContext:\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": query},
    ]
