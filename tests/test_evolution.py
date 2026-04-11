import tempfile
import unittest
from pathlib import Path

from atlas_local.benchmarks.models import BenchmarkResult, BenchmarkRun
from atlas_local.config import load_config
from atlas_local.evolution.propose import propose_profile_improvement
from atlas_local.evolution.registry import default_profile, load_active_profile, promote_profile, save_profile


class EvolutionTests(unittest.TestCase):
    def test_profile_roundtrip_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            profile = default_profile()
            save_profile(config, profile)
            loaded = load_active_profile(config)
            self.assertEqual(loaded.name, "default")
            active_path = promote_profile(config, "default")
            self.assertTrue(active_path.exists())

    def test_proposal_targets_weakest_metric(self) -> None:
        run = BenchmarkRun(
            run_id="r1",
            suite="browse_research_v1",
            profile_name="default",
            aggregate_scores={"signal_score": 0.3, "citation_score": 0.8, "contradiction_score": 1.0},
            results=[
                BenchmarkResult(
                    suite="browse_research_v1",
                    case_name="c1",
                    answer="",
                    scores={"signal_score": 0.3, "citation_score": 0.8, "contradiction_score": 1.0},
                    citations=[],
                    violations=[],
                )
            ],
        )
        proposal = propose_profile_improvement(run, default_profile())
        self.assertEqual(proposal.target_area, "retrieval")


if __name__ == "__main__":
    unittest.main()
