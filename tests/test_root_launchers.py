import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_local.root_launchers import maybe_reexec_with_repo_venv


class RootLauncherTests(unittest.TestCase):
    def test_reexecs_into_repo_venv_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            script_path = repo_root / "atlas.py"
            repo_python = repo_root / ".venv" / "Scripts" / "python.exe"
            script_path.write_text("print('atlas')", encoding="utf-8")
            repo_python.parent.mkdir(parents=True, exist_ok=True)
            repo_python.write_text("", encoding="utf-8")

            with patch("atlas_local.root_launchers.sys.executable", str(repo_root / "python.exe")):
                with patch("atlas_local.root_launchers.sys.argv", ["atlas.py", "--ask", "hello"]):
                    with patch("atlas_local.root_launchers.os.execv") as execv_mock:
                        maybe_reexec_with_repo_venv(script_path)

            execv_mock.assert_called_once_with(
                str(repo_python.resolve()),
                [str(repo_python.resolve()), str(script_path), "--ask", "hello"],
            )

    def test_skips_reexec_when_already_using_repo_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            script_path = repo_root / "atlas.py"
            repo_python = repo_root / ".venv" / "Scripts" / "python.exe"
            script_path.write_text("print('atlas')", encoding="utf-8")
            repo_python.parent.mkdir(parents=True, exist_ok=True)
            repo_python.write_text("", encoding="utf-8")

            with patch("atlas_local.root_launchers.sys.executable", str(repo_python.resolve())):
                with patch("atlas_local.root_launchers.os.execv") as execv_mock:
                    maybe_reexec_with_repo_venv(script_path)

            execv_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
