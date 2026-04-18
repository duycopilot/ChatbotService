"""
Purpose: Intent classification via LLM
"""
from enum import Enum
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from services.chat.llm.prompt_builder import get_intent_classification_prompt
from services.chat.validators.intent import validate_intent_label
from services.observability import langfuse_client


class Intent(str, Enum):
    CHITCHAT = "chitchat"
    RAG      = "rag"
    ACTION   = "action"


async def classify(message: str, llm: ChatOpenAI, max_retries: int = 2) -> Intent:
    """
    Classify the user's message into one of: chitchat | rag | action.
    Retry when LLM returns an invalid label, then fallback to chitchat.
    """
    with langfuse_client.span(
        "classify_intent",
        as_type="chain",
        input={"message": message, "max_retries": max_retries},
    ):
        prompt = get_intent_classification_prompt(message)

        # total attempts = first try + max_retries
        attempts = max(1, max_retries + 1)
        for _ in range(attempts):
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            label = response.content

            is_valid, intent = validate_intent_label(label)
            if is_valid:
                return intent

        return Intent.CHITCHAT
