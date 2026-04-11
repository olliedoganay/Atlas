from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryCandidate:
    category: str
    value: str
    confidence: float = 0.8
    source_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryCandidate":
        return cls(
            category=str(payload.get("category", "")).strip(),
            value=str(payload.get("value", "")).strip(),
            confidence=float(payload.get("confidence", 0.8) or 0.8),
            source_text=str(payload.get("source_text", "")).strip(),
        )

    def to_storage_text(self) -> str:
        return f"[{self.category}] {self.value}"


@dataclass(frozen=True)
class MemoryRecord:
    claim_id: str
    text: str
    status: str = "active"
    memory_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoredMemory:
    memory: str
    memory_id: str
    score: float | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StoredMemory":
        return cls(
            memory=str(payload.get("memory", "")).strip(),
            memory_id=str(payload.get("id", "")).strip(),
            score=float(payload["score"]) if payload.get("score") is not None else None,
            metadata=payload.get("metadata"),
        )


@dataclass(frozen=True)
class MemoryScore:
    future_utility: float
    factual_confidence: float
    semantic_novelty: float
    temporal_recency: float
    content_type_prior: float

    @property
    def total(self) -> float:
        return (
            (0.30 * self.future_utility)
            + (0.25 * self.factual_confidence)
            + (0.20 * self.semantic_novelty)
            + (0.15 * self.temporal_recency)
            + (0.10 * self.content_type_prior)
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["total"] = round(self.total, 4)
        return payload


@dataclass(frozen=True)
class MemoryDecision:
    action: str
    claim_id: str | None
    score: MemoryScore
    reason: str
    conflicts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "claim_id": self.claim_id,
            "score": self.score.to_dict(),
            "reason": self.reason,
            "conflicts": self.conflicts,
        }
