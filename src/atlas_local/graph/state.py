from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    thread_summary: str
    compacted_message_count: int
    detected_context_window: int
    retrieved_memories: list[str]
    world_claims: list[dict[str, Any]]
    world_events: list[dict[str, Any]]
    browser_plan: dict[str, Any]
    browser_trace: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    update_candidates: list[dict[str, Any]]
    adjudicated_updates: list[dict[str, Any]]
    reasoning_report: dict[str, Any]
    answer: str
