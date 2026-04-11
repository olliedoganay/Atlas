from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from .models import BenchmarkCase


def list_benchmark_suites() -> list[str]:
    return ["web_interactive_v1", "browse_research_v1", "memory_world_v1"]


def get_benchmark_suite(config: AppConfig, name: str) -> list[BenchmarkCase]:
    if name not in list_benchmark_suites():
        raise RuntimeError(f"Unknown benchmark suite: {name}")

    fixture_root = config.project_root / "src" / "atlas_local" / "benchmarks" / "fixtures"
    landing = (fixture_root / "landing.html").resolve().as_uri()
    details = (fixture_root / "details.html").resolve().as_uri()
    notes = (fixture_root / "notes.html").resolve().as_uri()

    suites = {
        "web_interactive_v1": [
            BenchmarkCase(
                suite=name,
                name="landing_phase_lookup",
                prompt=f"Open {landing} and identify the current research phase and codename.",
                expected_signals=("phase two", "atlas"),
                research_mode=True,
                require_citation=True,
            ),
            BenchmarkCase(
                suite=name,
                name="details_constraints_lookup",
                prompt=f"Open {details} and summarize the listed constraints.",
                expected_signals=("local-first", "human approval"),
                research_mode=True,
                require_citation=True,
            ),
        ],
        "browse_research_v1": [
            BenchmarkCase(
                suite=name,
                name="notes_hypothesis_lookup",
                prompt=f"Research the project notes at {notes} and report the main hypothesis.",
                expected_signals=("memory plus world model",),
                research_mode=True,
                require_citation=True,
            ),
            BenchmarkCase(
                suite=name,
                name="details_deadline_lookup",
                prompt=f"Use {details} to identify the next milestone deadline.",
                expected_signals=("2026-06-01",),
                research_mode=True,
                require_citation=True,
            ),
        ],
        "memory_world_v1": [
            BenchmarkCase(
                suite=name,
                name="cross_thread_recall",
                setup_turns=(
                    "My name is Ada.",
                    "I prefer local-first architectures.",
                ),
                prompt="What do you know about my name and architecture preference?",
                expected_signals=("ada", "local-first"),
            ),
            BenchmarkCase(
                suite=name,
                name="goal_constraint_recall",
                setup_turns=(
                    "My goal is to build a durable research agent.",
                    "We must keep a human approval gate for self-improvement.",
                ),
                prompt="What long-term goal and constraint have I set?",
                expected_signals=("durable research agent", "human approval"),
            ),
        ],
    }
    return suites[name]
