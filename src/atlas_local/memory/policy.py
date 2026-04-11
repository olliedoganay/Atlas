from __future__ import annotations

import re
from typing import Iterable

from .models import MemoryCandidate

ALLOWED_CATEGORIES = {
    "preference",
    "profile",
    "goal",
    "constraint",
    "experiment_outcome",
    "hypothesis",
}
EPHEMERAL_MARKERS = ("hello", "hi", "thanks", "thank you", "what do you think")


def _clean_value(value: str) -> str:
    compact = " ".join(value.strip().split())
    return compact.rstrip(".")


def normalize_candidate(candidate: MemoryCandidate) -> MemoryCandidate | None:
    category = candidate.category.strip().lower().replace(" ", "_")
    value = _clean_value(candidate.value)
    lowered = value.lower()

    if category not in ALLOWED_CATEGORIES:
        return None
    if len(value) < 3:
        return None
    if any(re.search(rf"\b{re.escape(marker)}\b", lowered) for marker in EPHEMERAL_MARKERS):
        return None

    confidence = max(0.0, min(1.0, candidate.confidence))
    return MemoryCandidate(
        category=category,
        value=value[:240],
        confidence=confidence,
        source_text=candidate.source_text,
    )


def select_persistable_candidates(candidates: Iterable[MemoryCandidate]) -> list[MemoryCandidate]:
    seen: set[tuple[str, str]] = set()
    accepted: list[MemoryCandidate] = []
    for candidate in candidates:
        normalized = normalize_candidate(candidate)
        if normalized is None:
            continue
        key = (normalized.category, normalized.value.lower())
        if key in seen:
            continue
        seen.add(key)
        accepted.append(normalized)
    return accepted


def fallback_candidates_from_text(text: str) -> list[MemoryCandidate]:
    lowered = text.lower()
    candidates: list[MemoryCandidate] = []
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
        if segment.strip()
    ]

    patterns = [
        (
            "profile",
            re.compile(r"\bmy name is ([a-z0-9 _-]+)", re.IGNORECASE),
            lambda match: f"name: {match.group(1).strip()}",
        ),
        (
            "goal",
            re.compile(r"\b(i want to|we need to|my goal is|i am trying to) ([^.!\n]+)", re.IGNORECASE),
            lambda match: match.group(2).strip(),
        ),
        (
            "preference",
            re.compile(r"\b(i prefer|i like|we prefer) ([^.!\n]+)", re.IGNORECASE),
            lambda match: match.group(2).strip(),
        ),
        (
            "constraint",
            re.compile(r"\b(must|should not|cannot|can't|do not want) ([^.!\n]+)", re.IGNORECASE),
            lambda match: f"{match.group(1).strip()} {match.group(2).strip()}",
        ),
    ]

    for segment in segments or [text]:
        if segment.endswith("?"):
            continue

        for category, pattern, formatter in patterns:
            match = pattern.search(segment)
            if match:
                candidates.append(
                    MemoryCandidate(
                        category=category,
                        value=formatter(match),
                        confidence=0.72,
                        source_text=segment,
                    )
                )

    outcome_markers = ("error", "fails", "failed", "works", "working", "crash", "bug")
    if "?" not in text and any(marker in lowered for marker in outcome_markers):
        candidates.append(
            MemoryCandidate(
                category="experiment_outcome",
                value=text.strip()[:240],
                confidence=0.65,
                source_text=text,
            )
        )

    return select_persistable_candidates(candidates)


def fallback_local_memory_candidates_from_text(text: str) -> list[MemoryCandidate]:
    local_candidates = [
        candidate
        for candidate in fallback_candidates_from_text(text)
        if candidate.category in {"profile", "preference", "constraint"}
    ]
    return select_persistable_candidates(local_candidates)
