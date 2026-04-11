from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Fact:
    subject: str
    predicate: str
    object: str
    confidence: float
    source_turn: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Fact":
        return cls(
            subject=str(payload.get("subject", "user")),
            predicate=str(payload.get("predicate", "profile")),
            object=str(payload.get("object", "")).strip(),
            confidence=float(payload.get("confidence", 0.7)),
            source_turn=str(payload.get("source_turn", "unknown")),
        )


@dataclass(frozen=True)
class ConstraintViolation:
    rule_id: str
    severity: str
    message: str
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConstraintViolation":
        return cls(
            rule_id=str(payload.get("rule_id", "unknown")),
            severity=str(payload.get("severity", "warning")),
            message=str(payload.get("message", "")),
            evidence=[str(item) for item in payload.get("evidence", [])],
        )


@dataclass(frozen=True)
class ReasoningReport:
    claims: list[dict[str, Any]]
    violations: list[ConstraintViolation]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": self.claims,
            "violations": [violation.to_dict() for violation in self.violations],
            "recommendations": self.recommendations,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ReasoningReport":
        payload = payload or {}
        claims = payload.get("claims")
        if claims is None:
            claims = [Fact.from_dict(item).to_dict() for item in payload.get("facts", [])]
        return cls(
            claims=[dict(item) for item in claims],
            violations=[
                ConstraintViolation.from_dict(item)
                for item in payload.get("violations", [])
            ],
            recommendations=[str(item) for item in payload.get("recommendations", [])],
        )

    def to_prompt_text(self) -> str:
        fact_lines = [
            f"- {str(item.get('predicate', 'claim'))}: {str(item.get('value', item.get('object', '')))}"
            for item in self.claims
        ]
        violation_lines = [f"- {item.message}" for item in self.violations]
        recommendation_lines = [f"- {item}" for item in self.recommendations]
        sections = [
            "Claims:\n" + ("\n".join(fact_lines) if fact_lines else "- none"),
            "Violations:\n" + ("\n".join(violation_lines) if violation_lines else "- none"),
            "Recommendations:\n"
            + ("\n".join(recommendation_lines) if recommendation_lines else "- none"),
        ]
        return "\n\n".join(sections)
