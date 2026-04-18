"""Token-aware memory summarization strategy.

Handles context window budget by summarizing older turns when token count
approaches limits. Keeps recent turns intact and merges older ones into summary.
"""

from dataclasses import dataclass
import importlib
import importlib.util
from typing import Protocol

from services.chat.memory.base import MemoryTurn

if importlib.util.find_spec("tiktoken") is not None:
    tiktoken = importlib.import_module("tiktoken")
else:  # pragma: no cover - optional dependency
    tiktoken = None

if importlib.util.find_spec("transformers") is not None:
    transformers = importlib.import_module("transformers")
else:  # pragma: no cover - optional dependency
    transformers = None


@dataclass
class TokenBudget:
    """Token budget constraints."""
    context_window: int = 3072  # Total context window (Llama 3-8B)
    max_output_tokens: int = 512
    reserve_tokens: int = 100
    
    @property
    def max_input_tokens(self) -> int:
        """Calculate max input tokens."""
        return self.context_window - self.max_output_tokens - self.reserve_tokens


class TokenCounter(Protocol):
    """Protocol for counting tokens in text."""
    
    def count(self, text: str) -> int:
        """Count approximate tokens in text."""


class SimpleTokenCounter:
    """Simple token counter (rough estimation)."""
    # Approximation: 1 token ~= 4 characters
    TOKEN_RATIO = 4
    
    def count(self, text: str) -> int:
        """Count approximate tokens."""
        return len(text) // self.TOKEN_RATIO + 1


class TikTokenCounter:
    """Token counter using tiktoken when available."""

    def __init__(self, model_name: str | None = None, encoding_name: str = "cl100k_base") -> None:
        if tiktoken is None:
            raise RuntimeError("tiktoken is not installed")

        if model_name:
            try:
                self.encoding = tiktoken.encoding_for_model(model_name)
            except KeyError:
                self.encoding = tiktoken.get_encoding(encoding_name)
        else:
            self.encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        """Count tokens using model tokenizer."""
        if not text:
            return 0
        return len(self.encoding.encode(text))


class HuggingFaceTokenCounter:
    """Token counter using HuggingFace tokenizer for closer model alignment."""

    def __init__(self, model_name: str, local_files_only: bool = True) -> None:
        if transformers is None:
            raise RuntimeError("transformers is not installed")
        if not model_name:
            raise RuntimeError("model_name is required for HuggingFaceTokenCounter")

        auto_tokenizer = getattr(transformers, "AutoTokenizer")
        self.tokenizer = auto_tokenizer.from_pretrained(
            model_name,
            use_fast=True,
            local_files_only=local_files_only,
        )

    def count(self, text: str) -> int:
        """Count tokens using model tokenizer."""
        if not text:
            return 0
        return len(self.tokenizer.encode(text, add_special_tokens=False))


def create_token_counter(
    model_name: str | None = None,
    strategy: str = "auto",
    hf_local_files_only: bool = True,
) -> TokenCounter:
    """Create token counter based on strategy.

    Strategies:
    - auto: prefer HuggingFace tokenizer -> tiktoken -> simple
    - hf: force HuggingFace tokenizer if available, else fallback chain
    - tiktoken: force tiktoken if available, else fallback to simple
    - simple: always use rough estimate
    """
    normalized = (strategy or "auto").strip().lower()
    if normalized in {"auto", "hf", "huggingface"} and model_name and transformers is not None:
        try:
            return HuggingFaceTokenCounter(model_name=model_name, local_files_only=hf_local_files_only)
        except Exception:
            if normalized in {"hf", "huggingface"}:
                # Explicit HF requested but unavailable at runtime; continue with best fallback.
                pass
    if normalized in {"auto", "tiktoken"} and tiktoken is not None:
        return TikTokenCounter(model_name=model_name)
    return SimpleTokenCounter()


def estimate_message_tokens(turn: MemoryTurn, counter: TokenCounter | None = None) -> int:
    """Estimate tokens for a memory turn."""
    if counter is None:
        counter = SimpleTokenCounter()
    
    # Role overhead + content
    role_tokens = 5  # Approximate overhead for role/formatting
    content_tokens = counter.count(turn.content)
    return role_tokens + content_tokens


def calculate_history_tokens(turns: list[MemoryTurn], counter: TokenCounter | None = None) -> int:
    """Calculate total tokens in history."""
    total = 0
    for turn in turns:
        total += estimate_message_tokens(turn, counter)
    return total


@dataclass
class HistorySummary:
    """Represents summarized conversation history."""
    summary_content: str
    num_turns_summarized: int
    token_count: int


