from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Entity:
    entity_id: str
    user_id: str
    entity_type: str
    name: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Source:
    source_id: str
    user_id: str
    url: str
    title: str
    accessed_at: str
    supporting_text: str
    created_in_thread_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    user_id: str
    entity_id: str
    predicate: str
    value: str
    claim_type: str
    status: str
    confidence: float
    source_id: str | None
    created_at: str
    updated_at: str
    supersedes_claim_id: str | None
    created_in_thread_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=str(payload.get("claim_id", "")).strip(),
            user_id=str(payload.get("user_id", "")).strip(),
            entity_id=str(payload.get("entity_id", "")).strip(),
            predicate=str(payload.get("predicate", "")).strip(),
            value=str(payload.get("value", "")).strip(),
            claim_type=str(payload.get("claim_type", "")).strip(),
            status=str(payload.get("status", "active")).strip(),
            confidence=float(payload.get("confidence", 0.8) or 0.8),
            source_id=str(payload["source_id"]).strip() if payload.get("source_id") else None,
            created_at=str(payload.get("created_at", "")).strip(),
            updated_at=str(payload.get("updated_at", "")).strip(),
            supersedes_claim_id=(
                str(payload["supersedes_claim_id"]).strip()
                if payload.get("supersedes_claim_id")
                else None
            ),
            created_in_thread_id=(
                str(payload["created_in_thread_id"]).strip()
                if payload.get("created_in_thread_id")
                else None
            ),
        )


@dataclass(frozen=True)
class ClaimCandidate:
    entity_name: str
    entity_type: str
    predicate: str
    value: str
    claim_type: str
    confidence: float
    source_kind: str
    source_text: str = ""
    source_url: str = ""
    source_title: str = ""
    supporting_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClaimCandidate":
        return cls(
            entity_name=str(payload.get("entity_name", "user")).strip() or "user",
            entity_type=str(payload.get("entity_type", "user")).strip() or "user",
            predicate=str(payload.get("predicate", "")).strip(),
            value=str(payload.get("value", "")).strip(),
            claim_type=str(payload.get("claim_type", "")).strip(),
            confidence=float(payload.get("confidence", 0.75) or 0.75),
            source_kind=str(payload.get("source_kind", "user")).strip() or "user",
            source_text=str(payload.get("source_text", "")).strip(),
            source_url=str(payload.get("source_url", "")).strip(),
            source_title=str(payload.get("source_title", "")).strip(),
            supporting_text=str(payload.get("supporting_text", "")).strip(),
        )


@dataclass(frozen=True)
class WorldEvent:
    event_id: str
    user_id: str
    event_type: str
    thread_id: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
