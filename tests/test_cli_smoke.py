import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from atlas_local.cli import main


class FakeApp:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ask(self, prompt: str, *, user_id: str, thread_id: str, research_mode: bool = False):
        return {
            "answer": f"echo:{prompt}|{user_id}|{thread_id}|research={research_mode}",
            "reasoning_report": {"claims": [], "violations": [], "recommendations": []},
            "citations": [],
        }

    def list_memories(self, *, user_id: str, limit: int = 20):
        return []


class CliSmokeTests(unittest.TestCase):
    @patch("atlas_local.cli.build_chat_application", return_value=FakeApp())
    def test_ask_command_prints_answer(self, _build_app) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                ["ask", "hello", "--user-id", "u1", "--thread-id", "t1"]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("echo:hello|u1|t1|research=False", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
