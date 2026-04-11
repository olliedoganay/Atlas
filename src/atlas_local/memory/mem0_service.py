from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
import json

from mem0 import Memory

from ..config import AppConfig
from .models import MemoryCandidate, MemoryRecord, StoredMemory

class Mem0Service:
    def __init__(self, config: AppConfig):
        self.config = config
        self._memory: Memory | None = None
        _reconcile_legacy_qdrant_collections(config)

    def search(self, query: str, *, user_id: str, limit: int) -> list[StoredMemory]:
        response = self._require_memory().search(query, user_id=user_id, limit=limit, rerank=True)
        return [StoredMemory.from_dict(item) for item in response.get("results", [])]

    def add(
        self,
        candidate: MemoryCandidate | MemoryRecord,
        *,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = candidate.to_storage_text() if isinstance(candidate, MemoryCandidate) else candidate.text
        return self._require_memory().add(
            text,
            user_id=user_id,
            metadata=metadata,
            infer=False,
        )

    def update(self, memory_id: str, text: str, *, metadata: dict[str, Any] | None = None) -> None:
        self._require_memory().update(memory_id, text, metadata=metadata)

    def delete(self, memory_id: str) -> None:
        self._require_memory().delete(memory_id)

    def list(self, *, user_id: str, limit: int = 20) -> list[StoredMemory]:
        response = self._require_memory().get_all(user_id=user_id, limit=limit)
        return [StoredMemory.from_dict(item) for item in response.get("results", [])]

    def delete_all(self, *, user_id: str) -> None:
        memory = self._memory
        if memory is None:
            return
        memory.delete_all(user_id=user_id)

    def reset(self) -> None:
        memory = self._memory
        if memory is None:
            return
        memory.reset()

    def close(self) -> None:
        memory = self._memory
        if memory is None:
            return
        try:
            memory.close()
        finally:
            vector_store = getattr(memory, "vector_store", None)
            client = getattr(vector_store, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _require_memory(self) -> Memory:
        if self._memory is not None:
            return self._memory
        try:
            self._memory = Memory.from_config(
                {
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {
                            "collection_name": self.config.mem0_collection,
                            "path": str(self.config.qdrant_path),
                            "embedding_model_dims": self.config.embed_dim,
                            "on_disk": True,
                        },
                    },
                    "llm": {
                        "provider": "ollama",
                        "config": {
                            "model": self.config.chat_model,
                            "temperature": 0.0,
                            "max_tokens": 600,
                            "ollama_base_url": self.config.ollama_url,
                        },
                    },
                    "embedder": {
                        "provider": "ollama",
                        "config": {
                            "model": self.config.embed_model,
                            "ollama_base_url": self.config.ollama_url,
                        },
                    },
                    "history_db_path": str(self.config.mem0_history_db),
                }
            )
        except RuntimeError as exc:
            if "already accessed by another instance" in str(exc):
                raise RuntimeError(
                    "Local Qdrant storage is locked by another Atlas process. "
                    "Run one CLI process at a time when using local-path Qdrant, "
                    "or switch to a remote Qdrant server for concurrent access."
                ) from exc
            raise RuntimeError("Atlas memory service is unavailable.") from exc
        except Exception as exc:
            raise RuntimeError(
                "Atlas memory service is unavailable. Make sure Ollama is running and the configured models are available."
            ) from exc
        return self._memory


def _reconcile_legacy_qdrant_collections(config: AppConfig) -> None:
    collection_root = config.qdrant_path / "collection"
    if not collection_root.exists():
        return

    target_dir = collection_root / config.mem0_collection
    target_points = _local_collection_points(target_dir)
    meta_path = config.qdrant_path / "meta.json"
    metadata = _load_qdrant_metadata(meta_path)
    sibling_dirs = [path for path in collection_root.iterdir() if path.is_dir() and path != target_dir]

    if target_points is None or target_points > 0:
        _write_qdrant_metadata(meta_path, metadata)
        return

    populated_candidates: list[tuple[Path, int]] = []
    for sibling_dir in sibling_dirs:
        sibling_points = _local_collection_points(sibling_dir)
        if sibling_points is None or sibling_points <= 0:
            continue
        populated_candidates.append((sibling_dir, sibling_points))

    if len(populated_candidates) != 1:
        _write_qdrant_metadata(meta_path, metadata)
        return

    source_dir, source_points = populated_candidates[0]
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    source_dir.replace(target_dir)
    _move_collection_metadata(metadata, from_name=source_dir.name, to_name=config.mem0_collection)
    target_points = source_points

    _write_qdrant_metadata(meta_path, metadata)


def _local_collection_points(collection_dir: Path) -> int | None:
    if not collection_dir.exists():
        return 0

    database_path = collection_dir / "storage.sqlite"
    if not database_path.exists():
        return 0

    try:
        with closing(sqlite3.connect(database_path)) as conn:
            has_points_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'points'"
            ).fetchone()
            if not has_points_table:
                return 0
            row = conn.execute("SELECT COUNT(*) FROM points").fetchone()
            return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return None


def _load_qdrant_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_qdrant_metadata(path: Path, payload: dict[str, Any]) -> None:
    if not payload:
        return
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _move_collection_metadata(payload: dict[str, Any], *, from_name: str, to_name: str) -> None:
    collections = payload.get("collections")
    if not isinstance(collections, dict):
        return
    if to_name in collections:
        collections.pop(from_name, None)
        return
    if from_name in collections:
        collections[to_name] = collections.pop(from_name)
