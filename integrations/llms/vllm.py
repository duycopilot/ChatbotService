"""
Purpose: vLLM client via LangChain + OpenAI-compatible API
Server: meta-llama/Meta-Llama-3-8B-Instruct on port 8380
"""
from langchain_openai import ChatOpenAI
from configs.config import settings


def create_llm(profile: str = "primary", **overrides) -> ChatOpenAI:
    """
    Factory: trả về ChatOpenAI instance trỏ vào vLLM server.
    Truyền overrides để ghi đè temperature, max_tokens, v.v.
    """
    if profile == "classifier":
        temperature = settings.CLASSIFIER_TEMPERATURE
        max_tokens = settings.CLASSIFIER_MAX_TOKENS
        model = settings.CLASSIFIER_MODEL
        base_url = settings.CLASSIFIER_BASE_URL
        api_key = settings.CLASSIFIER_API_KEY
    elif profile == "summarizer":
        temperature = settings.SUMMARIZER_TEMPERATURE
        max_tokens = settings.SUMMARIZER_MAX_TOKENS
        model = settings.SUMMARIZER_MODEL
        base_url = settings.SUMMARIZER_BASE_URL
        api_key = settings.SUMMARIZER_API_KEY
    else:
        temperature = settings.LLM_TEMPERATURE
        max_tokens = settings.LLM_MAX_TOKENS
        model = settings.LLM_MODEL
        base_url = settings.LLM_BASE_URL
        api_key = settings.LLM_API_KEY

    return ChatOpenAI(
        model=overrides.get("model", model),
        base_url=overrides.get("base_url", base_url),
        api_key=overrides.get("api_key", api_key),
        temperature=overrides.get("temperature", temperature),
        max_tokens=overrides.get("max_tokens", max_tokens),
    )
