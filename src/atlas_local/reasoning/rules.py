from __future__ import annotations

from collections import Counter, defaultdict

from ..world.models import Claim, WorldEvent
from .models import ConstraintViolation, ReasoningReport
from .solver import solve_constraints


def evaluate_world_state(claims: list[Claim], events: list[WorldEvent] | None = None) -> ReasoningReport:
    events = events or []
    active_claims = [claim for claim in claims if claim.status == "active"]
    violations: list[ConstraintViolation] = []

    duplicate_counter = Counter(
        (claim.entity_id, claim.predicate, claim.value.lower()) for claim in active_claims
    )
    for key, count in duplicate_counter.items():
        if count > 1:
            violations.append(
                ConstraintViolation(
                    rule_id="claim.duplicate",
                    severity="warning",
                    message=f"Duplicate active claim detected for {key[1]}: {key[2]}",
                    evidence=[f"{count} active copies"],
                )
            )

    names_by_entity: dict[str, set[str]] = defaultdict(set)
    for claim in active_claims:
        if claim.predicate == "name":
            names_by_entity[claim.entity_id].add(claim.value.lower())
        if claim.claim_type == "research_finding" and not claim.source_id:
            violations.append(
                ConstraintViolation(
                    rule_id="claim.unsupported",
                    severity="error",
                    message=f"Research finding '{claim.value}' is missing source provenance.",
                    evidence=[claim.claim_id],
                )
            )

    for entity_id, values in names_by_entity.items():
        if len(values) > 1:
            violations.append(
                ConstraintViolation(
                    rule_id="claim.name_conflict",
                    severity="error",
                    message=f"Conflicting active names detected for entity {entity_id}.",
                    evidence=sorted(values),
                )
            )

    experiment_counter = Counter(
        claim.value.lower() for claim in active_claims if claim.claim_type == "experiment_outcome"
    )
    for value, count in experiment_counter.items():
        if count > 1:
            violations.append(
                ConstraintViolation(
                    rule_id="claim.duplicate_experiment",
                    severity="warning",
                    message=f"Duplicate experiment outcome detected: {value}",
                    evidence=[f"{count} active experiment claims"],
                )
            )

    violations.extend(solve_constraints(active_claims))

    recommendations: list[str] = []
    if violations:
        recommendations.append("Review contradictory or unsupported claims before relying on them in research answers.")
    if not active_claims:
        recommendations.append("No active canonical claims exist yet; rely on the current turn and citations only.")
    if active_claims and not violations:
        recommendations.append("Use active claims confidently and keep provenance attached to browser-derived findings.")
    if events:
        recommendations.append("Inspect recent world events when a multi-step research plan appears to drift.")

    return ReasoningReport(
        claims=[claim.to_dict() for claim in active_claims],
        violations=violations,
        recommendations=recommendations,
    )
