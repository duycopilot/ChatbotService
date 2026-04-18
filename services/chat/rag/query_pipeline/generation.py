"""Generation step for RAG query pipeline."""

from __future__ import annotations

import logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from configs.config import settings
from integrations.llms.vllm import create_llm
from services.chat.llm.prompt_builder import build_rag_prompt
from services.chat.memory import MemoryTurn
from services.chat.memory.token_aware import create_token_counter
from services.observability import langfuse_client


logger = logging.getLogger(__name__)


def _build_history_messages(
	recent_turns: list[MemoryTurn] | None,
	max_history_turns: int,
) -> list[HumanMessage | AIMessage]:
	if not recent_turns or max_history_turns <= 0:
		return []

	history_messages: list[HumanMessage | AIMessage] = []
	turns = recent_turns[-max_history_turns:]
	for turn in turns:
		content = str(turn.content).strip()
		if not content:
			continue

		role = str(turn.role).strip().lower()
		if role == "user":
			history_messages.append(HumanMessage(content=content))
		elif role == "assistant":
			history_messages.append(AIMessage(content=content))

	return history_messages


def _trim_docs_to_budget(
	documents: list[dict],
	budget_tokens: int,
	counter,
) -> list[dict]:
	"""Trim documents to fit into a dedicated token budget."""
	doc_budget = max(0, budget_tokens)
	trimmed: list[dict] = []
	used = 0
	for doc in documents:
		text = doc.get("page_content") or doc.get("content", "")
		tokens = counter.count(text) + 10  # +10 for "[N] " prefix per doc
		if used + tokens <= doc_budget:
			trimmed.append(doc)
			used += tokens
		else:
			break

	# Always include at least 1 doc to preserve RAG intent
	return trimmed if trimmed else documents[:1]


def _trim_history_to_budget(
	history_messages: list[HumanMessage | AIMessage],
	budget_tokens: int,
	counter,
) -> list[HumanMessage | AIMessage]:
	"""Keep the newest history messages that fit within history budget."""
	if budget_tokens <= 0 or not history_messages:
		return []

	trimmed_reversed: list[HumanMessage | AIMessage] = []
	used = 0
	for message in reversed(history_messages):
		tokens = counter.count(message.content) + 5  # +5 role/format overhead
		if used + tokens > budget_tokens:
			break
		trimmed_reversed.append(message)
		used += tokens

	return list(reversed(trimmed_reversed))


async def generate_answer(
	query: str,
	documents: list[dict],
	llm: ChatOpenAI | None = None,
	recent_turns: list[MemoryTurn] | None = None,
	long_term_memories: list[str] | None = None,
	max_history_turns: int | None = None,
) -> str:
	"""Generate final answer from query and retrieved documents.

	If `llm` is not provided, this function will instantiate the default
	integration LLM via `create_llm()`.
	"""
	with langfuse_client.span(
		"rag_generation",
		as_type="generation",
		input={"query": query, "documents_count": len(documents)},
		metadata={
			"max_history_turns": max_history_turns or settings.RAG_GENERATION_MAX_HISTORY_TURNS,
			"tokenizer_strategy": settings.MEMORY_TOKENIZER_STRATEGY,
			"max_history_turns_config": settings.RAG_GENERATION_MAX_HISTORY_TURNS,
		},
	) as gen_obs:
		SYSTEM_PREFIX = settings.RAG_SYSTEM_PROMPT_TEMPLATE + "\n\nContext:"
		SAFETY_MARGIN_TOKENS = 160
		DOC_BUDGET_RATIO = 0.60
		effective_history_turns = (
			settings.RAG_GENERATION_MAX_HISTORY_TURNS
			if max_history_turns is None
			else max_history_turns
		)

		counter = create_token_counter(
			model_name=settings.LLM_MODEL,
			strategy=settings.MEMORY_TOKENIZER_STRATEGY,
		)

		max_input_tokens = (
			settings.LLM_CONTEXT_WINDOW
			- settings.LLM_MAX_TOKENS
			- settings.MEMORY_SUMMARIZATION_RESERVE_TOKENS
			- SAFETY_MARGIN_TOKENS
		)

		fixed_overhead = counter.count(SYSTEM_PREFIX) + counter.count(query) + 96
		variable_budget = max(0, max_input_tokens - fixed_overhead)
		doc_budget = int(variable_budget * DOC_BUDGET_RATIO)
		history_budget = max(0, variable_budget - doc_budget)

		history_messages_full = _build_history_messages(recent_turns, effective_history_turns)
		history_messages = _trim_history_to_budget(history_messages_full, history_budget, counter)
		documents = _trim_docs_to_budget(documents, doc_budget, counter)

		prompt_messages = build_rag_prompt(query, documents, memories=long_term_memories)

		messages = [
			SystemMessage(content=prompt_messages[0]["content"]),
			*history_messages,
			HumanMessage(content=prompt_messages[1]["content"]),
		]

		active_llm = llm or create_llm()
		lf_handler = langfuse_client.get_langchain_handler()
		if lf_handler is not None:
			try:
				active_llm = active_llm.with_config(callbacks=[lf_handler])
			except Exception:
				pass

		try:
			response = await active_llm.ainvoke(messages)
			# Log context + final response to Langfuse for faithfulness evaluation
			if gen_obs is not None:
				context_content = prompt_messages[0]["content"]
				gen_obs.update(
					output={
						"answer": response.content,
						"context_full": context_content,
						"documents_used": len(documents),
						"history_turns_used": len(history_messages),
					}
				)
				# Also log to console for debugging
				logger.debug(f"RAG generation context logged: {len(context_content)} chars, {len(documents)} docs")
			return response.content
		except Exception as exc:
			error_text = str(exc).lower()
			is_context_overflow = (
				"maximum input length" in error_text
				or "context length" in error_text
				or "input tokens" in error_text
			)
			if not is_context_overflow:
				raise

			# Final fallback: remove history and keep only top-1 doc.
			fallback_docs = documents[:1]
			fallback_prompt = build_rag_prompt(query, fallback_docs, memories=long_term_memories)
			fallback_messages = [
				SystemMessage(content=fallback_prompt[0]["content"]),
				HumanMessage(content=fallback_prompt[1]["content"]),
			]
			response = await active_llm.ainvoke(fallback_messages)
			# Log context + final response (fallback) to Langfuse
			if gen_obs is not None:
				gen_obs.update(
					output={
						"answer": response.content,
						"context_full": fallback_prompt[0]["content"],
						"documents_used": len(fallback_docs),
						"history_turns_used": 0,
						"fallback_triggered": True,
					}
				)
			return response.content
