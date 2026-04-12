from __future__ import annotations

from typing import Any, Protocol


class ChatModelProvider(Protocol):
    def chat(
        self,
        model: str | None = None,
        *,
        temperature: float | None = None,
        reasoning: bool | str | None = None,
    ) -> Any: ...

    def json_chat(self, model: str | None = None) -> Any: ...

    def count_message_tokens(self, model: str | None, messages: list[Any]) -> int: ...

    def effective_context_window(self, model: str | None = None, *, ttl_seconds: float = 15.0) -> int: ...

    def abort_active_requests(self) -> None: ...
