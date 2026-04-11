import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

import atlas


class AtlasWrapperTests(unittest.TestCase):
    @patch("atlas.cli_main", return_value=0)
    def test_no_args_launches_chat(self, cli_main_mock) -> None:
        with patch("sys.argv", ["atlas.py", "--user-id", "u1"]):
            exit_code = atlas.main()
        self.assertEqual(exit_code, 0)
        cli_main_mock.assert_called_once_with(["chat", "--thread-id", "main", "--user-id", "u1"])

    @patch("atlas.cli_main", return_value=0)
    def test_question_launches_ask(self, cli_main_mock) -> None:
        with patch("sys.argv", ["atlas.py", "--user-id", "u1", "hello"]):
            exit_code = atlas.main()
        self.assertEqual(exit_code, 0)
        cli_main_mock.assert_called_once_with(["ask", "hello", "--thread-id", "main", "--user-id", "u1"])

    @patch("atlas.cli_main", return_value=0)
    def test_ask_flag_launches_ask(self, cli_main_mock) -> None:
        with patch("sys.argv", ["atlas.py", "--user-id", "u1", "--ask", "latest findings"]):
            exit_code = atlas.main()
        self.assertEqual(exit_code, 0)
        cli_main_mock.assert_called_once_with(["ask", "latest findings", "--thread-id", "main", "--user-id", "u1"])

    def test_user_id_is_required(self) -> None:
        with patch("sys.argv", ["atlas.py"]):
            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as exc_info:
                    atlas.main()
        self.assertEqual(exc_info.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
