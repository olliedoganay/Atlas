from __future__ import annotations

import sys
from pathlib import Path


def configure_console() -> None:
    """Force UTF-8 console output to avoid Windows cp1252 crashes."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def read_prompt(prompt_dir: Path, name: str) -> str:
    return (prompt_dir / name).read_text(encoding="utf-8").strip()
