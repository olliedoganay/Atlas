from __future__ import annotations

import re
from typing import Iterable

from ..memory.models import MemoryCandidate
from ..memory.policy import fallback_candidates_from_text
from .models import Fact

TAGGED_MEMORY_RE = re.compile(r"^\[(?P<category>[a-z_]+)\]\s*(?P<value>.+)$", re.IGNORECASE)


def _candidate_to_fact(candidate: MemoryCandidate, source_turn: str) -> Fact:
    predicate = candidate.category
    value = candidate.value

    if candidate.category == "profile" and ":" in value:
        key, raw_value = value.split(":", 1)
        predicate = key.strip().lower().replace(" ", "_")
        value = raw_value.strip()

    return Fact(
        subject="user",
        predicate=predicate,
        object=value,
        confidence=candidate.confidence,
        source_turn=source_turn,
    )


def _memory_text_to_candidate(memory_text: str) -> MemoryCandidate | None:
    match = TAGGED_MEMORY_RE.match(memory_text.strip())
    if not match:
        return None
    return MemoryCandidate(
        category=match.group("category").lower(),
        value=match.group("value").strip(),
        confidence=0.9,
        source_text=memory_text,
    )


def extract_facts(
    latest_user_message: str,
    retrieved_memories: Iterable[str],
    *,
    accepted_candidates: Iterable[MemoryCandidate] | None = None,
    source_turn: str = "current",
) -> list[Fact]:
    facts: list[Fact] = []

    for memory_text in retrieved_memories:
        candidate = _memory_text_to_candidate(memory_text)
        if candidate:
            facts.append(_candidate_to_fact(candidate, "memory"))

    for candidate in fallback_candidates_from_text(latest_user_message):
        facts.append(_candidate_to_fact(candidate, source_turn))

    if accepted_candidates:
        for candidate in accepted_candidates:
            facts.append(_candidate_to_fact(candidate, source_turn))

    return facts
