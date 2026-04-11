from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_CHAT_MODEL = "gpt-oss:20b"
DEFAULT_CHAT_TEMPERATURE = 0.2
DEFAULT_EMBED_MODEL = "nomic-embed-text:latest"
DEFAULT_MEM0_COLLECTION = "atlas_local_memory"
DEFAULT_EMBED_DIM = 768
DEFAULT_MEMORY_TOP_K = 5
DEFAULT_WORLD_DB_PATH = ".data/world.sqlite"
DEFAULT_BROWSER_STORAGE_DIR = ".data/browser_runs"
DEFAULT_BROWSER_HEADLESS = True
DEFAULT_MAX_BROWSER_STEPS = 8
DEFAULT_SEARCH_PROVIDER = "yahoo_browser"
DEFAULT_BENCHMARKS_DIR = ".data/benchmarks"
DEFAULT_EVALS_DIR = ".data/evals"
DEFAULT_ACTIVE_PROFILE = "default"
DEFAULT_PROPOSALS_DIR = ".data/profiles"


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    prompt_dir: Path
    data_dir: Path
    qdrant_path: Path
    langgraph_checkpoint_db: Path
    mem0_history_db: Path
    world_db_path: Path
    browser_storage_dir: Path
    benchmarks_dir: Path
    evals_dir: Path
    proposals_dir: Path
    ollama_url: str
    chat_model: str
    chat_temperature: float
    embed_model: str
    mem0_collection: str
    embed_dim: int
    memory_top_k: int
    browser_headless: bool
    max_browser_steps: int
    search_provider: str
    web_allowlist: tuple[str, ...]
    web_blocklist: tuple[str, ...]
    active_profile: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _path_value(env: Mapping[str, str], key: str, default: Path, *, base: Path | None = None) -> Path:
    raw = env.get(key)
    if not raw or not str(raw).strip():
        return default
    path = Path(str(raw).strip())
    if path.is_absolute() or base is None:
        return path
    return base / path


def _value(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _bool_value(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = _value(env, key, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _list_value(env: Mapping[str, str], key: str) -> tuple[str, ...]:
    raw = _value(env, key, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_config(
    *,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> AppConfig:
    fallback_root = project_root or _repo_root()
    root = fallback_root
    load_dotenv(root / ".env")
    source = dict(os.environ)
    if env:
        source.update(env)

    root = _path_value(source, "ATLAS_PROJECT_ROOT", fallback_root, base=fallback_root)
    prompt_dir = _path_value(source, "ATLAS_PROMPT_DIR", root / "prompts", base=root)
    data_dir = _path_value(source, "ATLAS_DATA_DIR", root / ".data", base=root)
    qdrant_path = _path_value(source, "QDRANT_PATH", root / ".data" / "qdrant", base=root)
    checkpoint_db = _path_value(
        source,
        "LANGGRAPH_CHECKPOINT_DB",
        root / ".data" / "langgraph" / "checkpoints.sqlite",
        base=root,
    )
    world_db_path = _path_value(source, "WORLD_DB_PATH", root / DEFAULT_WORLD_DB_PATH, base=root)
    browser_storage_dir = _path_value(
        source,
        "BROWSER_STORAGE_DIR",
        root / DEFAULT_BROWSER_STORAGE_DIR,
        base=root,
    )
    benchmarks_dir = _path_value(source, "BENCHMARKS_DIR", root / DEFAULT_BENCHMARKS_DIR, base=root)
    evals_dir = _path_value(source, "EVALS_DIR", root / DEFAULT_EVALS_DIR, base=root)
    proposals_dir = _path_value(source, "PROPOSALS_DIR", root / DEFAULT_PROPOSALS_DIR, base=root)
    mem0_history_db = _path_value(
        source,
        "MEM0_HISTORY_DB",
        data_dir / "mem0_history.sqlite",
        base=data_dir,
    )

    qdrant_path.mkdir(parents=True, exist_ok=True)
    checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
    mem0_history_db.parent.mkdir(parents=True, exist_ok=True)
    world_db_path.parent.mkdir(parents=True, exist_ok=True)
    browser_storage_dir.mkdir(parents=True, exist_ok=True)
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    evals_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        project_root=root,
        prompt_dir=prompt_dir,
        data_dir=data_dir,
        qdrant_path=qdrant_path,
        langgraph_checkpoint_db=checkpoint_db,
        mem0_history_db=mem0_history_db,
        world_db_path=world_db_path,
        browser_storage_dir=browser_storage_dir,
        benchmarks_dir=benchmarks_dir,
        evals_dir=evals_dir,
        proposals_dir=proposals_dir,
        ollama_url=_value(source, "OLLAMA_URL", DEFAULT_OLLAMA_URL),
        chat_model=_value(source, "CHAT_MODEL", DEFAULT_CHAT_MODEL),
        chat_temperature=float(_value(source, "CHAT_TEMPERATURE", str(DEFAULT_CHAT_TEMPERATURE))),
        embed_model=_value(source, "EMBED_MODEL", DEFAULT_EMBED_MODEL),
        mem0_collection=_value(source, "MEM0_COLLECTION", DEFAULT_MEM0_COLLECTION),
        embed_dim=int(_value(source, "EMBED_DIM", str(DEFAULT_EMBED_DIM))),
        memory_top_k=int(_value(source, "MEMORY_TOP_K", str(DEFAULT_MEMORY_TOP_K))),
        browser_headless=_bool_value(source, "BROWSER_HEADLESS", DEFAULT_BROWSER_HEADLESS),
        max_browser_steps=int(
            _value(source, "MAX_BROWSER_STEPS", str(DEFAULT_MAX_BROWSER_STEPS))
        ),
        search_provider=_value(source, "SEARCH_PROVIDER", DEFAULT_SEARCH_PROVIDER),
        web_allowlist=_list_value(source, "WEB_ALLOWLIST"),
        web_blocklist=_list_value(source, "WEB_BLOCKLIST"),
        active_profile=_value(source, "ACTIVE_PROFILE", DEFAULT_ACTIVE_PROFILE),
    )
