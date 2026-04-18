"""Language normalization helpers for chat input."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from services.observability import langfuse_client

logger = logging.getLogger(__name__)


def _coerce_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


async def translate_to_english(text: str, llm) -> str:
    """Translate user text to English for downstream normalization.

    If the text is already English, return it unchanged. On any LLM error,
    fall back to the original input to keep the pipeline resilient.
    """
    source = str(text or "").strip()
    if not source:
        return source
    if llm is None:
        return source

    with langfuse_client.span(
        "translate_into_english",
        as_type="generation",
        input={"text": source},
    ) as obs:
        invoke_llm = llm
        try:
            invoke_llm = llm.with_config(run_name="translate_into_english")
        except Exception:
            pass

        try:
            response = await invoke_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "Translate the user message into natural English. "
                            "If it is already English, return it unchanged. "
                            "Respond with plain text only."
                        )
                    ),
                    HumanMessage(content=source),
                ]
            )
        except Exception:
            logger.exception("Input translation failed; using original text")
            return source

    translated = _coerce_text(getattr(response, "content", "")).strip()
    if obs is not None:
        obs.update(output={"translated_text": translated or source})
    return translated or source


async def translate_to_vietnamese(text: str, llm) -> str:
    """Translate assistant output to Vietnamese.

    If the text is already Vietnamese, return it unchanged. On any LLM error,
    fall back to the original output so responses are never blocked.
    """
    source = str(text or "").strip()
    if not source:
        return source
    if llm is None:
        return source

    with langfuse_client.span(
        "translate_into_vietnamese",
        as_type="generation",
        input={"text": source},
    ) as obs:
        invoke_llm = llm
        try:
            invoke_llm = llm.with_config(run_name="translate_into_vietnamese")
        except Exception:
            pass

        try:
            response = await invoke_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "Translate the assistant response into natural Vietnamese. "
                            "If it is already Vietnamese, return it unchanged. "
                            "Respond with plain text only."
                        )
                    ),
                    HumanMessage(content=source),
                ]
            )
        except Exception:
            logger.exception("Output translation failed; using original text")
            return source

    translated = _coerce_text(getattr(response, "content", "")).strip()
    if obs is not None:
        obs.update(output={"translated_text": translated or source})
    return translated or source
