from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import AppConfig
from ..evolution.registry import RuntimeProfile
from ..reasoning.models import ReasoningReport
from .models import BenchmarkResult, BenchmarkRun
from .registry import get_benchmark_suite


class BenchmarkRunner:
    def __init__(self, config: AppConfig):
        self.config = config

    def run(self, *, app, suite: str, profile: RuntimeProfile) -> BenchmarkRun:
        cases = get_benchmark_suite(self.config, suite)
        run_id = str(uuid.uuid4())
        results: list[BenchmarkResult] = []
        for index, case in enumerate(cases, start=1):
            user_id = f"benchmark-{run_id}-{index}"
            for setup_index, setup_prompt in enumerate(case.setup_turns, start=1):
                app.ask(
                    setup_prompt,
                    user_id=user_id,
                    thread_id=f"{case.name}-setup-{setup_index}",
                    research_mode=False,
                )
            response = app.ask(
                case.prompt,
                user_id=user_id,
                thread_id=f"{case.name}-run",
                research_mode=case.research_mode,
            )
            report = ReasoningReport.from_dict(response.get("reasoning_report"))
            scores = _score_case(
                answer=response.get("answer", ""),
                expected_signals=case.expected_signals,
                citations=response.get("citations", []),
                violations=report.violations,
                require_citation=case.require_citation,
            )
            results.append(
                BenchmarkResult(
                    suite=suite,
                    case_name=case.name,
                    answer=response.get("answer", ""),
                    scores=scores,
                    citations=list(response.get("citations", [])),
                    violations=[item.to_dict() for item in report.violations],
                )
            )

        aggregate_scores = _aggregate_scores(results)
        run = BenchmarkRun(
            run_id=run_id,
            suite=suite,
            profile_name=profile.name,
            aggregate_scores=aggregate_scores,
            results=results,
        )
        self._write_run(run)
        return run

    def load(self, run_id_or_path: str) -> BenchmarkRun:
        path = Path(run_id_or_path)
        if not path.exists():
            path = self.config.evals_dir / f"{run_id_or_path}.json"
        if not path.exists():
            raise RuntimeError(f"Benchmark run not found: {run_id_or_path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return BenchmarkRun(
            run_id=payload["run_id"],
            suite=payload["suite"],
            profile_name=payload["profile_name"],
            aggregate_scores=dict(payload.get("aggregate_scores", {})),
            results=[
                BenchmarkResult(
                    suite=item["suite"],
                    case_name=item["case_name"],
                    answer=item["answer"],
                    scores=dict(item.get("scores", {})),
                    citations=list(item.get("citations", [])),
                    violations=list(item.get("violations", [])),
                )
                for item in payload.get("results", [])
            ],
        )

    def _write_run(self, run: BenchmarkRun) -> Path:
        path = self.config.evals_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
        return path


def _score_case(
    *,
    answer: str,
    expected_signals: tuple[str, ...],
    citations: list[dict[str, object]],
    violations,
    require_citation: bool,
) -> dict[str, float]:
    lowered_answer = answer.lower()
    signal_hits = sum(1 for signal in expected_signals if signal.lower() in lowered_answer)
    signal_score = signal_hits / max(len(expected_signals), 1)
    citation_score = 1.0 if (citations or not require_citation) else 0.0
    contradiction_score = 1.0 if not violations else max(0.0, 1.0 - (0.25 * len(violations)))
    return {
        "signal_score": signal_score,
        "citation_score": citation_score,
        "contradiction_score": contradiction_score,
    }


def _aggregate_scores(results: list[BenchmarkResult]) -> dict[str, float]:
    if not results:
        return {"signal_score": 0.0, "citation_score": 0.0, "contradiction_score": 0.0}
    keys = sorted(results[0].scores.keys())
    return {
        key: round(sum(result.scores.get(key, 0.0) for result in results) / len(results), 4)
        for key in keys
    }
