"""Purpose: Read general config from config.yaml and AI config from ai_config.yaml."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_AI_CONFIG_PATH = Path(__file__).parent / "ai_config.yaml"
_ENV_PATH = _CONFIG_PATH.parent.parent / ".env"
_ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)(?::([^}]*))?\}$")


def _load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE pairs from .env into process environment."""
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as config_file:
        content = yaml.safe_load(config_file) or {}
        if not isinstance(content, dict):
            raise ValueError(f"Invalid config format in {path.name}: expected YAML object")
        return content


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    if not isinstance(value, str):
        return value

    match = _ENV_PATTERN.match(value.strip())
    if not match:
        return value

    env_key, default = match.group(1), match.group(2)
    env_value = os.getenv(env_key)
    if env_value is not None:
        return env_value
    if default is not None:
        return default
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_or(env_key: str, fallback: Any) -> Any:
    env_value = os.getenv(env_key)
    if env_value is None:
        return fallback
    return env_value


class Settings:
    def __init__(self) -> None:
        _load_env_file(_ENV_PATH)

        self._cfg = _resolve_env_placeholders(_read_yaml(_CONFIG_PATH))
        self._ai = _resolve_env_placeholders(_read_yaml(_AI_CONFIG_PATH))

        self._load_general_settings()
        self._load_ai_settings()
        self._validate_settings()

    def _load_general_settings(self) -> None:
        app = _as_dict(self._cfg.get("app"))
        server = _as_dict(self._cfg.get("server"))
        database = _as_dict(self._cfg.get("database"))
        auth = _as_dict(self._cfg.get("auth"))

        self.APP_NAME = str(_env_or("APP_NAME", app.get("name", "Refined Chatbot")))
        self.APP_VERSION = str(_env_or("APP_VERSION", app.get("version", "1.0.0")))
        self.DEBUG = _as_bool(_env_or("DEBUG", app.get("debug", True)), True)

        self.HOST = str(_env_or("HOST", server.get("host", "0.0.0.0")))
        self.PORT = _as_int(_env_or("PORT", server.get("port", 8111)), 8111)

        self.DATABASE_URL = str(_env_or("DATABASE_URL", database.get("url", "")))
        self.SECRET_KEY = str(_env_or("SECRET_KEY", auth.get("secret_key", "change-me-in-production")))

        self.LANGFUSE_ENABLED = _as_bool(_env_or("LANGFUSE_ENABLED", "false"), False)
        self.LANGFUSE_HOST = str(_env_or("LANGFUSE_HOST", "http://localhost:3000"))
        self.LANGFUSE_PUBLIC_KEY = str(_env_or("LANGFUSE_PUBLIC_KEY", ""))
        self.LANGFUSE_SECRET_KEY = str(_env_or("LANGFUSE_SECRET_KEY", ""))

    def _load_ai_settings(self) -> None:
        llm = _as_dict(self._ai.get("llm"))
        primary = _as_dict(llm.get("primary"))
        primary_h = _as_dict(primary.get("hyperparameters"))
        classifier = _as_dict(llm.get("classifier"))
        classifier_h = _as_dict(classifier.get("hyperparameters"))
        summarizer = _as_dict(llm.get("summarizer"))
        summarizer_h = _as_dict(summarizer.get("hyperparameters"))

        self.LLM_BASE_URL = str(_env_or("LLM_BASE_URL", primary.get("base_url", "http://localhost:8380/v1")))
        self.LLM_MODEL = str(_env_or("LLM_MODEL", primary.get("model_id", "meta-llama/Meta-Llama-3-8B-Instruct")))
        self.LLM_API_KEY = str(_env_or("LLM_API_KEY", primary.get("api_key", "dummy")))
        self.LLM_TEMPERATURE = _as_float(_env_or("LLM_TEMPERATURE", primary_h.get("temperature", 0.7)), 0.7)
        self.LLM_MAX_TOKENS = _as_int(_env_or("LLM_MAX_TOKENS", primary_h.get("max_tokens", 512)), 512)
        self.LLM_CONTEXT_WINDOW = _as_int(_env_or("LLM_CONTEXT_WINDOW", 8192), 8192)

        self.CLASSIFIER_TEMPERATURE = _as_float(
            _env_or("CLASSIFIER_TEMPERATURE", classifier_h.get("temperature", 0.0)),
            0.0,
        )
        self.CLASSIFIER_MAX_TOKENS = _as_int(
            _env_or("CLASSIFIER_MAX_TOKENS", classifier_h.get("max_tokens", 10)),
            10,
        )
        self.CLASSIFIER_BASE_URL = str(
            _env_or("CLASSIFIER_BASE_URL", classifier.get("base_url", self.LLM_BASE_URL))
        )
        self.CLASSIFIER_MODEL = str(
            _env_or("CLASSIFIER_MODEL", classifier.get("model_id", self.LLM_MODEL))
        )
        self.CLASSIFIER_API_KEY = str(
            _env_or("CLASSIFIER_API_KEY", classifier.get("api_key", self.LLM_API_KEY))
        )

        self.SUMMARIZER_TEMPERATURE = _as_float(
            _env_or("SUMMARIZER_TEMPERATURE", summarizer_h.get("temperature", self.LLM_TEMPERATURE)),
            self.LLM_TEMPERATURE,
        )
        self.SUMMARIZER_MAX_TOKENS = _as_int(
            _env_or("SUMMARIZER_MAX_TOKENS", summarizer_h.get("max_tokens", self.LLM_MAX_TOKENS)),
            self.LLM_MAX_TOKENS,
        )
        self.SUMMARIZER_BASE_URL = str(
            _env_or("SUMMARIZER_BASE_URL", summarizer.get("base_url", self.LLM_BASE_URL))
        )
        self.SUMMARIZER_MODEL = str(
            _env_or("SUMMARIZER_MODEL", summarizer.get("model_id", self.LLM_MODEL))
        )
        self.SUMMARIZER_API_KEY = str(
            _env_or("SUMMARIZER_API_KEY", summarizer.get("api_key", self.LLM_API_KEY))
        )

        embeddings = _as_dict(self._ai.get("embeddings"))
        embeddings_primary = _as_dict(embeddings.get("primary"))
        embeddings_h = _as_dict(embeddings_primary.get("hyperparameters"))
        self.EMBEDDINGS_PROVIDER = str(_env_or("EMBEDDINGS_PROVIDER", embeddings_primary.get("provider", "openai")))
        self.EMBEDDINGS_MODEL = str(_env_or("EMBEDDINGS_MODEL", embeddings_primary.get("model", "text-embedding-3-large")))
        self.EMBEDDINGS_API_KEY = str(_env_or("OPENAI_API_KEY", embeddings_primary.get("api_key", "")))
        self.EMBEDDINGS_BASE_URL = _env_or("EMBEDDINGS_BASE_URL", embeddings_primary.get("base_url"))
        self.EMBEDDINGS_BATCH_SIZE = _as_int(_env_or("EMBEDDINGS_BATCH_SIZE", embeddings_h.get("batch_size", 100)), 100)
        self.EMBEDDINGS_DIMENSION = _as_int(
            _env_or("EMBEDDINGS_DIMENSION", embeddings_h.get("embedding_dimension", 3072)),
            3072,
        )

        memory = _as_dict(self._ai.get("memory"))
        short_term = _as_dict(memory.get("short_term"))
        short_h = _as_dict(short_term.get("hyperparameters"))
        summary_cfg = _as_dict(short_term.get("summarization"))
        tokenizer_cfg = _as_dict(summary_cfg.get("tokenizer"))

        self.MEMORY_RECENT_TURNS_LIMIT = _as_int(short_h.get("max_recent_turns", 8), 8)
        self.MEMORY_PROMPT_TURNS_LIMIT = _as_int(short_h.get("max_turns_in_prompt", 3), 3)
        self.MEMORY_SUMMARIZATION_ENABLED = _as_bool(summary_cfg.get("enabled", True), True)
        self.MEMORY_SUMMARIZATION_THRESHOLD_TOKENS = _as_int(summary_cfg.get("threshold_tokens", 2400), 2400)
        self.MEMORY_SUMMARIZATION_KEEP_RECENT_TURNS = _as_int(summary_cfg.get("keep_recent_turns", 2), 2)
        self.MEMORY_SUMMARIZATION_RESERVE_TOKENS = _as_int(summary_cfg.get("reserve_tokens", 256), 256)
        self.MEMORY_TOKENIZER_STRATEGY = str(tokenizer_cfg.get("strategy", "auto"))
        self.MEMORY_TOKENIZER_MODEL_NAME = tokenizer_cfg.get("model_name")
        self.MEMORY_TOKENIZER_HF_LOCAL_FILES_ONLY = _as_bool(
            tokenizer_cfg.get("hf_local_files_only", True),
            True,
        )
        long_term = _as_dict(memory.get("long_term"))
        long_term_h = _as_dict(long_term.get("hyperparameters"))
        self.LONG_TERM_MEMORY_ENABLED = _as_bool(long_term.get("enabled", True), True)
        self.LONG_TERM_MEMORY_PROVIDER = str(long_term.get("provider", "qdrant"))
        self.LONG_TERM_MEMORY_COLLECTION_NAME = str(
            _env_or("LONG_TERM_MEMORY_COLLECTION_NAME", long_term.get("collection_name", "refined_chatbot_memories"))
        )
        self.LONG_TERM_MEMORY_TOP_K = _as_int(
            _env_or("LONG_TERM_MEMORY_TOP_K", long_term_h.get("top_k", 4)),
            4,
        )
        self.LONG_TERM_MEMORY_FALLBACK_LIMIT = _as_int(
            _env_or("LONG_TERM_MEMORY_FALLBACK_LIMIT", long_term_h.get("fallback_limit", 4)),
            4,
        )
        self.LONG_TERM_MEMORY_MAX_WRITE_ITEMS = _as_int(
            _env_or("LONG_TERM_MEMORY_MAX_WRITE_ITEMS", long_term_h.get("max_write_items", 3)),
            3,
        )
        self.LONG_TERM_MEMORY_MAX_CONTENT_CHARS = _as_int(
            _env_or("LONG_TERM_MEMORY_MAX_CONTENT_CHARS", long_term_h.get("max_content_chars", 240)),
            240,
        )
        self.LONG_TERM_MEMORY_MIN_CONFIDENCE = _as_float(
            _env_or("LONG_TERM_MEMORY_MIN_CONFIDENCE", long_term_h.get("min_confidence", 0.55)),
            0.55,
        )

        rag = _as_dict(self._ai.get("rag"))
        rag_query = _as_dict(rag.get("query"))
        rag_query_retrieval = _as_dict(rag_query.get("retrieval"))
        rag_dense = _as_dict(rag_query_retrieval.get("dense"))
        rag_dense_h = _as_dict(rag_dense.get("hyperparameters"))
        rag_sparse = _as_dict(rag_query_retrieval.get("sparse"))
        rag_sparse_h = _as_dict(rag_sparse.get("hyperparameters"))
        rag_fusion = _as_dict(rag_query_retrieval.get("fusion"))
        rag_rerank = _as_dict(rag_query.get("reranking"))
        rag_rerank_h = _as_dict(rag_rerank.get("hyperparameters"))
        rag_generation = _as_dict(rag_query.get("generation"))

        flags = _as_dict(self._ai.get("feature_flags"))
        self.RETRIEVAL_MODE = str(_env_or("RETRIEVAL_MODE", flags.get("retrieval_mode", "hybrid"))).lower()
        self.ENABLED_INTENTS = [str(v).lower() for v in _as_list(flags.get("enabled_intents", ["chitchat", "rag"]))]
        self.TRANSLATE_INPUT_ENABLED = _as_bool(_env_or("TRANSLATE_INPUT_ENABLED", flags.get("translate_input", False)), False)
        self.TRANSLATE_OUTPUT_ENABLED = _as_bool(_env_or("TRANSLATE_OUTPUT_ENABLED", flags.get("translate_output", False)), False)

        self.QDRANT_TOP_K = _as_int(_env_or("QDRANT_TOP_K", rag_dense_h.get("top_k", 5)), 5)
        self.ELASTICSEARCH_TOP_K = _as_int(_env_or("ELASTICSEARCH_TOP_K", rag_sparse_h.get("top_k", 5)), 5)

        self.QDRANT_COLLECTION_NAME = str(_env_or("QDRANT_COLLECTION_NAME", rag_dense.get("collection_name", "refined_chatbot_chunks")))
        self.QDRANT_URL = str(_env_or("QDRANT_URL", rag_dense.get("url", "http://localhost:6333")))
        self.QDRANT_API_KEY = _env_or("QDRANT_API_KEY", rag_dense.get("api_key"))
        if self.QDRANT_URL.startswith("http://"):
            self.QDRANT_API_KEY = None

        self.ELASTICSEARCH_INDEX_NAME = str(
            _env_or("ELASTICSEARCH_INDEX_NAME", rag_sparse.get("index_name", "refined_chatbot_chunks"))
        )
        self.ELASTICSEARCH_URL = str(_env_or("ELASTICSEARCH_URL", rag_sparse.get("url", "http://localhost:9200")))
        self.ELASTICSEARCH_BOOST_FACTOR = _as_float(rag_sparse_h.get("boost_factor", 1.5), 1.5)
        self.ELASTICSEARCH_MATCH_TYPE = str(rag_sparse_h.get("match_type", "best_fields"))

        self.FUSION_METHOD = str(rag_fusion.get("method", "reciprocal_rank_fusion"))
        self.FUSION_WEIGHT_DENSE = _as_float(_env_or("RAG_SEMANTIC_WEIGHT", rag_fusion.get("weight_dense", 0.5)), 0.5)
        self.FUSION_WEIGHT_SPARSE = _as_float(_env_or("RAG_BM25_WEIGHT", rag_fusion.get("weight_sparse", 0.5)), 0.5)
        self.FUSION_FINAL_TOP_K = _as_int(_env_or("RAG_FINAL_TOP_K", rag_fusion.get("final_top_k", 5)), 5)

        self.RERANK_ENABLED = _as_bool(rag_rerank.get("enabled", True), True)
        self.RERANK_PROVIDER = str(rag_rerank.get("provider", "cohere"))
        self.RERANK_MODEL = str(_env_or("COHERE_RERANK_MODEL", rag_rerank.get("model", "rerank-v3.5")))
        self.RERANK_API_KEY = str(_env_or("COHERE_API_KEY", rag_rerank.get("api_key", "")))
        self.RERANK_TOP_K = _as_int(_env_or("RERANK_TOP_K", rag_rerank_h.get("top_k", 3)), 3)
        self.RERANK_SCORE_THRESHOLD = _as_float(rag_rerank_h.get("score_threshold", 0.0), 0.0)
        self.RERANK_TIMEOUT_SEC = _as_float(_env_or("COHERE_TIMEOUT_SEC", rag_rerank_h.get("timeout_seconds", 30)), 30.0)
        self.RERANK_URL = str(
            _env_or("COHERE_RERANK_URL", rag_rerank.get("url", "https://api.cohere.com/v2/rerank"))
        )

        self.RAG_GENERATION_MAX_HISTORY_TURNS = _as_int(rag_generation.get("max_history_turns", 4), 4)
        self.RAG_GENERATION_SAFETY_MARGIN_TOKENS = _as_int(rag_generation.get("safety_margin_tokens", 160), 160)
        self.RAG_GENERATION_DOC_BUDGET_RATIO = _as_float(rag_generation.get("doc_budget_ratio", 0.60), 0.60)
        self.RAG_GENERATION_DOC_PREFIX_TOKENS = _as_int(rag_generation.get("doc_prefix_tokens", 10), 10)
        self.RAG_GENERATION_TAG_TOKENS = _as_int(rag_generation.get("tag_tokens", 96), 96)
        self.RAG_GENERATION_ROLE_FORMAT_OVERHEAD = _as_int(rag_generation.get("role_format_overhead", 5), 5)

        rag_ingestion = _as_dict(rag.get("ingestion"))
        chunking = _as_dict(rag_ingestion.get("chunking"))
        embedding = _as_dict(rag_ingestion.get("embedding"))
        indexing = _as_dict(rag_ingestion.get("indexing"))
        qdrant_index = _as_dict(indexing.get("qdrant"))
        elastic_index = _as_dict(indexing.get("elasticsearch"))

        self.INGESTION_CHUNK_SIZE = _as_int(chunking.get("chunk_size", 500), 500)
        self.INGESTION_CHUNK_OVERLAP = _as_int(chunking.get("chunk_overlap", 100), 100)
        self.INGESTION_EMBED_BATCH_SIZE = _as_int(embedding.get("batch_size", 32), 32)
        self.INGESTION_QDRANT_BATCH_SIZE = _as_int(qdrant_index.get("batch_size", 128), 128)
        self.INGESTION_QDRANT_DISTANCE = str(qdrant_index.get("distance", "cosine"))
        self.INGESTION_ES_BATCH_SIZE = _as_int(elastic_index.get("batch_size", 128), 128)

        prompts = _as_dict(self._ai.get("prompts"))
        memory_summary_prompt = _as_dict(prompts.get("memory_summarization"))
        self.MEMORY_SUMMARY_PROMPT_TEMPLATE = str(
            memory_summary_prompt.get(
                "template",
                summary_cfg.get(
                    "prompt_template",
                    "Summarize conversation history.\n\n{turns_text}\n\nSummary:",
                ),
            )
        )
        long_term_memory_prompt = _as_dict(prompts.get("long_term_memory_extraction"))
        self.LONG_TERM_MEMORY_EXTRACTION_PROMPT_TEMPLATE = str(
            long_term_memory_prompt.get(
                "template",
                (
                    "Extract durable patient memory facts from the conversation below.\n\n"
                    "Return valid JSON only as an array of objects with keys: "
                    "entity_type, entity_key, attribute_key, value_text or value_json, canonical_value, "
                    "category, clinical_status, verification_status, content, confidence, metadata.\n\n"
                    "Recent conversation:\n{history_text}\n\n"
                    "Latest user message:\n{user_message}\n\n"
                    "Latest assistant message:\n{assistant_message}\n\n"
                    "JSON:"
                ),
            )
        )

        intent_prompt = _as_dict(prompts.get("intent_classification"))
        intent_descriptions = _as_dict(intent_prompt.get("intent_descriptions"))
        self.INTENT_PROMPT_TEMPLATE = str(
            intent_prompt.get(
                "template",
                "You are an intent classifier for a healthcare chatbot.\n"
                "Classify the user message into exactly one enabled intent below.\n\n"
                "{intent_lines}\n\n"
                "Respond with ONLY one word: {labels}.\n\n"
                "User message: {message}",
            )
        )
        self.INTENT_DESCRIPTIONS = {
            "chitchat": str(
                intent_descriptions.get(
                    "chitchat",
                    "General conversation, greetings, and small talk.",
                )
            ),
            "rag": str(
                intent_descriptions.get(
                    "rag",
                    "Question that needs knowledge retrieval from documents.",
                )
            ),
            "action": str(
                intent_descriptions.get(
                    "action",
                    "Concrete action request like booking or account operation.",
                )
            ),
        }

        chitchat_prompt = _as_dict(prompts.get("chitchat_system"))
        self.CHITCHAT_SYSTEM_PROMPT_TEMPLATE = str(
            chitchat_prompt.get(
                "template",
                "You are a helpful and friendly healthcare assistant. "
                "Answer the user's questions clearly and concisely. "
                "If the question is outside your knowledge, say so honestly.",
            )
        )

        rag_prompt = _as_dict(prompts.get("rag_generation"))
        self.RAG_SYSTEM_PROMPT_TEMPLATE = str(
            rag_prompt.get(
                "template",
                "You are a healthcare assistant. Use ONLY the provided context to answer. "
                "If the context does not contain enough information, say so.",
            )
        )

        data = _as_dict(self._ai.get("data"))
        self.DATA_RAW_DIR = str(data.get("raw_dir", "data/raw_files"))
        self.DATA_TEMP_DIR = str(data.get("temp_dir", "data/temp_files"))

    def _validate_settings(self) -> None:
        if not self.DATABASE_URL:
            raise ValueError("Missing required configuration: database.url (or DATABASE_URL)")

        if self.RETRIEVAL_MODE not in {"hybrid", "semantic"}:
            raise ValueError(
                "Invalid feature_flags.retrieval_mode. Expected one of: hybrid, semantic"
            )

        if self.LONG_TERM_MEMORY_PROVIDER not in {"qdrant"}:
            raise ValueError("Invalid memory.long_term.provider. Expected: qdrant")

        allowed_intents = {"chitchat", "rag", "action"}
        invalid_intents = [intent for intent in self.ENABLED_INTENTS if intent not in allowed_intents]
        if invalid_intents:
            raise ValueError(
                f"Invalid feature_flags.enabled_intents values: {invalid_intents}. "
                f"Allowed: {sorted(allowed_intents)}"
            )

        if self.QDRANT_TOP_K <= 0:
            raise ValueError("rag.query.retrieval.dense.hyperparameters.top_k must be > 0")


settings = Settings()
