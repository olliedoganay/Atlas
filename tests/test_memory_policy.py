import unittest

from atlas_local.memory.models import MemoryCandidate
from atlas_local.memory.policy import (
    adjudicate_candidate,
    candidates_to_claims,
    fallback_candidates_from_text,
    fallback_local_memory_candidates_from_text,
    select_persistable_candidates,
)
from atlas_local.world.models import Claim


class MemoryPolicyTests(unittest.TestCase):
    def test_only_durable_categories_are_persisted(self) -> None:
        candidates = [
            MemoryCandidate(category="goal", value="build a durable local agent"),
            MemoryCandidate(category="greeting", value="hello there"),
            MemoryCandidate(category="goal", value="build a durable local agent"),
        ]
        accepted = select_persistable_candidates(candidates)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].category, "goal")

    def test_fallback_extractor_detects_preferences(self) -> None:
        accepted = fallback_candidates_from_text("I prefer local-first architectures for this project.")
        self.assertTrue(any(item.category == "preference" for item in accepted))

    def test_local_fallback_excludes_goal_like_chat_intent(self) -> None:
        accepted = fallback_local_memory_candidates_from_text("I am trying to check for the latest developments on AGI.")
        self.assertEqual(accepted, [])

    def test_browser_claim_requires_source(self) -> None:
        candidate = candidates_to_claims(
            [MemoryCandidate(category="research_finding", value="A cited finding", confidence=0.8)],
            source_kind="browser",
        )[0]
        decision = adjudicate_candidate(candidate, active_claims=[])
        self.assertEqual(decision.action, "reject")

    def test_cited_research_finding_is_treated_as_browser_claim(self) -> None:
        candidate = candidates_to_claims(
            [MemoryCandidate(category="research_finding", value="A cited finding", confidence=0.8)],
            source_kind="user",
        )[0]
        candidate = candidate.__class__(
            entity_name=candidate.entity_name,
            entity_type=candidate.entity_type,
            predicate=candidate.predicate,
            value=candidate.value,
            claim_type=candidate.claim_type,
            confidence=candidate.confidence,
            source_kind=candidate.source_kind,
            source_text=candidate.source_text,
            source_url="https://example.com",
            source_title="Example",
            supporting_text="A cited finding",
        )
        decision = adjudicate_candidate(candidate, active_claims=[])
        self.assertEqual(decision.action, "accept_new")

    def test_singleton_claim_revises_existing_name(self) -> None:
        candidate = candidates_to_claims(
            [MemoryCandidate(category="profile", value="name: Ada", confidence=0.9)],
            source_kind="user",
        )[0]
        existing = [
            Claim(
                claim_id="c1",
                user_id="u1",
                entity_id="e1",
                predicate="name",
                value="Grace",
                claim_type="profile",
                status="active",
                confidence=0.9,
                source_id=None,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                supersedes_claim_id=None,
            )
        ]
        decision = adjudicate_candidate(candidate, active_claims=existing)
        self.assertEqual(decision.action, "revise")


if __name__ == "__main__":
    unittest.main()
