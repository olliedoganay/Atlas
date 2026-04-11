import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from atlas_local.root_launchers import maybe_reexec_with_repo_venv, run_chat_launcher

maybe_reexec_with_repo_venv(Path(__file__).resolve())

from atlas_local.cli import main as cli_main


def main() -> int:
    return run_chat_launcher(cli_main, description="Primary launcher for Atlas.")


if __name__ == "__main__":
    raise SystemExit(main())
