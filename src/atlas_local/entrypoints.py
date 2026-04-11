from __future__ import annotations

from .api import main as api_main
from .cli import main as cli_main
from .root_launchers import run_chat_launcher


def atlas_main() -> int:
    return run_chat_launcher(cli_main, description="Primary launcher for Atlas.")


def atlas_backend_main() -> int:
    return api_main()
