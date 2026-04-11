from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserAction:
    tool: str
    value: str = ""
    selector: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BrowserAction":
        return cls(
            tool=str(payload.get("tool", "")).strip(),
            value=str(payload.get("value", "")).strip(),
            selector=str(payload.get("selector", "")).strip(),
            metadata=dict(payload.get("metadata", {}) or {}),
        )


@dataclass(frozen=True)
class BrowserObservation:
    url: str
    title: str
    text_excerpt: str
    links: list[dict[str, str]]
    results: list[dict[str, str]] = field(default_factory=list)
    screenshot_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BrowserObservation":
        links = []
        for item in payload.get("links", []) or []:
            if isinstance(item, dict):
                links.append(
                    {
                        "text": str(item.get("text", "")).strip(),
                        "url": str(item.get("url", "")).strip(),
                    }
                )
        results = []
        for item in payload.get("results", []) or []:
            if isinstance(item, dict):
                results.append(
                    {
                        "title": str(item.get("title", "")).strip(),
                        "url": str(item.get("url", "")).strip(),
                        "snippet": str(item.get("snippet", "")).strip(),
                        "display_url": str(item.get("display_url", "")).strip(),
                    }
                )
        return cls(
            url=str(payload.get("url", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            text_excerpt=str(payload.get("text_excerpt", "")).strip(),
            links=links,
            results=results,
            screenshot_path=str(payload.get("screenshot_path", "")).strip(),
        )


@dataclass(frozen=True)
class Citation:
    url: str
    title: str
    quote: str
    accessed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Citation":
        return cls(
            url=str(payload.get("url", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            quote=str(payload.get("quote", "")).strip(),
            accessed_at=str(payload.get("accessed_at", "")).strip(),
        )


@dataclass(frozen=True)
class BrowserTraceEntry:
    action: BrowserAction
    observation: BrowserObservation | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "observation": self.observation.to_dict() if self.observation else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BrowserTraceEntry":
        observation = payload.get("observation")
        return cls(
            action=BrowserAction.from_dict(payload.get("action", {})),
            observation=BrowserObservation.from_dict(observation) if observation else None,
            error=str(payload.get("error", "")).strip(),
        )


@dataclass(frozen=True)
class BrowserPlan:
    use_browser: bool
    objective: str
    query: str = ""
    direct_url: str = ""
    max_steps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "BrowserPlan":
        payload = payload or {}
        return cls(
            use_browser=bool(payload.get("use_browser", False)),
            objective=str(payload.get("objective", "")).strip(),
            query=str(payload.get("query", "")).strip(),
            direct_url=str(payload.get("direct_url", "")).strip(),
            max_steps=int(payload.get("max_steps", 0) or 0),
        )
