from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from ..world.models import Claim, ClaimCandidate
from .models import MemoryCandidate, MemoryDecision, MemoryScore

ALLOWED_CATEGORIES = {
    "preference",
    "profile",
    "goal",
    "constraint",
    "experiment_outcome",
    "hypothesis",
    "research_finding",
}
EPHEMERAL_MARKERS = ("hello", "hi", "thanks", "thank you", "what do you think")
SINGLETON_PREDICATES = {"name", "preferred_name"}
CONTENT_TYPE_PRIORS = {
    "profile": 0.90,
    "preference": 0.85,
    "goal": 0.90,
    "constraint": 0.88,
    "experiment_outcome": 0.78,
    "hypothesis": 0.70,
    "research_finding": 0.72,
}


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


def select_persistable_candidates(
    candidates: Iterable[MemoryCandidate],
) -> list[MemoryCandidate]:
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


def candidates_to_claims(
    candidates: Iterable[MemoryCandidate],
    *,
    source_kind: str,
    entity_name: str = "user",
    entity_type: str = "user",
) -> list[ClaimCandidate]:
    claim_candidates: list[ClaimCandidate] = []
    for candidate in candidates:
        predicate = candidate.category
        value = candidate.value
        if candidate.category == "profile" and ":" in candidate.value:
            key, raw_value = candidate.value.split(":", 1)
            predicate = key.strip().lower().replace(" ", "_")
            value = raw_value.strip()
        claim_candidates.append(
            ClaimCandidate(
                entity_name=entity_name,
                entity_type=entity_type,
                predicate=predicate,
                value=value,
                claim_type=candidate.category,
                confidence=candidate.confidence,
                source_kind=source_kind,
                source_text=candidate.source_text,
            )
        )
    return claim_candidates


def normalize_claim_candidate(candidate: ClaimCandidate) -> ClaimCandidate | None:
    predicate = candidate.predicate.strip().lower().replace(" ", "_")
    claim_type = candidate.claim_type.strip().lower().replace(" ", "_")
    value = _clean_value(candidate.value)
    source_url = candidate.source_url.strip()
    source_kind = candidate.source_kind.strip() or "user"
    if not predicate or not value or len(value) < 2:
        return None
    if claim_type not in ALLOWED_CATEGORIES:
        return None
    if any(re.search(rf"\b{re.escape(marker)}\b", value.lower()) for marker in EPHEMERAL_MARKERS):
        return None
    if claim_type == "research_finding" and source_url:
        source_kind = "browser"
    return ClaimCandidate(
        entity_name=candidate.entity_name.strip() or "user",
        entity_type=candidate.entity_type.strip() or "user",
        predicate=predicate,
        value=value[:280],
        claim_type=claim_type,
        confidence=max(0.0, min(1.0, candidate.confidence)),
        source_kind=source_kind,
        source_text=candidate.source_text,
        source_url=source_url,
        source_title=candidate.source_title.strip(),
        supporting_text=_clean_value(candidate.supporting_text)[:320],
    )


def score_candidate(candidate: ClaimCandidate, active_claims: Iterable[Claim]) -> MemoryScore:
    claims = list(active_claims)
    matching = [claim for claim in claims if claim.predicate == candidate.predicate]
    novelty = 1.0
    if matching:
        novelty = min(
            1.0,
            max(
                0.05,
                1.0 - max(_similarity(candidate.value, claim.value) for claim in matching),
            ),
        )
    future_utility = {
        "goal": 0.95,
        "constraint": 0.92,
        "profile": 0.88,
        "preference": 0.85,
        "experiment_outcome": 0.80,
        "hypothesis": 0.78,
        "research_finding": 0.76,
    }.get(candidate.claim_type, 0.70)
    recency = 1.0 if candidate.source_kind in {"browser", "user"} else 0.75
    return MemoryScore(
        future_utility=future_utility,
        factual_confidence=max(0.0, min(1.0, candidate.confidence)),
        semantic_novelty=novelty,
        temporal_recency=recency,
        content_type_prior=CONTENT_TYPE_PRIORS.get(candidate.claim_type, 0.65),
    )


def adjudicate_candidate(
    candidate: ClaimCandidate,
    *,
    active_claims: Iterable[Claim],
) -> MemoryDecision:
    normalized = normalize_claim_candidate(candidate)
    if normalized is None:
        return MemoryDecision(
            action="reject",
            claim_id=None,
            score=MemoryScore(0.0, 0.0, 0.0, 0.0, 0.0),
            reason="Candidate was empty, ephemeral, or had a disallowed category.",
            conflicts=[],
        )

    claims = list(active_claims)
    score = score_candidate(normalized, claims)
    exact_match = next(
        (
            claim
            for claim in claims
            if claim.predicate == normalized.predicate
            and claim.value.lower() == normalized.value.lower()
            and claim.status == "active"
        ),
        None,
    )
    if normalized.claim_type == "research_finding" and not normalized.source_url:
        return MemoryDecision(
            action="reject",
            claim_id=None,
            score=score,
            reason="Research findings require source provenance and a source URL.",
            conflicts=["missing_source"],
        )
    if normalized.source_kind == "browser" and not normalized.source_url:
        return MemoryDecision(
            action="reject",
            claim_id=None,
            score=score,
            reason="Browser-derived claims require provenance and a source URL.",
            conflicts=["missing_source"],
        )
    if exact_match is not None:
        return MemoryDecision(
            action="merge",
            claim_id=exact_match.claim_id,
            score=score,
            reason="An active canonical claim already exists with the same predicate and value.",
            conflicts=[],
        )
    if score.total < 0.55:
        return MemoryDecision(
            action="reject",
            claim_id=None,
            score=score,
            reason="Candidate scored below the persistence threshold.",
            conflicts=[],
        )

    same_predicate = [claim for claim in claims if claim.predicate == normalized.predicate]
    if normalized.predicate in SINGLETON_PREDICATES and same_predicate:
        highest = max(same_predicate, key=lambda claim: claim.updated_at)
        if highest.value.lower() != normalized.value.lower():
            return MemoryDecision(
                action="revise",
                claim_id=highest.claim_id,
                score=score,
                reason="Singleton predicate received a more recent value and must supersede the prior claim.",
                conflicts=[highest.value],
            )

    if same_predicate and any(_is_conflict(normalized.value, claim.value) for claim in same_predicate):
        return MemoryDecision(
            action="accept_new",
            claim_id=None,
            score=score,
            reason="Conflicting evidence should remain explicit instead of silently overwriting prior claims.",
            conflicts=[claim.value for claim in same_predicate],
        )

    return MemoryDecision(
        action="accept_new",
        claim_id=None,
        score=score,
        reason="Candidate is novel and above the acceptance threshold.",
        conflicts=[],
    )


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _is_conflict(left: str, right: str) -> bool:
    left_norm = left.lower()
    right_norm = right.lower()
    if left_norm == right_norm:
        return False
    polarity_words = ("not ", "no ", "cannot", "can't", "must ", "should ")
    return any(token in left_norm or token in right_norm for token in polarity_words)
