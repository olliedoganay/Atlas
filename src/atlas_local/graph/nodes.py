from __future__ import annotations

import logging
import re
from typing import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from ..config import AppConfig
from ..llm import format_runtime_error
from ..memory.mem0_service import Mem0Service
from ..memory.models import MemoryCandidate, MemoryRecord
from ..memory.policy import fallback_local_memory_candidates_from_text
from ..providers.base import ChatModelProvider
from .context import GraphContext
from .state import AgentState

LOGGER = logging.getLogger(__name__)


class GraphNodes:
    def __init__(
        self,
        config: AppConfig,
        llm_provider: ChatModelProvider,
        memory_service: Mem0Service,
    ):
        self.config = config
        self.llm_provider = llm_provider
        self.memory_service = memory_service

    def retrieve_memories(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {"retrieved_memories": []}

        latest_user_message = _latest_user_text(state)
        if not latest_user_message:
            return {"retrieved_memories": []}

        retrieved: list[str] = []
        try:
            stored = self.memory_service.search(
                latest_user_message,
                user_id=runtime.context.user_id,
                limit=max(1, self.config.memory_top_k),
            )
            retrieved = [item.memory for item in stored if item.memory]
        except Exception as exc:  # pragma: no cover - integration path
            LOGGER.warning("Memory retrieval failed: %s", exc)
        return {"retrieved_memories": retrieved}

    def synthesize_answer(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        messages = _build_answer_messages(
            state=state,
            runtime_context=runtime.context,
            token_counter=_provider_message_token_counter(self.llm_provider, runtime.context.chat_model),
        )
        try:
            response = self.llm_provider.chat(
                runtime.context.chat_model,
                temperature=runtime.context.chat_temperature,
            ).invoke(messages)
        except Exception as exc:  # pragma: no cover - integration path
            raise format_runtime_error(self.config, exc, chat_model=runtime.context.chat_model) from exc

        answer = _finalize_answer_text(str(response.content))
        return {
            "messages": [AIMessage(content=answer)],
            "answer": answer,
        }

    def extract_updates(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {"update_candidates": []}

        latest_user_message = _latest_user_text(state)
        if not latest_user_message:
            return {"update_candidates": []}

        candidates = fallback_local_memory_candidates_from_text(latest_user_message)
        return {"update_candidates": [candidate.to_dict() for candidate in candidates]}

    def persist(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {"persisted_memories": []}

        existing_memories: set[str] = set()
        try:
            existing_memories = {
                item.memory.strip().lower()
                for item in self.memory_service.list(user_id=runtime.context.user_id, limit=200)
                if item.memory.strip()
            }
        except Exception as exc:  # pragma: no cover - integration path
            LOGGER.warning("Could not load existing memories before persistence: %s", exc)

        persisted: list[dict[str, Any]] = []
        for payload in state.get("update_candidates", []):
            candidate = MemoryCandidate.from_dict(payload)
            storage_text = candidate.to_storage_text().strip()
            if not storage_text or storage_text.lower() in existing_memories:
                continue
            response = self.memory_service.add(
                MemoryRecord(claim_id=f"auto:{runtime.context.thread_id}", text=storage_text),
                user_id=runtime.context.user_id,
                metadata={
                    "source": "auto",
                    "kind": "extracted_memory",
                    "category": candidate.category,
                },
            )
            existing_memories.add(storage_text.lower())
            persisted.append(
                {
                    "memory": storage_text,
                    "category": candidate.category,
                    "response": response,
                }
            )
        return {"persisted_memories": persisted}


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return _message_text(message.content)
    return ""


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


MessageTokenCounter = Callable[[list[BaseMessage]], int]


def _build_answer_messages(
    *,
    state: AgentState,
    runtime_context: GraphContext,
    token_counter: MessageTokenCounter | None = None,
) -> list[HumanMessage | AIMessage | SystemMessage]:
    memory_message = _memory_context_message(state=state, runtime_context=runtime_context)
    summary_message = _thread_summary_message(state)
    recent_messages = _recent_prompt_messages(
        state=state,
        runtime_context=runtime_context,
        memory_message=memory_message,
        summary_message=summary_message,
        token_counter=token_counter,
    )
    prefix = [item for item in (memory_message, summary_message) if item is not None]
    return prefix + recent_messages


def _memory_context_message(*, state: AgentState, runtime_context: GraphContext) -> SystemMessage | None:
    if not getattr(runtime_context, "cross_chat_memory", True):
        return None

    memories = [item for item in state.get("retrieved_memories", []) if item]
    if not memories:
        return None
    return SystemMessage(content="Relevant persistent memories:\n" + _format_list(memories))


def _thread_summary_message(state: AgentState) -> SystemMessage | None:
    summary = str(state.get("thread_summary", "") or "").strip()
    if not summary:
        return None
    return SystemMessage(content=f"Conversation summary from earlier in this thread:\n{summary}")


def _recent_prompt_messages(
    *,
    state: AgentState,
    runtime_context: GraphContext,
    memory_message: SystemMessage | None,
    summary_message: SystemMessage | None,
    token_counter: MessageTokenCounter | None,
) -> list[BaseMessage]:
    messages = list(state.get("messages", []))
    compacted_count = max(0, min(int(state.get("compacted_message_count", 0) or 0), len(messages)))
    candidate_messages = messages[compacted_count:]
    effective_context_window = int(
        runtime_context.effective_context_window
        or state.get("detected_context_window")
        or 0
    )
    if effective_context_window <= 0:
        return candidate_messages

    prompt_budget = max(1024, int(effective_context_window * 0.72))
    reserved_tokens = _count_messages_tokens([memory_message, summary_message], token_counter=token_counter) + 64
    available_tokens = max(256, prompt_budget - reserved_tokens)

    selected: list[BaseMessage] = []
    consumed = 0
    for message in reversed(candidate_messages):
        message_tokens = _count_messages_tokens([message], token_counter=token_counter)
        if selected and consumed + message_tokens > available_tokens:
            break
        selected.insert(0, message)
        consumed += message_tokens
        if len(selected) >= 12 and consumed >= available_tokens:
            break

    if not selected and candidate_messages:
        return [candidate_messages[-1]]
    return selected


def _estimate_message_tokens(message: BaseMessage | None) -> int:
    if message is None:
        return 0
    return _estimate_content_tokens(message.content) + 8


def _count_messages_tokens(
    messages: list[BaseMessage | None],
    *,
    token_counter: MessageTokenCounter | None,
) -> int:
    items = [message for message in messages if message is not None]
    if not items:
        return 0
    if token_counter is not None:
        try:
            counted = int(token_counter(items))
            if counted >= 0:
                return counted
        except Exception:
            pass
    return sum(_estimate_message_tokens(message) for message in items)


def _estimate_content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return max(1, len(content) // 4)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += max(1, len(item) // 4)
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).strip().lower()
                if item_type == "text":
                    total += max(1, len(str(item.get("text", ""))) // 4)
                elif item_type == "image_url":
                    total += 256
        return max(total, 1)
    return max(1, len(str(content)) // 4)


def _format_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {item}" for item in values)


def _provider_message_token_counter(
    llm_provider: ChatModelProvider,
    model: str,
) -> MessageTokenCounter | None:
    counter = getattr(llm_provider, "count_message_tokens", None)
    if not callable(counter):
        return None
    return lambda messages: counter(model, messages)


def _strip_empty_sources_footer(answer: str) -> str:
    cleaned = re.sub(r"\n{0,2}Sources:\s*(-\s*)?(none|n/?a)\s*$", "", answer.strip(), flags=re.IGNORECASE)
    return cleaned.strip()


def _finalize_answer_text(answer: str) -> str:
    return _strip_empty_sources_footer(answer.strip())
