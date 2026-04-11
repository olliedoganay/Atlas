from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphContext:
    user_id: str
    thread_id: str
    session_id: str
    chat_model: str
    chat_temperature: float | None
    research_mode: bool = False
    cross_chat_memory: bool = True
    auto_compact_long_chats: bool = True
    effective_context_window: int | None = None
