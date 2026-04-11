from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    suite: str
    name: str
    prompt: str
    expected_signals: tuple[str, ...]
    setup_turns: tuple[str, ...] = ()
    research_mode: bool = False
    expected_claims: tuple[str, ...] = ()
    require_citation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkResult:
    suite: str
    case_name: str
    answer: str
    scores: dict[str, float]
    citations: list[dict[str, Any]]
    violations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    suite: str
    profile_name: str
    aggregate_scores: dict[str, float]
    results: list[BenchmarkResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "suite": self.suite,
            "profile_name": self.profile_name,
            "aggregate_scores": self.aggregate_scores,
            "results": [result.to_dict() for result in self.results],
        }
