import tempfile
import unittest
from pathlib import Path

from atlas_local.browser.service import BrowserManager, _BrowserSession
from atlas_local.browser.models import BrowserObservation
from atlas_local.browser.service import _bing_challenge_reason, _resolve_bing_url
from atlas_local.config import load_config
from atlas_local.graph.nodes import (
    _expand_research_queries,
    _grounded_research_answer,
    _score_search_result,
    _strip_empty_sources_footer,
)
from atlas_local.browser.models import Citation


class BrowserServiceTests(unittest.TestCase):
    def test_resolve_bing_redirect_url(self) -> None:
        url = (
            "https://www.bing.com/ck/a?!&&p=abc"
            "&u=a1aHR0cHM6Ly93d3cuc2NtcC5jb20vbGl2ZQ&ntb=1"
        )
        self.assertEqual(_resolve_bing_url(url), "https://www.scmp.com/live")

    def test_detect_bing_challenge_page(self) -> None:
        observation = BrowserObservation(
            url="https://www.bing.com/search?q=agi",
            title="Blocked Search",
            text_excerpt="About this page. Our systems have detected unusual traffic from your computer network.",
            links=[],
        )
        self.assertIn("blocked", _bing_challenge_reason(observation).lower())

    def test_latest_trace_path_ignores_missing_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            manager = BrowserManager(config)
            missing = config.browser_storage_dir / "thread-a" / "missing.jsonl"
            manager._sessions["thread-a"] = _BrowserSession(context=None, page=None, trace_path=missing)  # type: ignore[arg-type]
            self.assertEqual(manager.latest_trace_path(thread_id="thread-a"), "")

    def test_grounded_research_answer_uses_citation_quotes(self) -> None:
        answer = _grounded_research_answer(
            question="What are the latest developments on AGI?",
            citations=[
                Citation(
                    url="https://arxiv.org/abs/2601.10904",
                    title="ARC Prize 2025",
                    quote="Interactive reasoning remains a major open bottleneck for current AI systems.",
                    accessed_at="2026-04-08T10:00:00Z",
                )
            ],
        )
        self.assertIn("Interactive reasoning remains a major open bottleneck", answer)
        self.assertIn("Sources:", answer)

    def test_research_ranking_prefers_primary_sources(self) -> None:
        arxiv = _score_search_result(
            {
                "title": "ARC-AGI-3 interactive reasoning benchmark",
                "url": "https://arxiv.org/abs/2603.24621",
                "snippet": "Benchmark for interactive reasoning environments.",
                "display_url": "arxiv.org",
            },
            "latest AGI interactive reasoning benchmark",
        )
        linkedin = _score_search_result(
            {
                "title": "My thoughts on AGI",
                "url": "https://www.linkedin.com/posts/example-ai-post",
                "snippet": "Personal commentary on AGI progress.",
                "display_url": "linkedin.com",
            },
            "latest AGI interactive reasoning benchmark",
        )
        self.assertGreater(arxiv, linkedin)

    def test_research_query_expansion_targets_primary_sources(self) -> None:
        queries = _expand_research_queries("latest AGI developments")
        self.assertIn("latest AGI developments site:arxiv.org", queries)
        self.assertIn("latest AGI developments site:openai.com", queries)

    def test_strip_empty_sources_footer_for_local_answers(self) -> None:
        answer = "Here is the answer.\n\nSources:\n- none"
        self.assertEqual(_strip_empty_sources_footer(answer), "Here is the answer.")


if __name__ == "__main__":
    unittest.main()
