from __future__ import annotations

from ..benchmarks.models import BenchmarkRun
from .evaluator import weakest_metric
from .registry import ImprovementProposal, RuntimeProfile


def propose_profile_improvement(run: BenchmarkRun, current: RuntimeProfile) -> ImprovementProposal:
    metric, score = weakest_metric(run)
    if metric == "citation_score":
        candidate = RuntimeProfile(
            name=f"{current.name}-cite",
            force_browser_for_research=True,
            browser_result_limit=min(current.browser_result_limit + 1, 4),
            memory_accept_threshold=current.memory_accept_threshold,
            retrieval_weight=current.retrieval_weight,
            rule_toggles=current.rule_toggles,
        )
        rationale = "Citation fidelity is the weakest metric."
        change = "Increase browser result exploration to gather more source coverage before synthesis."
        target = "browser"
    elif metric == "contradiction_score":
        toggles = dict(current.rule_toggles or {})
        toggles["constraints"] = True
        toggles["unsupported"] = True
        candidate = RuntimeProfile(
            name=f"{current.name}-rules",
            force_browser_for_research=current.force_browser_for_research,
            browser_result_limit=current.browser_result_limit,
            memory_accept_threshold=min(current.memory_accept_threshold + 0.05, 0.8),
            retrieval_weight=current.retrieval_weight,
            rule_toggles=toggles,
        )
        rationale = "Contradiction rate is the weakest metric."
        change = "Raise memory admission strictness and keep constraint checks fully enabled."
        target = "memory-policy"
    else:
        candidate = RuntimeProfile(
            name=f"{current.name}-retrieval",
            force_browser_for_research=current.force_browser_for_research,
            browser_result_limit=current.browser_result_limit,
            memory_accept_threshold=current.memory_accept_threshold,
            retrieval_weight=min(current.retrieval_weight + 0.1, 2.0),
            rule_toggles=current.rule_toggles,
        )
        rationale = "Signal recall is the weakest metric."
        change = "Slightly increase retrieval weighting so canonical context is surfaced more aggressively."
        target = "retrieval"

    return ImprovementProposal(
        title=f"Improve {target}",
        rationale=f"{rationale} Current score={score:.2f}.",
        target_area=target,
        suggested_change=change,
        candidate_profile=candidate,
    )
