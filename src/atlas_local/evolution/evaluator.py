from __future__ import annotations

from ..benchmarks.models import BenchmarkRun


def weakest_metric(run: BenchmarkRun) -> tuple[str, float]:
    if not run.aggregate_scores:
        return ("signal_score", 0.0)
    metric = min(run.aggregate_scores.items(), key=lambda item: item[1])
    return metric[0], metric[1]
