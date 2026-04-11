from __future__ import annotations

import base64
import hashlib
import hmac
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
from .security import protect_bytes, unprotect_bytes

ACTIVE_RUN_STATUSES = {"queued", "running", "cancelling"}
PASSWORDLESS_PROTECTION = "passwordless"
PASSWORD_PROTECTED = "password"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_PASSWORD_KEY_LENGTH = 32
_INDEX_FORMAT = "atlas-dpapi-index-v1"
_RUN_FORMAT = "atlas-dpapi-run-v1"


class RunStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.runs_dir = config.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.runs_dir / "index.json"
        self._lock = threading.Lock()
        self._user_keys: dict[str, bytes] = {}
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
            if user_id not in index.get("users", {}):
                index["users"][user_id] = self._build_user_record(
                    user_id,
                    updated_at=artifact["started_at"],
                )
                self._cache_user_key_from_record(user_id, index["users"][user_id])
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
                existing_user = index.get("users", {}).get(user_id)
                index["users"][user_id] = self._build_user_record(
                    user_id,
                    updated_at=artifact["started_at"],
                    existing=existing_user,
                )
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
                    artifact = self.get_run(run_id)
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
        payload = _read_json_with_retry(path)
        return self._decode_run_payload(payload)

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

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        index = self._read_index()
        item = index.get("users", {}).get(user_id)
        if not item:
            return None
        return dict(item)

    def create_user(self, user_id: str, *, password: str | None = None) -> dict[str, Any]:
        with self._lock:
            index = self._read_index()
            existing = index.get("users", {}).get(user_id)
            if existing:
                raise RuntimeError(f"User already exists: {user_id}")
            item = self._build_user_record(
                user_id,
                updated_at=now_timestamp(),
                password=password,
            )
            index["users"][user_id] = item
            self._write_index(index)
        return dict(item)

    def upsert_user(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            index = self._read_index()
            item = self._build_user_record(
                user_id,
                updated_at=now_timestamp(),
                existing=index.get("users", {}).get(user_id),
            )
            index["users"][user_id] = item
            self._write_index(index)
        return dict(item)

    def verify_user_password(self, user_id: str, password: str) -> bool:
        user = self.get_user(user_id)
        if not user:
            raise RuntimeError(f"User not found: {user_id}")
        if user.get("protection") != PASSWORD_PROTECTED:
            return True
        encoded_salt = str(user.get("password_salt", "") or "").strip()
        encoded_hash = str(user.get("password_hash", "") or "").strip()
        if not encoded_salt or not encoded_hash:
            return False
        salt = base64.b64decode(encoded_salt.encode("ascii"))
        expected = base64.b64decode(encoded_hash.encode("ascii"))
        actual = _derive_password_hash(password, salt)
        return hmac.compare_digest(actual, expected)

    def unlock_user_key(self, user_id: str, *, password: str | None = None) -> None:
        user = self.get_user(user_id)
        if not user:
            raise RuntimeError(f"User not found: {user_id}")
        if user.get("protection") == PASSWORD_PROTECTED:
            resolved_password = (password or "").strip()
            if not resolved_password:
                raise RuntimeError("Password is required for this user.")
            if not self.verify_user_password(user_id, resolved_password):
                raise RuntimeError("Password did not match this user.")
            key = unprotect_bytes(
                base64.b64decode(str(user.get("wrapped_profile_key", "") or "").encode("ascii")),
                entropy=_derive_user_entropy(resolved_password, user),
            )
        else:
            key = unprotect_bytes(
                base64.b64decode(str(user.get("wrapped_profile_key", "") or "").encode("ascii")),
            )
        self._user_keys[user_id] = key

    def lock_user_key(self, user_id: str) -> None:
        self._user_keys.pop(user_id, None)

    def is_user_key_unlocked(self, user_id: str) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        if user.get("protection") != PASSWORD_PROTECTED:
            return True
        return user_id in self._user_keys

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
                        artifact = self.get_run(run_id)
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
            index["users"][user_id] = self._build_user_record(
                user_id,
                updated_at=resolved_updated_at,
                existing=index.get("users", {}).get(user_id),
            )
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
            self._user_keys.pop(user_id, None)
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
            self._user_keys.clear()
            self._write_index({"threads": {}, "runs": {}, "users": {}})

    def _read_index(self) -> dict[str, Any]:
        payload = _read_json_with_retry(self._index_path)
        if payload.get("format") == _INDEX_FORMAT:
            encoded = str(payload.get("payload", "") or "").strip()
            decrypted = unprotect_bytes(base64.b64decode(encoded.encode("ascii")))
            payload = json.loads(decrypted.decode("utf-8"))
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
                payload["users"][user_id] = self._build_user_record(
                    user_id,
                    updated_at=item.get("started_at", ""),
                )
        for item in payload["threads"].values():
            user_id = item.get("user_id")
            if user_id and user_id not in payload["users"]:
                payload["users"][user_id] = self._build_user_record(
                    user_id,
                    updated_at=item.get("updated_at", ""),
                )
        payload["users"] = {
            user_id: self._build_user_record(
                user_id,
                updated_at=item.get("updated_at", ""),
                existing=item,
            )
            for user_id, item in payload["users"].items()
        }
        return payload

    def _write_index(self, payload: dict[str, Any]) -> None:
        encrypted = protect_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        _atomic_write_json(
            self._index_path,
            {
                "format": _INDEX_FORMAT,
                "payload": base64.b64encode(encrypted).decode("ascii"),
            },
        )

    def _write_run_file(self, run_id: str, payload: dict[str, Any]) -> None:
        path = self.runs_dir / f"{run_id}.json"
        user_id = str(payload.get("user_id", "") or "").strip()
        if not user_id:
            _atomic_write_json(path, payload)
            return
        key = self._require_user_key(user_id)
        encrypted = protect_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), entropy=key)
        _atomic_write_json(
            path,
            {
                "format": _RUN_FORMAT,
                "user_id": user_id,
                "payload": base64.b64encode(encrypted).decode("ascii"),
            },
        )

    @staticmethod
    def _thread_key(user_id: str, thread_id: str) -> str:
        return f"{user_id}::{thread_id}"

    def _build_user_record(
        self,
        user_id: str,
        *,
        updated_at: str | None = None,
        existing: dict[str, Any] | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "user_id": user_id,
            "updated_at": updated_at or (existing or {}).get("updated_at") or now_timestamp(),
            "protection": PASSWORDLESS_PROTECTION,
            "password_hash": None,
            "password_salt": None,
            "wrapped_profile_key": None,
        }
        if existing:
            record["protection"] = str(existing.get("protection", PASSWORDLESS_PROTECTION) or PASSWORDLESS_PROTECTION)
            record["password_hash"] = existing.get("password_hash")
            record["password_salt"] = existing.get("password_salt")
            record["wrapped_profile_key"] = existing.get("wrapped_profile_key")
        if password:
            salt = os.urandom(16)
            password_hash = _derive_password_hash(password, salt)
            profile_key = os.urandom(_PASSWORD_KEY_LENGTH)
            record["protection"] = PASSWORD_PROTECTED
            record["password_salt"] = base64.b64encode(salt).decode("ascii")
            record["password_hash"] = base64.b64encode(password_hash).decode("ascii")
            record["wrapped_profile_key"] = base64.b64encode(
                protect_bytes(profile_key, entropy=password_hash)
            ).decode("ascii")
        elif record["wrapped_profile_key"] is None:
            record["wrapped_profile_key"] = base64.b64encode(
                protect_bytes(os.urandom(_PASSWORD_KEY_LENGTH))
            ).decode("ascii")
        if record["protection"] != PASSWORD_PROTECTED:
            record["protection"] = PASSWORDLESS_PROTECTION
            record["password_salt"] = None
            record["password_hash"] = None
        return record

    def _cache_user_key_from_record(self, user_id: str, user: dict[str, Any], *, password: str | None = None) -> None:
        if user.get("protection") == PASSWORD_PROTECTED:
            if not password:
                return
            key = unprotect_bytes(
                base64.b64decode(str(user.get("wrapped_profile_key", "") or "").encode("ascii")),
                entropy=_derive_user_entropy(password, user),
            )
        else:
            key = unprotect_bytes(
                base64.b64decode(str(user.get("wrapped_profile_key", "") or "").encode("ascii")),
            )
        self._user_keys[user_id] = key

    def _require_user_key(self, user_id: str) -> bytes:
        cached = self._user_keys.get(user_id)
        if cached is not None:
            return cached
        user = self.get_user(user_id)
        if not user:
            raise RuntimeError(f"User not found: {user_id}")
        if user.get("protection") == PASSWORD_PROTECTED:
            raise RuntimeError("Unlock this user before continuing.")
        self.unlock_user_key(user_id)
        cached = self._user_keys.get(user_id)
        if cached is None:
            raise RuntimeError(f"Profile key is not available for user: {user_id}")
        return cached

    def _decode_run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("format") != _RUN_FORMAT:
            return payload
        user_id = str(payload.get("user_id", "") or "").strip()
        key = self._require_user_key(user_id)
        encrypted = base64.b64decode(str(payload.get("payload", "") or "").encode("ascii"))
        decrypted = unprotect_bytes(encrypted, entropy=key)
        return json.loads(decrypted.decode("utf-8"))


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


def _derive_password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_PASSWORD_KEY_LENGTH,
    )


def _derive_user_entropy(password: str, user: dict[str, Any]) -> bytes:
    encoded_salt = str(user.get("password_salt", "") or "").strip()
    if not encoded_salt:
        raise RuntimeError("Password salt is missing for this protected user.")
    salt = base64.b64decode(encoded_salt.encode("ascii"))
    return _derive_password_hash(password, salt)
