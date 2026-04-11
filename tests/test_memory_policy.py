import unittest

from atlas_local.memory.models import MemoryCandidate
from atlas_local.memory.policy import (
    fallback_candidates_from_text,
    fallback_local_memory_candidates_from_text,
    select_persistable_candidates,
)


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

    def test_local_fallback_keeps_profile_memory(self) -> None:
        accepted = fallback_local_memory_candidates_from_text("My name is Ada.")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].category, "profile")


if __name__ == "__main__":
    unittest.main()
