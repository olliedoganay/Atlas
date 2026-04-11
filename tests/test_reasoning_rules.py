import unittest

from atlas_local.reasoning.rules import evaluate_world_state
from atlas_local.world.models import Claim


class ReasoningRuleTests(unittest.TestCase):
    def test_duplicate_claim_violation(self) -> None:
        claims = [
            Claim("c1", "u1", "e1", "goal", "build a durable local agent", "goal", "active", 0.9, None, "t", "t", None),
            Claim("c2", "u1", "e1", "goal", "build a durable local agent", "goal", "active", 0.9, None, "t", "t", None),
        ]
        report = evaluate_world_state(claims)
        self.assertTrue(any(item.rule_id == "claim.duplicate" for item in report.violations))

    def test_local_and_cloud_conflict(self) -> None:
        claims = [
            Claim("c1", "u1", "e1", "goal", "local-first architecture", "goal", "active", 0.9, None, "t", "t", None),
            Claim("c2", "u1", "e1", "constraint", "must use cloud", "constraint", "active", 0.9, None, "t", "t", None),
        ]
        report = evaluate_world_state(claims)
        self.assertTrue(any(item.rule_id == "goal.local_vs_cloud" for item in report.violations))

    def test_browser_finding_without_source_is_flagged(self) -> None:
        claims = [
            Claim("c1", "u1", "e1", "finding", "A web claim", "research_finding", "active", 0.7, None, "t", "t", None),
        ]
        report = evaluate_world_state(claims)
        self.assertTrue(any(item.rule_id == "claim.unsupported" for item in report.violations))


if __name__ == "__main__":
    unittest.main()
