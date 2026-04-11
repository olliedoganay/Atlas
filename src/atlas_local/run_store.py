from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import AppConfig
from .run_contract import RunEvent, RunTraceItem, make_run_event, make_trace_item, now_timestamp

ACTIVE_RUN_STATUSES = {"queued", "running", "cancelling"}


class RunStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.runs_dir = config.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.runs_dir / "index.json"
        self._lock = threading.Lock()
        if not self._index_path.exists():
            self._write_index({"threads": {}, "runs": {}, "users": {}})

    def create_run(
        self,
        *,
        mode: str,
        user_id: str,
        thread_id: str,
        chat_model: str,
        temperature: float | None,
        prompt: str,
        thread_title: str | None = None,
        status: str = "running",
        touch_thread: bool = True,
        history_after_message_count: int = 0,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        index = self._read_index()
        existing_thread = index.get("threads", {}).get(self._thread_key(user_id, thread_id), {})
        resolved_title = (thread_title or "").strip() or existing_thread.get("title") or thread_id
        artifact = {
            "run_id": run_id,
            "mode": mode,
            "user_id": user_id,
            "thread_id": thread_id,
            "thread_title": resolved_title,
            "chat_model": chat_model,
            "temperature": temperature,
            "prompt": prompt,
            "status": status,
            "history_after_message_count": max(0, int(history_after_message_count or 0)),
            "started_at": now_timestamp(),
            "completed_at": None,
            "answer": "",
            "events": [],
            "trace_items": [],
            "error": None,
        }
        with self._lock:
            self._write_run_file(run_id, artifact)
            index["runs"][run_id] = {
                "run_id": run_id,
                "mode": mode,
                "user_id": user_id,
                "thread_id": thread_id,
                "thread_title": resolved_title,
                "chat_model": chat_model,
                "temperature": temperature,
                "status": status,
                "history_after_message_count": artifact["history_after_message_count"],
                "started_at": artifact["started_at"],
            }
            if touch_thread:
                index["threads"][self._thread_key(user_id, thread_id)] = {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "title": resolved_title,
                    "chat_model": chat_model,
                    "temperature": temperature,
                    "last_mode": mode,
                    "updated_at": artifact["started_at"],
                    "last_prompt": prompt[:120],
                    "last_run_id": run_id,
                }
                index["users"][user_id] = {
                    "user_id": user_id,
                    "updated_at": artifact["started_at"],
                }
            self._write_index(index)
        return artifact

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEvent:
        event = make_run_event(event_type, payload)
        with self._lock:
            artifact = self.get_run(run_id)
            artifact["events"].append(event)
            if event_type == "token":
                artifact["answer"] = f"{artifact.get('answer', '')}{payload.get('text', '')}"
            self._write_run_file(run_id, artifact)
        return event

    def append_trace_item(self, run_id: str, item: dict[str, Any]) -> RunTraceItem:
        enriched = make_trace_item(item)
        with self._lock:
            artifact = self.get_run(run_id)
            artifact["trace_items"].append(enriched)
            self._write_run_file(run_id, artifact)
        return enriched

    def complete_run(self, run_id: str, *, answer: str) -> dict[str, Any]:
        with self._lock:
            artifact = self.get_run(run_id)
            artifact["status"] = "completed"
            artifact["completed_at"] = now_timestamp()
            artifact["answer"] = answer
            self._write_run_file(run_id, artifact)
            index = self._read_index()
            if run_id in index["runs"]:
                index["runs"][run_id]["status"] = "completed"
                index["runs"][run_id]["completed_at"] = artifact["completed_at"]
                index["runs"][run_id]["thread_title"] = artifact.get("thread_title", artifact.get("thread_id", ""))
            self._write_index(index)
        return artifact

    def mark_run_running(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            artifact = self.get_run(run_id)
            artifact["status"] = "running"
            self._write_run_file(run_id, artifact)
            index = self._read_index()
            if run_id in index["runs"]:
                index["runs"][run_id]["status"] = "running"
            self._write_index(index)
        return artifact

    def mark_run_cancelling(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            artifact = self.get_run(run_id)
            if artifact.get("status") not in {"completed", "failed"}:
                artifact["status"] = "cancelling"
                self._write_run_file(run_id, artifact)
            index = self._read_index()
            if run_id in index["runs"] and index["runs"][run_id].get("status") not in {"completed", "failed"}:
                index["runs"][run_id]["status"] = "cancelling"
            self._write_index(index)
        return artifact

    def fail_run(self, run_id: str, *, error: str) -> dict[str, Any]:
        with self._lock:
            artifact = self.get_run(run_id)
            artifact["status"] = "failed"
            artifact["completed_at"] = now_timestamp()
            artifact["error"] = error
            self._write_run_file(run_id, artifact)
            index = self._read_index()
            if run_id in index["runs"]:
                index["runs"][run_id]["status"] = "failed"
                index["runs"][run_id]["completed_at"] = artifact["completed_at"]
                index["runs"][run_id]["thread_title"] = artifact.get("thread_title", artifact.get("thread_id", ""))
            self._write_index(index)
        return artifact

    def fail_incomplete_runs(self, *, error: str) -> list[str]:
        recovered: list[str] = []
        with self._lock:
            index = self._read_index()
            for run_id, item in index.get("runs", {}).items():
                if item.get("status") not in ACTIVE_RUN_STATUSES:
                    continue
                timestamp = now_timestamp()
                path = self.runs_dir / f"{run_id}.json"
                if path.exists():
                    artifact = _read_json_with_retry(path)
                else:
                    artifact = {
                        "run_id": run_id,
                        "mode": item.get("mode", "chat"),
                        "user_id": item.get("user_id", ""),
                        "thread_id": item.get("thread_id", ""),
                        "thread_title": item.get("thread_title", item.get("thread_id", "")),
                        "chat_model": item.get("chat_model", ""),
                        "temperature": item.get("temperature"),
                        "prompt": "",
                        "status": item.get("status", "failed"),
                        "history_after_message_count": int(item.get("history_after_message_count", 0) or 0),
                        "started_at": item.get("started_at", timestamp),
                        "completed_at": None,
                        "answer": "",
                        "events": [],
                        "trace_items": [],
                        "error": None,
                    }
                artifact["status"] = "failed"
                artifact["completed_at"] = timestamp
                artifact["error"] = error
                artifact.setdefault("events", [])
                artifact["events"].append(make_run_event("run_failed", {"error": error}, timestamp=timestamp))
                self._write_run_file(run_id, artifact)
                item["status"] = "failed"
                item["completed_at"] = timestamp
                recovered.append(run_id)
            self._write_index(index)
        return recovered

    def get_run(self, run_id: str) -> dict[str, Any]:
        path = self.runs_dir / f"{run_id}.json"
        if not path.exists():
            raise RuntimeError(f"Run not found: {run_id}")
        return _read_json_with_retry(path)

    def list_threads(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        index = self._read_index()
        items = list(index.get("threads", {}).values())
        if user_id:
            items = [item for item in items if item.get("user_id") == user_id]
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def list_runs_for_thread(self, *, user_id: str | None, thread_id: str) -> list[dict[str, Any]]:
        index = self._read_index()
        run_ids = [
            run_id
            for run_id, item in index.get("runs", {}).items()
            if item.get("thread_id") == thread_id and (user_id is None or item.get("user_id") == user_id)
        ]
        artifacts: list[dict[str, Any]] = []
        for run_id in run_ids:
            try:
                artifacts.append(self.get_run(run_id))
            except RuntimeError:
                continue
        artifacts.sort(key=lambda item: (str(item.get("started_at", "") or ""), str(item.get("run_id", "") or "")))
        return artifacts

    def list_users(self) -> list[dict[str, Any]]:
        index = self._read_index()
        items = list(index.get("users", {}).values())
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def upsert_user(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            index = self._read_index()
            item = {
                "user_id": user_id,
                "updated_at": now_timestamp(),
            }
            index["users"][user_id] = item
            self._write_index(index)
        return item

    def get_thread(self, *, user_id: str, thread_id: str) -> dict[str, Any] | None:
        index = self._read_index()
        thread = index.get("threads", {}).get(self._thread_key(user_id, thread_id))
        if thread:
            return dict(thread)
        run_id = ""
        for item in index.get("runs", {}).values():
            if item.get("user_id") == user_id and item.get("thread_id") == thread_id:
                run_id = str(item.get("run_id", ""))
                break
        if not run_id:
            return None
        try:
            artifact = self.get_run(run_id)
        except RuntimeError:
            return None
        return {
            "user_id": user_id,
            "thread_id": thread_id,
            "title": artifact.get("thread_title") or thread_id,
            "chat_model": artifact.get("chat_model", ""),
            "temperature": artifact.get("temperature", self.config.chat_temperature),
            "last_mode": artifact.get("mode", ""),
            "updated_at": artifact.get("completed_at") or artifact.get("started_at", ""),
            "last_prompt": str(artifact.get("prompt", ""))[:120],
            "last_run_id": run_id,
        }

    def rename_thread(self, *, user_id: str, thread_id: str, title: str) -> dict[str, Any]:
        resolved_title = title.strip() or thread_id
        with self._lock:
            index = self._read_index()
            thread_key = self._thread_key(user_id, thread_id)
            thread = dict(index.get("threads", {}).get(thread_key) or {})
            if not thread:
                thread = {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "chat_model": "",
                    "temperature": None,
                    "last_mode": "chat",
                    "updated_at": now_timestamp(),
                    "last_prompt": "",
                    "last_run_id": "",
                }
            thread["title"] = resolved_title
            thread["updated_at"] = now_timestamp()
            thread.setdefault("temperature", self.config.chat_temperature)
            index["threads"][thread_key] = thread
            for run_id, item in index.get("runs", {}).items():
                if item.get("user_id") == user_id and item.get("thread_id") == thread_id:
                    item["thread_title"] = resolved_title
                    path = self.runs_dir / f"{run_id}.json"
                    if path.exists():
                        artifact = _read_json_with_retry(path)
                        artifact["thread_title"] = resolved_title
                        self._write_run_file(run_id, artifact)
            self._write_index(index)
        return dict(thread)

    def upsert_thread(
        self,
        *,
        user_id: str,
        thread_id: str,
        title: str,
        chat_model: str,
        temperature: float | None,
        last_mode: str = "chat",
        updated_at: str | None = None,
        last_prompt: str = "",
        last_run_id: str = "",
    ) -> dict[str, Any]:
        resolved_updated_at = updated_at or now_timestamp()
        thread = {
            "user_id": user_id,
            "thread_id": thread_id,
            "title": title.strip() or thread_id,
            "chat_model": chat_model,
            "temperature": temperature,
            "last_mode": last_mode,
            "updated_at": resolved_updated_at,
            "last_prompt": last_prompt[:120],
            "last_run_id": last_run_id,
        }
        with self._lock:
            index = self._read_index()
            index["threads"][self._thread_key(user_id, thread_id)] = thread
            index["users"][user_id] = {
                "user_id": user_id,
                "updated_at": resolved_updated_at,
            }
            self._write_index(index)
        return dict(thread)

    def delete_thread(self, *, user_id: str | None, thread_id: str) -> None:
        with self._lock:
            index = self._read_index()
            thread_keys = [
                key
                for key, item in index.get("threads", {}).items()
                if item.get("thread_id") == thread_id and (user_id is None or item.get("user_id") == user_id)
            ]
            run_ids = [
                run_id
                for run_id, item in index.get("runs", {}).items()
                if item.get("thread_id") == thread_id and (user_id is None or item.get("user_id") == user_id)
            ]
            for key in thread_keys:
                index["threads"].pop(key, None)
                user_value = index.get("users", {}).get(user_id or "")
                if user_value and not any(
                    item.get("user_id") == (user_id or "")
                    for existing_key, item in index.get("threads", {}).items()
                    if existing_key != key
                ):
                    index.get("users", {}).pop(user_id or "", None)
            for run_id in run_ids:
                index["runs"].pop(run_id, None)
                path = self.runs_dir / f"{run_id}.json"
                if path.exists():
                    path.unlink()
            self._write_index(index)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            index = self._read_index()
            thread_keys = [
                key for key, item in index.get("threads", {}).items() if item.get("user_id") == user_id
            ]
            run_ids = [
                run_id for run_id, item in index.get("runs", {}).items() if item.get("user_id") == user_id
            ]
            for key in thread_keys:
                index["threads"].pop(key, None)
            index.get("users", {}).pop(user_id, None)
            for run_id in run_ids:
                index["runs"].pop(run_id, None)
                path = self.runs_dir / f"{run_id}.json"
                if path.exists():
                    path.unlink()
            self._write_index(index)

    def reset_all(self) -> None:
        with self._lock:
            for item in self.runs_dir.iterdir():
                if item.name == "index.json":
                    continue
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            self._write_index({"threads": {}, "runs": {}, "users": {}})

    def _read_index(self) -> dict[str, Any]:
        payload = _read_json_with_retry(self._index_path)
        payload.setdefault("threads", {})
        payload.setdefault("runs", {})
        payload.setdefault("users", {})
        for item in payload["threads"].values():
            item.setdefault("title", item.get("thread_id", ""))
            item.setdefault("temperature", self.config.chat_temperature)
        for item in payload["runs"].values():
            item.setdefault("thread_title", item.get("thread_id", ""))
            item.setdefault("temperature", self.config.chat_temperature)
            item.setdefault("history_after_message_count", 0)
            user_id = item.get("user_id")
            if user_id and user_id not in payload["users"]:
                payload["users"][user_id] = {"user_id": user_id, "updated_at": item.get("started_at", "")}
        for item in payload["threads"].values():
            user_id = item.get("user_id")
            if user_id and user_id not in payload["users"]:
                payload["users"][user_id] = {"user_id": user_id, "updated_at": item.get("updated_at", "")}
        return payload

    def _write_index(self, payload: dict[str, Any]) -> None:
        _atomic_write_json(self._index_path, payload)

    def _write_run_file(self, run_id: str, payload: dict[str, Any]) -> None:
        path = self.runs_dir / f"{run_id}.json"
        _atomic_write_json(path, payload)

    @staticmethod
    def _thread_key(user_id: str, thread_id: str) -> str:
        return f"{user_id}::{thread_id}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    last_error: PermissionError | None = None

    for attempt in range(6):
        temp_path = path.with_name(
            f"{path.stem}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
        finally:
            temp_path.unlink(missing_ok=True)

    if last_error is not None:
        raise last_error


def _read_json_with_retry(path: Path) -> dict[str, Any]:
    last_error: PermissionError | None = None
    for attempt in range(6):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))
