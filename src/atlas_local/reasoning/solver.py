from __future__ import annotations

from z3 import And, Bool, BoolVal, Implies, Not, Solver, unsat

from ..world.models import Claim
from .models import ConstraintViolation


def _has_text(claims: list[Claim], predicate: str, keywords: tuple[str, ...]) -> bool:
    for claim in claims:
        if claim.predicate != predicate or claim.status != "active":
            continue
        lowered = claim.value.lower()
        if any(keyword in lowered for keyword in keywords):
            return True
    return False


def solve_constraints(claims: list[Claim]) -> list[ConstraintViolation]:
    local_first = _has_text(claims, "goal", ("local", "on-device")) or _has_text(
        claims, "preference", ("local", "on-device")
    )
    cloud_required = _has_text(claims, "goal", ("cloud-only", "hosted", "remote api")) or _has_text(
        claims, "constraint", ("must use cloud",)
    )
    persistent_memory = _has_text(
        claims,
        "goal",
        ("persistent memory", "cross-session memory", "memory across sessions"),
    )
    diskless = _has_text(claims, "constraint", ("no disk", "stateless only", "without persistence"))

    solver = Solver()
    local_only_var = Bool("local_only")
    cloud_required_var = Bool("cloud_required")
    persistent_memory_var = Bool("persistent_memory")
    diskless_var = Bool("diskless")

    solver.add(local_only_var == BoolVal(local_first))
    solver.add(cloud_required_var == BoolVal(cloud_required))
    solver.add(persistent_memory_var == BoolVal(persistent_memory))
    solver.add(diskless_var == BoolVal(diskless))
    solver.add(Not(And(local_only_var, cloud_required_var)))
    solver.add(Implies(diskless_var, Not(persistent_memory_var)))

    if solver.check() != unsat:
        return []

    violations: list[ConstraintViolation] = []
    if local_first and cloud_required:
        violations.append(
            ConstraintViolation(
                rule_id="goal.local_vs_cloud",
                severity="error",
                message="Goals and constraints simultaneously require local-first and cloud-required behavior.",
                evidence=["local-first", "cloud-required"],
            )
        )
    if persistent_memory and diskless:
        violations.append(
            ConstraintViolation(
                rule_id="goal.persistence_vs_diskless",
                severity="error",
                message="Persistent memory conflicts with a diskless or stateless-only constraint.",
                evidence=["persistent-memory", "diskless"],
            )
        )
    return violations
