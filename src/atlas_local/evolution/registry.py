from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import AppConfig


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    force_browser_for_research: bool = True
    browser_result_limit: int = 2
    memory_accept_threshold: float = 0.55
    retrieval_weight: float = 1.0
    rule_toggles: dict[str, bool] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rule_toggles"] = dict(self.rule_toggles or {})
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeProfile":
        return cls(
            name=str(payload.get("name", "default")).strip() or "default",
            force_browser_for_research=bool(payload.get("force_browser_for_research", True)),
            browser_result_limit=int(payload.get("browser_result_limit", 2) or 2),
            memory_accept_threshold=float(payload.get("memory_accept_threshold", 0.55) or 0.55),
            retrieval_weight=float(payload.get("retrieval_weight", 1.0) or 1.0),
            rule_toggles=dict(payload.get("rule_toggles", {}) or {}),
        )


@dataclass(frozen=True)
class ImprovementProposal:
    title: str
    rationale: str
    target_area: str
    suggested_change: str
    candidate_profile: RuntimeProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "rationale": self.rationale,
            "target_area": self.target_area,
            "suggested_change": self.suggested_change,
            "candidate_profile": self.candidate_profile.to_dict(),
        }


def default_profile() -> RuntimeProfile:
    return RuntimeProfile(name="default", rule_toggles={"constraints": True, "unsupported": True})


def load_active_profile(config: AppConfig, *, profile_name: str | None = None) -> RuntimeProfile:
    active_name = profile_name or _resolve_active_name(config)
    path = _profile_path(config, active_name)
    if not path.exists():
        profile = default_profile()
        if active_name != profile.name:
            profile = RuntimeProfile(
                name=active_name,
                force_browser_for_research=profile.force_browser_for_research,
                browser_result_limit=profile.browser_result_limit,
                memory_accept_threshold=profile.memory_accept_threshold,
                retrieval_weight=profile.retrieval_weight,
                rule_toggles=profile.rule_toggles,
            )
        save_profile(config, profile)
        return profile
    return RuntimeProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_profile(config: AppConfig, profile: RuntimeProfile) -> Path:
    path = _profile_path(config, profile.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return path


def list_profiles(config: AppConfig) -> list[str]:
    config.proposals_dir.mkdir(parents=True, exist_ok=True)
    return sorted(path.stem for path in config.proposals_dir.glob("*.json"))


def promote_profile(config: AppConfig, profile_name: str) -> Path:
    path = _profile_path(config, profile_name)
    if not path.exists():
        raise RuntimeError(f"Profile not found: {profile_name}")
    active_path = config.proposals_dir / "active_profile.txt"
    active_path.write_text(profile_name, encoding="utf-8")
    return active_path


def _resolve_active_name(config: AppConfig) -> str:
    active_path = config.proposals_dir / "active_profile.txt"
    if active_path.exists():
        value = active_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return config.active_profile


def _profile_path(config: AppConfig, name: str) -> Path:
    return config.proposals_dir / f"{name}.json"