class HistorySummarizer:
    """Coordinates history summarization strategy."""
    
    def __init__(
        self,
        token_counter: TokenCounter | None = None,
        summary_llm = None,
        summary_prompt_template: str | None = None,
        tokenizer_model_name: str | None = None,
        tokenizer_strategy: str = "auto",
        hf_local_files_only: bool = True,
    ):
        self.counter = token_counter or create_token_counter(
            model_name=tokenizer_model_name,
            strategy=tokenizer_strategy,
            hf_local_files_only=hf_local_files_only,
        )
        self.summary_llm = summary_llm
        self.summary_prompt_template = summary_prompt_template or self._default_summary_prompt()
    
    def _default_summary_prompt(self) -> str:
        """Default summarization prompt."""
        return """Summarize the following conversation history into a concise summary.
Keep key facts, names, and important context.

Conversation:
{turns_text}

Summary (one paragraph):"""
    
    async def should_summarize(
        self,
        turns: list[MemoryTurn],
        threshold: int = 2000,
    ) -> bool:
        """Check if history exceeds token threshold."""
        total_tokens = calculate_history_tokens(turns, self.counter)
        return total_tokens >= threshold
    
    async def summarize(
        self,
        turns: list[MemoryTurn],
        keep_recent: int = 2,
        summarize_until_idx: int | None = None,
    ) -> tuple[list[MemoryTurn], HistorySummary | None]:
        """Summarize older turns, keep recent turns intact.
        
        Args:
            turns: All conversation turns
            keep_recent: Number of recent turns to preserve
            summarize_until_idx: Summarize up to this index (exclusive)
        
        Returns:
            (updated_turns, summary) - updated list with summary, or None if no summarization
        """
        if not turns or len(turns) <= keep_recent:
            return turns, None
        
        if summarize_until_idx is None:
            summarize_until_idx = len(turns) - keep_recent
        
        if summarize_until_idx <= 0:
            return turns, None
        
        # Turns to summarize and to keep
        to_summarize = turns[:summarize_until_idx]
        to_keep = turns[summarize_until_idx:]
        
        # Build turns text
        turns_text = "\n".join([
            f"{t.role.upper()}: {t.content}" 
            for t in to_summarize
        ])
        
        # Generate summary via LLM if available
        if self.summary_llm:
            system_prompt = self.summary_prompt_template
            if "{turns_text}" in system_prompt:
                system_prompt = system_prompt.replace(
                    "{turns_text}",
                    "[conversation history is provided in the user message]",
                )

            history_payload = (
                "Conversation history:\n"
                f"{turns_text}\n\n"
                "Return a compact summary of the key facts only."
            )
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                response = await self.summary_llm.ainvoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=history_payload),
                    ]
                )
                summary_text = response.content
            except Exception as e:
                # Fallback if LLM fails
                summary_text = self._fallback_summary(turns_text)
        else:
            summary_text = self._fallback_summary(turns_text)
        
        # Create summary turn
        summary_turn = MemoryTurn(
            role="system_summary",
            content=summary_text,
        )
        
        # Calculate summary tokens
        summary_tokens = estimate_message_tokens(summary_turn, self.counter)
        
        # New history: summary + kept turns
        updated_turns = [summary_turn] + to_keep
        
        result_summary = HistorySummary(
            summary_content=summary_text,
            num_turns_summarized=len(to_summarize),
            token_count=summary_tokens,
        )
        
        return updated_turns, result_summary
    
    def _fallback_summary(self, turns_text: str) -> str:
        """Generate fallback summary without LLM."""
        lines = turns_text.split("\n")
        # Simple heuristic: take first line + last 2 lines
        if len(lines) <= 3:
            return turns_text
        
        return f"{lines[0]}...(and {len(lines) - 3} more exchanges)...{lines[-2]}\n{lines[-1]}"


class TokenAwareMemoryManager:
    """Manages memory with token-aware summarization."""
    
    def __init__(
        self,
        token_budget: TokenBudget | None = None,
        summarizer: HistorySummarizer | None = None,
        summarization_threshold: int = 2000,
        keep_recent_turns: int = 2,
    ):
        self.token_budget = token_budget or TokenBudget()
        self.summarizer = summarizer or HistorySummarizer()
        # Keep threshold within effective input budget.
        self.summarization_threshold = min(
            max(1, summarization_threshold),
            max(1, self.token_budget.max_input_tokens),
        )
        self.keep_recent_turns = max(1, keep_recent_turns)
    
    async def filter_turns(
        self,
        turns: list[MemoryTurn],
        max_turns: int = 12,
        apply_summarization: bool = True,
    ) -> list[MemoryTurn]:
        """Filter turns with optional smart summarization.
        
        Strategy:
        1. If history exceeds token threshold, summarize older turns
        2. Keep recent turns intact
        3. Return limited turn count
        """
        if not turns:
            return []
        
        # First, check if summarization needed
        if apply_summarization:
            should_summarize = await self.summarizer.should_summarize(
                turns,
                threshold=self.summarization_threshold,
            )
            
            if should_summarize:
                turns, summary = await self.summarizer.summarize(
                    turns,
                    keep_recent=self.keep_recent_turns,
                )
                if summary:
                    print(f"[Memory] Summarized {summary.num_turns_summarized} turns "
                          f"into {summary.token_count} tokens")
        
        # Return limited turns
        return turns[-max_turns:] if len(turns) > max_turns else turns
