from __future__ import annotations

import base64
import os
import queue
import shutil
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .config import AppConfig, load_config
from .graph.builder import AgentApplication, build_chat_application
from .graph.builder import post_synthesis_node_sequence, pre_synthesis_node_sequence
from .graph.context import GraphContext
from .graph.nodes import _build_answer_messages, _finalize_answer_text, _latest_user_text
from .llm import OllamaCatalogSnapshot, OllamaModelInfo, inspect_local_ollama_models
from .memory.models import MemoryRecord
from .run_contract import RunEvent, RunHub, TERMINAL_EVENT_TYPES
from .run_store import PASSWORD_PROTECTED, RunStore
from .security import open_application_sqlite, sqlcipher_enabled
from .session import scoped_thread_id
from .text_normalization import MojibakeRepairStream


@dataclass
class _QueuedRunJob:
    mode: str
    run_id: str
    prompt: str
    user_id: str
    thread_id: str
    chat_model: str
    temperature: float | None
    cross_chat_memory: bool
    auto_compact_long_chats: bool
    images: list[dict[str, str]]


@dataclass
class AtlasBackendService:
    config: AppConfig
    app: AgentApplication
    run_store: RunStore
    run_hub: RunHub
    _control_lock: threading.Lock = field(default_factory=threading.Lock)
    _active_run_id: str | None = None
    _cancelled_runs: set[str] = field(default_factory=set)
    _pending_runs: list[_QueuedRunJob] = field(default_factory=list)
    _worker_wakeup: threading.Event = field(default_factory=threading.Event)
    _worker_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _shutdown_requested: bool = field(default=False, init=False, repr=False)
    _model_catalog_cache: tuple[float, OllamaCatalogSnapshot] | None = field(default=None, init=False, repr=False)
    _unlocked_users: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, config: AppConfig | None = None) -> "AtlasBackendService":
        resolved = config or load_config()
        service = cls(
            config=resolved,
            app=build_chat_application(resolved),
            run_store=RunStore(resolved),
            run_hub=RunHub(),
        )
        service._recover_incomplete_runs()
        service._ensure_worker_started()
        return service

    def close(self) -> None:
        self._ensure_runtime_state()
        error_message = "Atlas backend restarted while this run was active."
        active_run_id: str | None = None
        pending_run_ids: list[str] = []
        with self._control_lock:
            self._shutdown_requested = True
            active_run_id = self._active_run_id
            pending_run_ids = [job.run_id for job in self._pending_runs]
            self._pending_runs.clear()
            if active_run_id:
                self._cancelled_runs.add(active_run_id)
        for run_id in pending_run_ids:
            self.run_store.fail_run(run_id, error=error_message)
            self._emit_event(run_id, "run_failed", {"error": error_message})
        if active_run_id:
            self.run_store.mark_run_cancelling(active_run_id)
            self.app.llm_provider.abort_active_requests()
        self._worker_wakeup.set()
        worker = self._worker_thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self.app.close()

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "product": "Atlas"}

    def status(self) -> dict[str, Any]:
        self._ensure_runtime_state()
        with self._control_lock:
            busy = self._active_run_id is not None or bool(self._pending_runs)
        supports_dpapi = os.name == "nt"
        return {
            "status": "ok",
            "product_name": "Atlas",
            "backend": "Atlas local runtime",
            "default_chat_model": self.config.chat_model,
            "chat_model": self.config.chat_model,
            "default_chat_temperature": self.config.chat_temperature,
            "chat_temperature": self.config.chat_temperature,
            "embed_model": self.config.embed_model,
            "ollama_url": self.config.ollama_url,
            "runtime_mode": "chat-only",
            "busy": busy,
            "security": {
                "profile_key_protection": "windows-dpapi" if supports_dpapi else "not-available",
                "run_artifacts_encrypted_at_rest": supports_dpapi,
                "run_index_encrypted_at_rest": supports_dpapi,
                "packaged_logs_default": "off",
                "sqlite_encrypted_at_rest": sqlcipher_enabled(),
                "sqlite_paths": [
                    str(self.config.langgraph_checkpoint_db),
                    str(self.config.mem0_history_db),
                ],
                "vector_store": "local-qdrant",
                "vector_store_encrypted_at_rest": sqlcipher_enabled(),
                "vector_store_path": str(self.config.qdrant_path),
            },
        }

    def _ensure_runtime_state(self) -> None:
        if not hasattr(self, "_control_lock") or self._control_lock is None:
            self._control_lock = threading.Lock()
        if not hasattr(self, "_active_run_id"):
            self._active_run_id = None
        if not hasattr(self, "_cancelled_runs") or self._cancelled_runs is None:
            self._cancelled_runs = set()
        if not hasattr(self, "_pending_runs") or self._pending_runs is None:
            self._pending_runs = []
        if not hasattr(self, "_worker_wakeup") or self._worker_wakeup is None:
            self._worker_wakeup = threading.Event()
        if not hasattr(self, "_shutdown_requested"):
            self._shutdown_requested = False
        if not hasattr(self, "_model_catalog_cache"):
            self._model_catalog_cache = None
        if not hasattr(self, "_worker_thread"):
            self._worker_thread = None
        if not hasattr(self, "_unlocked_users") or self._unlocked_users is None:
            self._unlocked_users = set()

    def _ensure_worker_started(self) -> None:
        self._ensure_runtime_state()
        with self._control_lock:
            worker = self._worker_thread
            if worker is not None and worker.is_alive():
                return
            self._shutdown_requested = False
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="atlas-run-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def _recover_incomplete_runs(self) -> None:
        fail_incomplete_runs = getattr(self.run_store, "fail_incomplete_runs", None)
        if callable(fail_incomplete_runs):
            fail_incomplete_runs(error="Atlas backend restarted while this run was active.")

    def _worker_loop(self) -> None:
        while True:
            self._worker_wakeup.wait()
            self._worker_wakeup.clear()

            while True:
                job = self._claim_next_job()
                if job is None:
                    with self._control_lock:
                        if self._shutdown_requested:
                            return
                    break

                try:
                    if job.mode == "chat":
                        self._execute_run(
                            run_id=job.run_id,
                            prompt=job.prompt,
                            user_id=job.user_id,
                            thread_id=job.thread_id,
                            chat_model=job.chat_model,
                            temperature=job.temperature,
                            cross_chat_memory=job.cross_chat_memory,
                            auto_compact_long_chats=job.auto_compact_long_chats,
                            images=job.images,
                        )
                    elif job.mode == "compact":
                        self._execute_compact_run(
                            run_id=job.run_id,
                            user_id=job.user_id,
                            thread_id=job.thread_id,
                            chat_model=job.chat_model,
                        )
                    else:
                        raise RuntimeError(f"Unsupported queued run mode: {job.mode}")
                finally:
                    with self._control_lock:
                        if self._active_run_id == job.run_id:
                            self._active_run_id = None
                        self._cancelled_runs.discard(job.run_id)
                    self._worker_wakeup.set()

    def _claim_next_job(self) -> _QueuedRunJob | None:
        with self._control_lock:
            if self._shutdown_requested or self._active_run_id is not None or not self._pending_runs:
                return None
            job = self._pending_runs.pop(0)
            self._active_run_id = job.run_id
            self.run_store.mark_run_running(job.run_id)
            return job

    def list_models(self) -> dict[str, Any]:
        catalog = self._get_model_catalog()
        return {
            "default_model": self.config.chat_model,
            "default_temperature": self.config.chat_temperature,
            "temperature_presets": [
                {"label": f"{value:.1f}", "value": value}
                for value in _temperature_dropdown_values()
            ],
            "ollama_online": catalog.ollama_online,
            "has_local_models": catalog.has_local_models,
            "catalog_source": catalog.source,
            "models": [item.name for item in catalog.models],
            "model_details": [item.to_dict() for item in catalog.models],
        }

    def list_users(self) -> list[dict[str, Any]]:
        self._ensure_runtime_state()
        items = self.run_store.list_users()
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [self._sanitize_user_summary(item) for item in items]

    def create_user(self, *, user_id: str, password: str | None = None) -> dict[str, Any]:
        self._ensure_runtime_state()
        resolved = user_id.strip()
        if not resolved:
            raise RuntimeError("User id is required.")
        resolved_password = (password or "").strip() or None
        item = self.run_store.create_user(resolved, password=resolved_password)
        if item.get("protection") == PASSWORD_PROTECTED:
            self.run_store.unlock_user_key(resolved, password=resolved_password)
            self._unlocked_users.add(resolved)
        return self._sanitize_user_summary(item)

    def unlock_user(self, *, user_id: str, password: str | None = None) -> dict[str, Any]:
        self._ensure_runtime_state()
        resolved = user_id.strip()
        if not resolved:
            raise RuntimeError("User id is required.")
        user = self._lookup_user_record(resolved)
        if not user:
            raise RuntimeError(f"User not found: {resolved}")
        if user.get("protection") == PASSWORD_PROTECTED:
            resolved_password = (password or "").strip()
            if not resolved_password:
                raise RuntimeError("Password is required for this user.")
            self.run_store.unlock_user_key(resolved, password=resolved_password)
            self._unlocked_users.add(resolved)
        else:
            self.run_store.unlock_user_key(resolved)
        return self._sanitize_user_summary(user)

    def lock_user(self, *, user_id: str) -> dict[str, Any]:
        self._ensure_runtime_state()
        resolved = user_id.strip()
        if not resolved:
            raise RuntimeError("User id is required.")
        user = self._lookup_user_record(resolved)
        if not user:
            raise RuntimeError(f"User not found: {resolved}")
        self._unlocked_users.discard(resolved)
        self.run_store.lock_user_key(resolved)
        return self._sanitize_user_summary(user)

    def add_memory(self, *, user_id: str, text: str) -> dict[str, Any]:
        resolved_user_id = user_id.strip()
        resolved_text = text.strip()
        if not resolved_user_id:
            raise RuntimeError("User id is required.")
        if not resolved_text:
            raise RuntimeError("Memory text is required.")
        self._ensure_user_unlocked(resolved_user_id)
        response = self.app.memory_service.add(
            MemoryRecord(claim_id=f"manual:{uuid4()}", text=resolved_text),
            user_id=resolved_user_id,
            metadata={"source": "manual", "kind": "memory_note"},
        )
        results = response.get("results", []) if isinstance(response, dict) else []
        memory_id = ""
        if results and isinstance(results[0], dict):
            memory_id = str(results[0].get("id", "")).strip()
        self.run_store.upsert_user(resolved_user_id)
        return {"status": "ok", "user_id": resolved_user_id, "memory_id": memory_id, "text": resolved_text}

    def delete_memory(self, *, user_id: str, memory_id: str) -> dict[str, Any]:
        resolved_user_id = user_id.strip()
        resolved_memory_id = memory_id.strip()
        if not resolved_user_id:
            raise RuntimeError("User id is required.")
        if not resolved_memory_id:
            raise RuntimeError("Memory id is required.")
        self._ensure_user_unlocked(resolved_user_id)
        self.app.memory_service.delete(resolved_memory_id)
        return {"status": "ok", "user_id": resolved_user_id, "memory_id": resolved_memory_id}

    def list_threads(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        items = self.run_store.list_threads(user_id=user_id)
        if user_id:
            self._ensure_user_unlocked(user_id)
            items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
            return items
        checkpoint_threads = self._list_checkpoint_threads()
        seen = {(item["user_id"], item["thread_id"]) for item in items}
        for thread_id in checkpoint_threads:
            key = (user_id or "", thread_id)
            if user_id and key in seen:
                continue
            if not user_id and any(item["thread_id"] == thread_id for item in items):
                continue
            items.append(
                {
                    "user_id": user_id or "",
                    "thread_id": thread_id,
                    "title": thread_id,
                    "chat_model": "",
                    "temperature": None,
                    "last_mode": "chat",
                    "updated_at": "",
                    "last_prompt": "",
                    "last_run_id": "",
                }
            )
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def rename_thread(self, *, user_id: str, thread_id: str, title: str) -> dict[str, Any]:
        if not user_id.strip():
            raise RuntimeError("User id is required.")
        if not thread_id.strip():
            raise RuntimeError("Thread id is required.")
        self._ensure_user_unlocked(user_id)
        return self.run_store.rename_thread(user_id=user_id, thread_id=thread_id, title=title)

    def duplicate_thread(self, *, user_id: str, thread_id: str) -> dict[str, Any]:
        if not user_id.strip():
            raise RuntimeError("User id is required.")
        if not thread_id.strip():
            raise RuntimeError("Thread id is required.")
        self._ensure_user_unlocked(user_id)
        source_thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        if not source_thread:
            raise RuntimeError(f"Thread not found: {thread_id}")

        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        history_messages = list(snapshot.values.get("messages", []))
        duplicate_thread_id = f"atlas-{datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S')}-{uuid4().hex[:4]}"
        duplicate_title = _duplicate_thread_title(source_thread.get("title") or thread_id)
        duplicate_session_id = scoped_thread_id(user_id, duplicate_thread_id)
        timeline_events = _persistent_thread_timeline_events(snapshot.values.get("timeline_events", []))

        if history_messages:
            self.app.graph.update_state(
                {"configurable": {"thread_id": duplicate_session_id}},
                {
                    "messages": history_messages,
                    "thread_summary": str(snapshot.values.get("thread_summary", "") or ""),
                    "compacted_message_count": int(snapshot.values.get("compacted_message_count", 0) or 0),
                    "detected_context_window": int(snapshot.values.get("detected_context_window", 0) or 0),
                    "timeline_events": timeline_events,
                },
                as_node="persist",
            )

        return self.run_store.upsert_thread(
            user_id=user_id,
            thread_id=duplicate_thread_id,
            title=duplicate_title,
            chat_model=str(source_thread.get("chat_model", "") or self.config.chat_model),
            temperature=self._record_temperature(source_thread, fallback_on_missing=self.config.chat_temperature),
            last_mode=str(source_thread.get("last_mode", "chat") or "chat"),
            last_prompt=str(source_thread.get("last_prompt", "") or ""),
        )

    def branch_thread(self, *, user_id: str, thread_id: str, after_message_count: int) -> dict[str, Any]:
        if not user_id.strip():
            raise RuntimeError("User id is required.")
        if not thread_id.strip():
            raise RuntimeError("Thread id is required.")
        self._ensure_user_unlocked(user_id)
        source_thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        if not source_thread:
            raise RuntimeError(f"Thread not found: {thread_id}")

        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        history_messages = list(snapshot.values.get("messages", []))
        branch_count = max(0, min(int(after_message_count or 0), len(history_messages)))
        branch_messages = history_messages[:branch_count]
        branch_thread_id = f"atlas-{datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S')}-{uuid4().hex[:4]}"
        branch_title = _branch_thread_title(source_thread.get("title") or thread_id)
        branch_session_id = scoped_thread_id(user_id, branch_thread_id)

        if branch_messages:
            self.app.graph.update_state(
                {"configurable": {"thread_id": branch_session_id}},
                {
                    "messages": branch_messages,
                    "thread_summary": "",
                    "compacted_message_count": 0,
                    "detected_context_window": 0,
                    "timeline_events": [],
                },
                as_node="persist",
            )

        return self.run_store.upsert_thread(
            user_id=user_id,
            thread_id=branch_thread_id,
            title=branch_title,
            chat_model=str(source_thread.get("chat_model", "") or self.config.chat_model),
            temperature=self._record_temperature(source_thread, fallback_on_missing=self.config.chat_temperature),
            last_mode="chat",
            last_prompt=_latest_user_text({"messages": branch_messages}) if branch_messages else "",
        )

    def get_thread_history(self, *, user_id: str | None, thread_id: str) -> list[dict[str, Any]]:
        if user_id:
            self._ensure_user_unlocked(user_id)
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        history: list[dict[str, Any]] = []
        timeline_events = _sorted_thread_timeline_events(
            _persistent_thread_timeline_events(snapshot.values.get("timeline_events", []))
        )
        pending_events = list(timeline_events)
        for index, message in enumerate(snapshot.values.get("messages", []), start=1):
            role = "system"
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            content, attachments = _message_content_to_history_parts(message.content)
            history.append({"role": role, "content": content, "attachments": attachments})
            while pending_events and int(pending_events[0].get("after_message_count", 0) or 0) == index:
                history.append(_timeline_event_to_history_item(pending_events.pop(0)))
        while pending_events:
            history.append(_timeline_event_to_history_item(pending_events.pop(0)))
        return history

    def search_threads(
        self,
        *,
        user_id: str,
        query: str,
        current_thread_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        if not user_id.strip():
            raise RuntimeError("User id is required.")
        self._ensure_user_unlocked(user_id)

        normalized_query = _normalize_search_query(query)
        if len(normalized_query) < 2:
            return {
                "query": query.strip(),
                "current_thread_id": current_thread_id or "",
                "current_thread_results": [],
                "other_thread_results": [],
            }

        thread_items = self.list_threads(user_id=user_id)
        current_results: list[dict[str, Any]] = []
        other_results: list[dict[str, Any]] = []

        for thread in thread_items:
            thread_id = str(thread.get("thread_id", "") or "").strip()
            if not thread_id:
                continue
            matches = self._search_thread_matches(
                user_id=user_id,
                thread=thread,
                normalized_query=normalized_query,
            )
            if thread_id == (current_thread_id or ""):
                current_results.extend(matches)
            else:
                other_results.extend(matches)

        return {
            "query": query.strip(),
            "current_thread_id": current_thread_id or "",
            "current_thread_results": _sort_search_results(current_results, current_thread=True)[: max(1, limit)],
            "other_thread_results": _sort_search_results(other_results, current_thread=False)[: max(1, limit * 2)],
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        artifact = self._get_accessible_run(run_id)
        user_id = str(artifact.get("user_id", "") or "").strip() or None
        thread_id = str(artifact.get("thread_id", "") or "").strip()
        if not thread_id:
            return artifact
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        artifact["thread_summary"] = str(snapshot.values.get("thread_summary", "") or "")
        artifact["compacted_message_count"] = int(snapshot.values.get("compacted_message_count", 0) or 0)
        artifact["detected_context_window"] = int(snapshot.values.get("detected_context_window", 0) or 0)
        return artifact

    def _search_thread_matches(
        self,
        *,
        user_id: str,
        thread: dict[str, Any],
        normalized_query: str,
    ) -> list[dict[str, Any]]:
        thread_id = str(thread.get("thread_id", "") or "").strip()
        title = str(thread.get("title", "") or thread_id).strip() or thread_id
        last_prompt = str(thread.get("last_prompt", "") or "").strip()
        updated_at = str(thread.get("updated_at", "") or "")
        chat_model = str(thread.get("chat_model", "") or "")

        results: list[dict[str, Any]] = []
        title_match = normalized_query in title.casefold()
        prompt_match = bool(last_prompt) and normalized_query in last_prompt.casefold()
        if title_match or prompt_match:
            results.append(
                {
                    "thread_id": thread_id,
                    "thread_title": title,
                    "chat_model": chat_model,
                    "updated_at": updated_at,
                    "match_type": "thread",
                    "role": None,
                    "history_index": None,
                    "snippet": _build_thread_search_snippet(title=title, last_prompt=last_prompt, normalized_query=normalized_query),
                }
            )

        history = self.get_thread_history(user_id=user_id, thread_id=thread_id)
        for history_index, item in enumerate(history):
            role = str(item.get("role", "") or "")
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content", "") or "").strip()
            if not content or normalized_query not in content.casefold():
                continue
            results.append(
                {
                    "thread_id": thread_id,
                    "thread_title": title,
                    "chat_model": chat_model,
                    "updated_at": updated_at,
                    "match_type": "message",
                    "role": role,
                    "history_index": history_index,
                    "snippet": _build_search_snippet(content, normalized_query),
                }
            )
        return results

    def subscribe(self, run_id: str) -> queue.Queue[RunEvent]:
        return self.run_hub.subscribe(run_id)

    def unsubscribe(self, run_id: str, subscriber: queue.Queue[RunEvent]) -> None:
        self.run_hub.unsubscribe(run_id, subscriber)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self._ensure_worker_started()
        artifact = self._get_accessible_run(run_id)

        with self._control_lock:
            queued_index = next(
                (index for index, job in enumerate(self._pending_runs) if job.run_id == run_id),
                None,
            )
            active_match = self._active_run_id == run_id

            if queued_index is not None and not active_match:
                self._pending_runs.pop(queued_index)
                self._cancelled_runs.discard(run_id)
                queued_cancelled = True
            elif artifact.get("status") in {"queued", "running", "cancelling"} or active_match:
                self._cancelled_runs.add(run_id)
                queued_cancelled = False
            else:
                return {
                    "status": artifact.get("status", "unknown"),
                    "run_id": run_id,
                    "detail": "Run is not active.",
                }

        if queued_cancelled:
            error_message = "Run stopped by user."
            self.run_store.fail_run(run_id, error=error_message)
            self._emit_stage(run_id, "stopping")
            self._emit_event(run_id, "run_failed", {"error": error_message})
            return {"status": "cancelling", "run_id": run_id}

        self.run_store.mark_run_cancelling(run_id)
        if active_match:
            self.app.llm_provider.abort_active_requests()
        self._emit_stage(run_id, "stopping")
        return {"status": "cancelling", "run_id": run_id}

    def start_chat(
        self,
        *,
        prompt: str,
        user_id: str,
        thread_id: str,
        chat_model: str | None = None,
        temperature: float | None = None,
        thread_title: str | None = None,
        cross_chat_memory: bool = True,
        auto_compact_long_chats: bool = True,
        images: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        self._ensure_user_unlocked(user_id)
        return self._start_run(
            mode="chat",
            prompt=prompt,
            user_id=user_id,
            thread_id=thread_id,
            chat_model=chat_model,
            temperature=temperature,
            thread_title=thread_title,
            cross_chat_memory=cross_chat_memory,
            auto_compact_long_chats=auto_compact_long_chats,
            images=images or [],
        )

    def start_manual_compact(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        self._ensure_user_unlocked(user_id)
        thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        if not list(snapshot.values.get("messages", [])) and (not thread or not thread.get("last_run_id")):
            raise RuntimeError("This thread does not have enough history to compact yet.")
        return self._start_run(
            mode="compact",
            prompt="",
            user_id=user_id,
            thread_id=thread_id,
            chat_model=None,
            temperature=None,
            thread_title=str(thread.get("title", "") or thread_id),
            cross_chat_memory=True,
            auto_compact_long_chats=True,
            images=[],
        )

    def list_memories(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self._ensure_user_unlocked(user_id)
        return [item.__dict__ for item in self.app.list_memories(user_id=user_id, limit=limit)]

    def reset_thread(self, *, thread_id: str, user_id: str | None = None) -> dict[str, Any]:
        if user_id:
            self._ensure_user_unlocked(user_id)
        runtime_thread_ids = {thread_id}
        if user_id:
            runtime_thread_ids.add(scoped_thread_id(user_id, thread_id))
        with closing(open_application_sqlite(self.config.langgraph_checkpoint_db, data_dir=self.config.data_dir)) as conn:
            for runtime_thread_id in runtime_thread_ids:
                conn.execute("DELETE FROM writes WHERE thread_id = ?", (runtime_thread_id,))
                conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (runtime_thread_id,))
            conn.commit()
        self.run_store.delete_thread(user_id=user_id, thread_id=thread_id)
        return {"status": "ok", "thread_id": thread_id}

    def reset_user(self, *, user_id: str, confirmation_user_id: str) -> dict[str, Any]:
        if confirmation_user_id != user_id:
            raise RuntimeError("User confirmation did not match the requested user id.")
        self._ensure_user_unlocked(user_id)
        thread_ids = {item["thread_id"] for item in self.run_store.list_threads(user_id=user_id)}
        try:
            self.app.memory_service.delete_all(user_id=user_id)
        except Exception:
            pass
        for thread_id in thread_ids:
            self.reset_thread(thread_id=thread_id, user_id=user_id)
        self.run_store.delete_user(user_id)
        self._unlocked_users.discard(user_id)
        return {"status": "ok", "user_id": user_id}

    def _sanitize_user_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        user_id = str(item.get("user_id", "") or "").strip()
        protection = str(item.get("protection", "passwordless") or "passwordless")
        is_user_key_unlocked = getattr(self.run_store, "is_user_key_unlocked", None)
        unlocked = True
        if callable(is_user_key_unlocked):
            unlocked = bool(is_user_key_unlocked(user_id))
        elif protection == PASSWORD_PROTECTED:
            unlocked = user_id in self._unlocked_users
        locked = protection == PASSWORD_PROTECTED and not unlocked
        return {
            "user_id": user_id,
            "updated_at": item.get("updated_at", ""),
            "protection": protection,
            "locked": locked,
        }

    def _ensure_user_unlocked(self, user_id: str) -> None:
        self._ensure_runtime_state()
        resolved = user_id.strip()
        if not resolved:
            raise RuntimeError("User id is required.")
        user = self._lookup_user_record(resolved)
        if not user:
            raise RuntimeError(f"User not found: {resolved}")
        if user.get("protection") == PASSWORD_PROTECTED and resolved not in self._unlocked_users:
            raise RuntimeError("Unlock this user before continuing.")

    def _get_accessible_run(self, run_id: str) -> dict[str, Any]:
        artifact = self.run_store.get_run(run_id)
        user_id = str(artifact.get("user_id", "") or "").strip()
        if user_id:
            self._ensure_user_unlocked(user_id)
        return artifact

    def _lookup_user_record(self, user_id: str) -> dict[str, Any] | None:
        get_user = getattr(self.run_store, "get_user", None)
        has_lookup = False
        if callable(get_user):
            has_lookup = True
            user = get_user(user_id)
            if user:
                return user
        list_users = getattr(self.run_store, "list_users", None)
        if callable(list_users):
            has_lookup = True
            for item in list_users():
                if str(item.get("user_id", "") or "").strip() == user_id:
                    return dict(item)
        if user_id and not has_lookup:
            return {"user_id": user_id, "protection": "passwordless", "updated_at": ""}
        return None

    def reset_all(self, *, confirmation: str) -> dict[str, Any]:
        if confirmation != "RESET ATLAS":
            raise RuntimeError("Reset confirmation did not match `RESET ATLAS`.")
        with closing(open_application_sqlite(self.config.langgraph_checkpoint_db, data_dir=self.config.data_dir)) as conn:
            conn.execute("DELETE FROM writes")
            conn.execute("DELETE FROM checkpoints")
            conn.commit()
        try:
            self.app.memory_service.reset()
        except Exception:
            pass
        runs_dir = self.config.data_dir / "runs"
        if runs_dir.exists():
            shutil.rmtree(runs_dir, ignore_errors=True)
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.run_store.reset_all()
        return {"status": "ok"}

    def _start_run(
        self,
        *,
        mode: str,
        prompt: str,
        user_id: str,
        thread_id: str,
        chat_model: str | None,
        temperature: float | None,
        thread_title: str | None,
        cross_chat_memory: bool,
        auto_compact_long_chats: bool,
        images: list[dict[str, str]],
    ) -> dict[str, Any]:
        self._ensure_worker_started()
        history_after_message_count = self._thread_history_after_message_count(
            mode=mode,
            user_id=user_id,
            thread_id=thread_id,
        )

        resolved_chat_model = self._resolve_thread_model(
            user_id=user_id,
            thread_id=thread_id,
            requested_chat_model=chat_model,
        )
        if mode == "compact":
            resolved_temperature = 0.0
        else:
            resolved_temperature = self._resolve_thread_temperature(
                user_id=user_id,
                thread_id=thread_id,
                requested_temperature=temperature,
            )
        resolved_thread_title = self._resolve_thread_title(
            user_id=user_id,
            thread_id=thread_id,
            prompt=prompt,
            requested_thread_title=thread_title,
        )

        artifact = self.run_store.create_run(
            mode=mode,
            user_id=user_id,
            thread_id=thread_id,
            chat_model=resolved_chat_model,
            temperature=resolved_temperature,
            prompt=prompt,
            thread_title=resolved_thread_title,
            status="queued",
            touch_thread=mode == "chat",
            history_after_message_count=history_after_message_count,
        )
        queue_position = 0
        with self._control_lock:
            self._cancelled_runs.discard(artifact["run_id"])
            queue_position = len(self._pending_runs) + (1 if self._active_run_id else 0)
            self._pending_runs.append(
                _QueuedRunJob(
                    mode=mode,
                    run_id=artifact["run_id"],
                    prompt=prompt,
                    user_id=user_id,
                    thread_id=thread_id,
                    chat_model=resolved_chat_model,
                    temperature=resolved_temperature,
                    cross_chat_memory=cross_chat_memory,
                    auto_compact_long_chats=auto_compact_long_chats,
                    images=images,
                )
            )
        if queue_position > 0:
            self._emit_event(
                artifact["run_id"],
                "run_queued",
                {
                    "mode": mode,
                    "thread_id": thread_id,
                    "queue_position": queue_position,
                },
            )
        self._emit_stage(artifact["run_id"], "queued")
        self._worker_wakeup.set()
        return {
            "run_id": artifact["run_id"],
            "status": artifact["status"],
            "mode": mode,
            "chat_model": resolved_chat_model,
            "temperature": resolved_temperature,
        }

    def _thread_history_after_message_count(self, *, mode: str, user_id: str, thread_id: str) -> int:
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        message_count = len(list(snapshot.values.get("messages", [])))
        if mode == "chat":
            return message_count + 1
        return message_count

    def _execute_run(
        self,
        *,
        run_id: str,
        prompt: str,
        user_id: str,
        thread_id: str,
        chat_model: str,
        temperature: float | None,
        cross_chat_memory: bool,
        auto_compact_long_chats: bool,
        images: list[dict[str, str]],
    ) -> None:
        session_id = scoped_thread_id(user_id, thread_id)
        config = {"configurable": {"thread_id": session_id}}
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        prior_messages = list(snapshot.values.get("messages", []))
        validated_images = _validated_images(images)
        if validated_images and not self._model_supports_images(chat_model):
            raise RuntimeError(f"Model '{chat_model}' does not appear to support image input.")
        effective_context_window = self.app.llm_provider.effective_context_window(chat_model)
        new_user_message = HumanMessage(content=_build_user_message_content(prompt, validated_images))
        state: dict[str, Any] = dict(snapshot.values)
        state["messages"] = prior_messages + [new_user_message]
        state.setdefault("thread_summary", "")
        state.setdefault("compacted_message_count", 0)
        state["timeline_events"] = _persistent_thread_timeline_events(snapshot.values.get("timeline_events", []))
        state["detected_context_window"] = effective_context_window
        runtime = SimpleNamespace(
            context=GraphContext(
                user_id=user_id,
                thread_id=thread_id,
                session_id=session_id,
                chat_model=chat_model,
                chat_temperature=temperature,
                cross_chat_memory=cross_chat_memory,
                auto_compact_long_chats=auto_compact_long_chats,
                effective_context_window=effective_context_window,
            )
        )
        try:
            self._raise_if_cancelled(run_id)
            self._emit_event(
                run_id,
                "run_started",
                {
                    "mode": "chat",
                    "thread_id": thread_id,
                    "chat_model": chat_model,
                    "temperature": temperature,
                },
            )

            self._emit_stage(run_id, "memory_retrieval")
            self._run_graph_node(run_id=run_id, node_name="retrieve_memories", state=state, runtime=runtime)
            self._emit_trace(
                run_id,
                stage="memory retrieval",
                rationale="Retrieved semantically related long-term memory for the current prompt.",
                inputs={"query": prompt},
                outputs={"count": len(state.get("retrieved_memories", [])), "items": state.get("retrieved_memories", [])[:5]},
            )

            self._raise_if_cancelled(run_id)
            prior_compacted_count = int(state.get("compacted_message_count", 0) or 0)
            representation_tokens_before = self._count_thread_representation_tokens(
                model=chat_model,
                messages=state.get("messages", []),
                thread_summary=str(state.get("thread_summary", "") or ""),
                compacted_message_count=prior_compacted_count,
            )
            compaction = self._maybe_compact_context(state=state, runtime=runtime)
            if compaction:
                state.update(compaction)
                updated_compacted_count = int(state.get("compacted_message_count", 0) or 0)
                representation_tokens_after = self._count_thread_representation_tokens(
                    model=chat_model,
                    messages=state.get("messages", []),
                    thread_summary=str(state.get("thread_summary", "") or ""),
                    compacted_message_count=updated_compacted_count,
                )
                if (
                    updated_compacted_count > prior_compacted_count
                    and representation_tokens_after < representation_tokens_before
                ):
                    self._persist_compaction_event(
                        run_id=run_id,
                        state=state,
                        prior_compacted_count=prior_compacted_count,
                        representation_tokens_before=representation_tokens_before,
                        representation_tokens_after=representation_tokens_after,
                        after_message_count=len(prior_messages) + 1,
                        reason="auto",
                    )

            self._emit_stage(run_id, "synthesis")
            answer = self._stream_answer(run_id=run_id, state=state, runtime=runtime)
            self._raise_if_cancelled(run_id)
            new_ai_message = AIMessage(content=answer)
            state["messages"] = prior_messages + [new_user_message, new_ai_message]
            state["answer"] = answer
            self._emit_trace(
                run_id,
                stage="synthesis",
                rationale="Synthesized the final answer from the current thread and retrieved memory context.",
                inputs={"memory_items": len(state.get("retrieved_memories", []))},
                outputs={"answer_chars": len(answer)},
            )

            self._emit_stage(run_id, "memory_persistence")
            self._run_graph_node(run_id=run_id, node_name="extract_updates", state=state, runtime=runtime)
            self._run_graph_node(run_id=run_id, node_name="persist", state=state, runtime=runtime)
            self._emit_trace(
                run_id,
                stage="memory persistence",
                rationale="Persisted durable user facts that were suitable for future retrieval.",
                inputs={"candidates": len(state.get("update_candidates", []))},
                outputs={"stored": len(state.get("persisted_memories", []))},
            )

            self.app.graph.update_state(
                config,
                {
                    "messages": [new_user_message, new_ai_message],
                    "answer": answer,
                    "thread_summary": str(state.get("thread_summary", "") or ""),
                    "compacted_message_count": int(state.get("compacted_message_count", 0) or 0),
                    "detected_context_window": int(state.get("detected_context_window", 0) or 0),
                    "timeline_events": list(state.get("timeline_events", [])),
                },
                as_node="persist",
            )

            artifact = self.run_store.complete_run(run_id, answer=state.get("answer", ""))
            self._emit_event(
                run_id,
                "run_completed",
                {
                    "answer": artifact.get("answer", ""),
                },
            )
        except Exception as exc:  # pragma: no cover - integration path
            error_message = "Run stopped by user." if self._is_cancelled(run_id) else str(exc)
            self.run_store.fail_run(run_id, error=error_message)
            self._emit_event(run_id, "run_failed", {"error": error_message})

    def _execute_compact_run(
        self,
        *,
        run_id: str,
        user_id: str,
        thread_id: str,
        chat_model: str,
    ) -> None:
        session_id = scoped_thread_id(user_id, thread_id)
        config = {"configurable": {"thread_id": session_id}}
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        all_messages = list(snapshot.values.get("messages", []))

        effective_context_window = self.app.llm_provider.effective_context_window(chat_model)
        state: dict[str, Any] = dict(snapshot.values)
        state["messages"] = all_messages
        state.setdefault("thread_summary", "")
        state.setdefault("compacted_message_count", 0)
        state["timeline_events"] = _persistent_thread_timeline_events(snapshot.values.get("timeline_events", []))
        state["detected_context_window"] = effective_context_window
        runtime = SimpleNamespace(
            context=GraphContext(
                user_id=user_id,
                thread_id=thread_id,
                session_id=session_id,
                chat_model=chat_model,
                chat_temperature=0.0,
                cross_chat_memory=True,
                auto_compact_long_chats=True,
                effective_context_window=effective_context_window,
            )
        )

        try:
            if not all_messages:
                raise RuntimeError("This thread does not have enough history to compact yet.")
            self._raise_if_cancelled(run_id)
            self._emit_event(
                run_id,
                "run_started",
                {
                    "mode": "compact",
                    "thread_id": thread_id,
                    "chat_model": chat_model,
                    "temperature": 0.0,
                },
            )
            self._emit_stage(run_id, "compaction")

            prior_compacted_count = int(state.get("compacted_message_count", 0) or 0)
            representation_tokens_before = self._count_thread_representation_tokens(
                model=chat_model,
                messages=state.get("messages", []),
                thread_summary=str(state.get("thread_summary", "") or ""),
                compacted_message_count=prior_compacted_count,
            )
            compaction = self._manual_compact_context(state=state, runtime=runtime)
            state.update(compaction)
            updated_compacted_count = int(state.get("compacted_message_count", 0) or 0)
            representation_tokens_after = self._count_thread_representation_tokens(
                model=chat_model,
                messages=state.get("messages", []),
                thread_summary=str(state.get("thread_summary", "") or ""),
                compacted_message_count=updated_compacted_count,
            )
            if updated_compacted_count <= prior_compacted_count:
                raise RuntimeError("This thread does not have enough older context to compact yet.")
            if representation_tokens_after >= representation_tokens_before:
                raise RuntimeError("Manual compact would not reduce the current thread context.")

            self._persist_compaction_event(
                run_id=run_id,
                state=state,
                prior_compacted_count=prior_compacted_count,
                representation_tokens_before=representation_tokens_before,
                representation_tokens_after=representation_tokens_after,
                after_message_count=len(all_messages),
                reason="manual",
            )

            self.app.graph.update_state(
                config,
                {
                    "thread_summary": str(state.get("thread_summary", "") or ""),
                    "compacted_message_count": int(state.get("compacted_message_count", 0) or 0),
                    "detected_context_window": int(state.get("detected_context_window", 0) or 0),
                    "timeline_events": list(state.get("timeline_events", [])),
                },
                as_node="persist",
            )

            artifact = self.run_store.complete_run(run_id, answer="")
            self._emit_event(
                run_id,
                "run_completed",
                {
                    "answer": artifact.get("answer", ""),
                    "result": "compacted",
                },
            )
        except Exception as exc:  # pragma: no cover - integration path
            error_message = "Run stopped by user." if self._is_cancelled(run_id) else str(exc)
            self.run_store.fail_run(run_id, error=error_message)
            self._emit_event(run_id, "run_failed", {"error": error_message})

    def _stream_answer(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
        runtime: SimpleNamespace,
    ) -> str:
        messages = _build_answer_messages(
            state=state,
            runtime_context=runtime.context,
            token_counter=self._message_token_counter(runtime.context.chat_model),
        )

        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        stream_parser = _ThinkingStreamParser()
        answer_repair = MojibakeRepairStream()
        thinking_repair = MojibakeRepairStream()
        for chunk in self.app.llm_provider.chat(
            runtime.context.chat_model,
            temperature=runtime.context.chat_temperature,
        ).stream(messages):
            self._raise_if_cancelled(run_id)
            raw_answer_text, raw_thinking_text = _extract_chunk_stream_parts(chunk, stream_parser)
            thinking_text = thinking_repair.consume(raw_thinking_text)
            if thinking_text:
                thinking_parts.append(thinking_text)
                self._emit_event(run_id, "thinking_token", {"text": thinking_text})
            answer_text = answer_repair.consume(raw_answer_text)
            if answer_text:
                answer_parts.append(answer_text)
                self._emit_event(run_id, "token", {"text": answer_text})
            self._raise_if_cancelled(run_id)
        trailing_answer, trailing_thinking = stream_parser.flush()
        trailing_thinking = thinking_repair.consume(trailing_thinking) + thinking_repair.flush()
        if trailing_thinking:
            thinking_parts.append(trailing_thinking)
            self._emit_event(run_id, "thinking_token", {"text": trailing_thinking})
        trailing_answer = answer_repair.consume(trailing_answer) + answer_repair.flush()
        if trailing_answer:
            answer_parts.append(trailing_answer)
            self._emit_event(run_id, "token", {"text": trailing_answer})
        answer_body = "".join(answer_parts)
        answer = _finalize_answer_text(answer_body)
        suffix = answer[len(answer_body):]
        if suffix:
            self._emit_event(run_id, "token", {"text": suffix})
        return answer

    def _run_graph_node(
        self,
        *,
        run_id: str,
        node_name: str,
        state: dict[str, Any],
        runtime: SimpleNamespace,
    ) -> None:
        allowed_nodes = set(pre_synthesis_node_sequence()) | set(post_synthesis_node_sequence())
        if node_name not in allowed_nodes:
            raise RuntimeError(f"Unsupported graph execution node: {node_name}")
        self._raise_if_cancelled(run_id)
        handler = getattr(self.app.nodes, node_name)
        state.update(handler(state, runtime))
        self._raise_if_cancelled(run_id)

    def _is_cancelled(self, run_id: str) -> bool:
        with self._control_lock:
            return run_id in self._cancelled_runs

    def _raise_if_cancelled(self, run_id: str) -> None:
        if self._is_cancelled(run_id):
            raise RuntimeError("Run stopped by user.")

    def _persist_compaction_event(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
        prior_compacted_count: int,
        representation_tokens_before: int,
        representation_tokens_after: int,
        after_message_count: int,
        reason: str,
    ) -> None:
        updated_compacted_count = int(state.get("compacted_message_count", 0) or 0)
        compaction_event = self._emit_event(
            run_id,
            "context_compacted",
            {
                "compacted_message_count": updated_compacted_count,
                "newly_compacted_message_count": max(0, updated_compacted_count - prior_compacted_count),
                "thread_summary": str(state.get("thread_summary", "") or ""),
                "detected_context_window": int(state.get("detected_context_window", 0) or 0),
                "history_representation_tokens_before_compaction": representation_tokens_before,
                "history_representation_tokens_after_compaction": representation_tokens_after,
                "compaction_reason": reason,
            },
        )
        state["timeline_events"] = list(state.get("timeline_events", [])) + [
            {
                "type": "context_compacted",
                "timestamp": compaction_event["timestamp"],
                "run_id": run_id,
                "after_message_count": after_message_count,
                **compaction_event["payload"],
            }
        ]

    def _maybe_compact_context(self, *, state: dict[str, Any], runtime: SimpleNamespace) -> dict[str, Any]:
        if not getattr(runtime.context, "auto_compact_long_chats", True):
            return {"detected_context_window": int(runtime.context.effective_context_window or 0)}

        effective_context_window = int(runtime.context.effective_context_window or 0)
        if effective_context_window <= 0:
            return {}

        all_messages = list(state.get("messages", []))
        threshold = max(1024, int(effective_context_window * 0.72))
        updated_summary = str(state.get("thread_summary", "") or "")
        compacted_count = max(0, min(int(state.get("compacted_message_count", 0) or 0), len(all_messages)))
        if self._count_messages_tokens(model=runtime.context.chat_model, messages=all_messages[compacted_count:]) <= threshold:
            return {"detected_context_window": effective_context_window}

        recent_window = min(8, max(2, len(all_messages) // 2))
        max_iterations = 3

        while (
            max_iterations > 0
            and self._count_messages_tokens(model=runtime.context.chat_model, messages=all_messages[compacted_count:]) > threshold
        ):
            cutoff = len(all_messages) - recent_window
            if cutoff <= compacted_count:
                break
            batch_messages, consumed = _select_messages_for_compaction(
                all_messages[compacted_count:cutoff],
                max_chars=max(6000, int(effective_context_window * 3)),
            )
            if not batch_messages or consumed <= 0:
                break

            updated_summary = self._summarize_message_batch(
                model=runtime.context.chat_model,
                existing_summary=updated_summary,
                messages=batch_messages,
            )
            compacted_count += consumed
            state["thread_summary"] = updated_summary
            state["compacted_message_count"] = compacted_count
            max_iterations -= 1

        return {
            "thread_summary": updated_summary,
            "compacted_message_count": compacted_count,
            "detected_context_window": effective_context_window,
        }

    def _message_token_counter(self, model: str):
        provider = getattr(self.app, "llm_provider", None)
        counter = getattr(provider, "count_message_tokens", None)
        if not callable(counter):
            return None
        return lambda messages: counter(model, messages)

    def _count_messages_tokens(self, *, model: str, messages: list[Any]) -> int:
        if not messages:
            return 0
        token_counter = self._message_token_counter(model)
        if token_counter is not None:
            try:
                counted = int(token_counter(messages))
                if counted >= 0:
                    return counted
            except Exception:
                pass
        return _estimate_prompt_messages_tokens(messages)

    def _count_thread_representation_tokens(
        self,
        *,
        model: str,
        messages: list[Any],
        thread_summary: str,
        compacted_message_count: int,
    ) -> int:
        clamped_compacted_count = max(0, min(int(compacted_message_count or 0), len(messages)))
        total = self._count_messages_tokens(model=model, messages=messages[clamped_compacted_count:])
        summary = thread_summary.strip()
        if summary:
            total += self._count_messages_tokens(
                model=model,
                messages=[SystemMessage(content=f"Conversation summary from earlier in this thread:\n{summary}")],
            )
        return total

    def _manual_compact_context(self, *, state: dict[str, Any], runtime: SimpleNamespace) -> dict[str, Any]:
        effective_context_window = int(runtime.context.effective_context_window or 0)
        all_messages = list(state.get("messages", []))
        updated_summary = str(state.get("thread_summary", "") or "")
        compacted_count = max(0, min(int(state.get("compacted_message_count", 0) or 0), len(all_messages)))
        remaining_messages = all_messages[compacted_count:]
        if len(remaining_messages) <= 2:
            return {
                "thread_summary": updated_summary,
                "compacted_message_count": compacted_count,
                "detected_context_window": effective_context_window,
            }

        recent_window = min(8, max(2, len(remaining_messages) // 2))
        cutoff = len(all_messages) - recent_window
        if cutoff <= compacted_count:
            return {
                "thread_summary": updated_summary,
                "compacted_message_count": compacted_count,
                "detected_context_window": effective_context_window,
            }

        batch_messages, consumed = _select_messages_for_compaction(
            all_messages[compacted_count:cutoff],
            max_chars=max(6000, int(max(effective_context_window, 1024) * 3)),
        )
        if not batch_messages or consumed <= 0:
            return {
                "thread_summary": updated_summary,
                "compacted_message_count": compacted_count,
                "detected_context_window": effective_context_window,
            }

        updated_summary = self._summarize_message_batch(
            model=runtime.context.chat_model,
            existing_summary=updated_summary,
            messages=batch_messages,
        )
        return {
            "thread_summary": updated_summary,
            "compacted_message_count": compacted_count + consumed,
            "detected_context_window": effective_context_window,
        }

    def _summarize_message_batch(
        self,
        *,
        model: str,
        existing_summary: str,
        messages: list[HumanMessage | AIMessage],
    ) -> str:
        transcript = _render_messages_for_summary(messages)
        if not transcript:
            return existing_summary

        prompt_parts = [
            "Condense the earlier part of this conversation into a compact working summary.",
            "Keep only durable user facts, active goals, constraints, key decisions, code/file references, and unresolved tasks.",
            "Drop filler chat. Use short bullet points. Stay under 220 words.",
        ]
        if existing_summary.strip():
            prompt_parts.append("\nExisting summary:\n" + existing_summary.strip())
        prompt_parts.append("\nNew conversation chunk:\n" + transcript)

        try:
            response = self.app.llm_provider.chat(model, temperature=0.0).invoke(
                [HumanMessage(content="\n".join(prompt_parts))]
            )
            summary = str(response.content).strip()
            return summary or existing_summary
        except Exception:
            fallback = _fallback_summary(existing_summary=existing_summary, transcript=transcript)
            return fallback or existing_summary

    def _resolve_thread_model(
        self,
        *,
        user_id: str,
        thread_id: str,
        requested_chat_model: str | None,
    ) -> str:
        requested = (requested_chat_model or "").strip()
        thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        locked_model = ""
        if thread:
            locked_model = str(thread.get("chat_model", "") or "").strip()
            if not locked_model and thread.get("last_run_id"):
                locked_model = self.config.chat_model

        if locked_model:
            if requested and requested != locked_model:
                raise RuntimeError(
                    f"Thread '{thread_id}' is locked to chat model '{locked_model}'. Start a new chat to use '{requested}'."
                )
            return locked_model
        return requested or self.config.chat_model

    def _resolve_thread_temperature(
        self,
        *,
        user_id: str,
        thread_id: str,
        requested_temperature: float | None,
    ) -> float | None:
        thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        has_history = bool(thread and thread.get("last_run_id"))
        if has_history:
            locked_temperature = self._record_temperature(thread, fallback_on_missing=self.config.chat_temperature)
            if locked_temperature is None:
                if requested_temperature is not None:
                    raise RuntimeError(
                        f"Thread '{thread_id}' is locked to model default temperature. Start a new chat to use '{float(requested_temperature):.1f}'."
                    )
                return None
            if requested_temperature is not None and abs(float(requested_temperature) - locked_temperature) > 1e-9:
                raise RuntimeError(
                    f"Thread '{thread_id}' is locked to temperature '{locked_temperature:.1f}'. Start a new chat to use '{float(requested_temperature):.1f}'."
                )
            return locked_temperature

        if requested_temperature is None:
            return None
        return float(requested_temperature)

    @staticmethod
    def _record_temperature(record: dict[str, Any] | None, *, fallback_on_missing: float | None = None) -> float | None:
        if not record or "temperature" not in record:
            return fallback_on_missing
        raw_value = record.get("temperature")
        if raw_value in (None, ""):
            return None
        return float(raw_value)

    def _resolve_thread_title(
        self,
        *,
        user_id: str,
        thread_id: str,
        prompt: str,
        requested_thread_title: str | None,
    ) -> str:
        requested = (requested_thread_title or "").strip()
        existing_thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        existing_title = str(existing_thread.get("title", "")).strip() if existing_thread else ""

        if existing_title and existing_title not in {"main", thread_id} and not existing_title.startswith("atlas-"):
            return existing_title
        if requested and requested not in {"main", thread_id} and not requested.startswith("atlas-"):
            return requested
        return _suggest_thread_title(prompt) or thread_id

    def _emit_stage(self, run_id: str, stage: str) -> None:
        self._emit_event(run_id, "stage_changed", {"stage": stage})

    def _emit_trace(
        self,
        run_id: str,
        *,
        stage: str,
        rationale: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        item = {
            "stage": stage,
            "rationale": rationale,
            "inputs": inputs,
            "outputs": outputs,
            "artifacts": artifacts or {},
        }
        stored = self.run_store.append_trace_item(run_id, item)
        self._emit_event(run_id, "trace_item", stored)

    def _emit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEvent:
        event = self.run_store.append_event(run_id, event_type, payload)
        self.run_hub.publish(run_id, event)
        return event

    def _list_checkpoint_threads(self) -> list[str]:
        if not self.config.langgraph_checkpoint_db.exists():
            return []
        with closing(open_application_sqlite(self.config.langgraph_checkpoint_db, data_dir=self.config.data_dir)) as conn:
            rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id ASC").fetchall()
        return [str(row[0]) for row in rows if row and row[0]]

    def _get_snapshot(self, *, user_id: str | None, thread_id: str):
        scoped_id = scoped_thread_id(user_id, thread_id) if user_id else thread_id
        scoped_snapshot = self.app.graph.get_state({"configurable": {"thread_id": scoped_id}})
        if scoped_snapshot.values.get("messages"):
            return scoped_snapshot
        if user_id:
            legacy_snapshot = self.app.graph.get_state({"configurable": {"thread_id": thread_id}})
            if legacy_snapshot.values.get("messages"):
                return legacy_snapshot
        return scoped_snapshot

    def _model_supports_images(self, model_name: str) -> bool:
        for item in self._get_model_catalog().models:
            if item.name == model_name:
                return item.supports_images
        return False

    def _get_model_catalog(self, *, ttl_seconds: float = 10.0) -> OllamaCatalogSnapshot:
        cached = self._model_catalog_cache
        now = monotonic()
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]
        catalog = inspect_local_ollama_models(self.config)
        self._model_catalog_cache = (now, catalog)
        return catalog


def _estimate_prompt_messages_tokens(messages: list[Any]) -> int:
    total = 0
    for message in messages:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            total += max(1, len(content) // 4)
            continue
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    total += max(1, len(item) // 4)
                elif isinstance(item, dict):
                    item_type = str(item.get("type", "")).strip().lower()
                    if item_type == "text":
                        total += max(1, len(str(item.get("text", ""))) // 4)
                    elif item_type == "image_url":
                        total += 256
            total += 8
            continue
        total += max(1, len(str(content)) // 4)
    return total


def _estimate_history_tokens(messages: list[Any]) -> int:
    return _estimate_prompt_messages_tokens(messages)


def _estimate_thread_representation_tokens(
    *,
    messages: list[Any],
    thread_summary: str,
    compacted_message_count: int,
) -> int:
    clamped_compacted_count = max(0, min(int(compacted_message_count or 0), len(messages)))
    total = _estimate_history_tokens(messages[clamped_compacted_count:])
    summary = thread_summary.strip()
    if summary:
        total += _estimate_prompt_messages_tokens(
            [SystemMessage(content=f"Conversation summary from earlier in this thread:\n{summary}")]
        )
    return total


def _select_messages_for_compaction(
    messages: list[HumanMessage | AIMessage],
    *,
    max_chars: int,
) -> tuple[list[HumanMessage | AIMessage], int]:
    selected: list[HumanMessage | AIMessage] = []
    consumed = 0
    used_chars = 0
    for message in messages:
        rendered = _message_text_for_summary(message)
        if not rendered:
            consumed += 1
            continue
        if selected and used_chars + len(rendered) > max_chars:
            break
        selected.append(message)
        consumed += 1
        used_chars += len(rendered)
    return selected, consumed


def _render_messages_for_summary(messages: list[HumanMessage | AIMessage]) -> str:
    rendered: list[str] = []
    for message in messages:
        text = _message_text_for_summary(message)
        if not text:
            continue
        role = "User" if isinstance(message, HumanMessage) else "Assistant"
        rendered.append(f"{role}: {text}")
    return "\n".join(rendered)


def _message_text_for_summary(message: HumanMessage | AIMessage) -> str:
    text = _latest_user_text({"messages": [message]}) if isinstance(message, HumanMessage) else _chunk_to_text(message)
    cleaned = " ".join(str(text).split()).strip()
    return cleaned


def _fallback_summary(*, existing_summary: str, transcript: str) -> str:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    bullets = [f"- {line[:180]}" for line in lines[:8]]
    merged = "\n".join(part for part in [existing_summary.strip(), "\n".join(bullets)] if part)
    return merged.strip()


def _chunk_to_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return str(content) if content else ""


@dataclass
class _ThinkingStreamParser:
    in_think: bool = False
    pending: str = ""
    open_tag: str = "<think>"
    close_tag: str = "</think>"

    def consume(self, text: str) -> tuple[str, str]:
        if not text:
            return "", ""
        data = f"{self.pending}{text}"
        self.pending = ""
        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        index = 0

        while index < len(data):
            marker = self.close_tag if self.in_think else self.open_tag
            match = data.find(marker, index)
            if match == -1:
                safe_end = _safe_stream_boundary(data, marker)
                segment = data[index:safe_end]
                if self.in_think:
                    thinking_parts.append(segment)
                else:
                    answer_parts.append(segment)
                self.pending = data[safe_end:]
                break

            segment = data[index:match]
            if self.in_think:
                thinking_parts.append(segment)
                index = match + len(self.close_tag)
                self.in_think = False
            else:
                answer_parts.append(segment)
                index = match + len(self.open_tag)
                self.in_think = True

        return "".join(answer_parts), "".join(thinking_parts)

    def flush(self) -> tuple[str, str]:
        if not self.pending:
            return "", ""
        remainder = self.pending
        self.pending = ""
        if self.in_think:
            return "", remainder
        return remainder, ""


def _extract_chunk_stream_parts(chunk: Any, parser: _ThinkingStreamParser) -> tuple[str, str]:
    thinking_parts: list[str] = []
    answer_parts: list[str] = []

    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        reasoning_text = str(additional_kwargs.get("reasoning_content") or "")
        if reasoning_text:
            thinking_parts.append(reasoning_text)

    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        answer_text, thinking_text = parser.consume(content)
        answer_parts.append(answer_text)
        thinking_parts.append(thinking_text)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                answer_text, thinking_text = parser.consume(item)
                answer_parts.append(answer_text)
                thinking_parts.append(thinking_text)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).strip().lower()
            if item_type in {"reasoning", "thinking"}:
                thinking_parts.append(str(item.get("reasoning") or item.get("text") or item.get("content") or ""))
                continue
            text = str(item.get("text") or item.get("content") or "")
            answer_text, thinking_text = parser.consume(text)
            answer_parts.append(answer_text)
            thinking_parts.append(thinking_text)
    else:
        answer_text, thinking_text = parser.consume(str(content) if content else "")
        answer_parts.append(answer_text)
        thinking_parts.append(thinking_text)

    return "".join(part for part in answer_parts if part), "".join(part for part in thinking_parts if part)


def _safe_stream_boundary(data: str, marker: str) -> int:
    max_overlap = min(len(marker) - 1, len(data))
    for overlap in range(max_overlap, 0, -1):
        if data.endswith(marker[:overlap]):
            return len(data) - overlap
    return len(data)


def _validated_images(images: list[dict[str, str]]) -> list[dict[str, str]]:
    validated: list[dict[str, str]] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("data_url", "")).strip()
        media_type = str(item.get("media_type", "")).strip() or "image/png"
        name = str(item.get("name", "")).strip() or "image"
        if not data_url.startswith("data:image/"):
            continue
        try:
            encoded = data_url.split(",", 1)[1]
            base64.b64decode(encoded, validate=True)
        except (IndexError, ValueError):
            continue
        validated.append({"name": name, "media_type": media_type, "data_url": data_url})
    return validated


def _build_user_message_content(prompt: str, images: list[dict[str, str]]) -> str | list[dict[str, Any]]:
    text = prompt.strip()
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text or "Describe this image."}]
    for item in images:
        parts.append({"type": "image_url", "image_url": item["data_url"]})
    return parts


def _message_content_to_history_parts(content: Any) -> tuple[str, list[dict[str, str]]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content), []

    text_parts: list[str] = []
    attachments: list[dict[str, str]] = []
    for item in content:
        if isinstance(item, str):
            text_parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text_parts.append(str(item.get("text", "")))
            continue
        if item.get("type") == "image_url":
            raw_value = item.get("image_url")
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("url", "")
            data_url = str(raw_value or "")
            attachments.append(
                {
                    "name": "image",
                    "media_type": _data_url_media_type(data_url),
                    "data_url": data_url,
                }
            )
    return "\n".join(part for part in text_parts if part).strip(), attachments


def _data_url_media_type(value: str) -> str:
    if value.startswith("data:") and ";" in value:
        return value[5 : value.index(";")]
    return "image/png"


def _suggest_thread_title(prompt: str, *, max_words: int = 6, max_chars: int = 56) -> str:
    cleaned = " ".join(prompt.replace("\n", " ").split()).strip(" -:.,")
    if not cleaned:
        return ""
    words = cleaned.split()
    title = " ".join(words[:max_words]).strip()
    if len(title) > max_chars:
        title = title[:max_chars].rstrip(" -:.,")
    return title or cleaned[:max_chars].rstrip(" -:.,")


def _duplicate_thread_title(value: str) -> str:
    base = value.strip() or "New chat"
    if base.lower().endswith(" copy"):
        return base
    return f"{base} copy"


def _branch_thread_title(value: str) -> str:
    base = value.strip() or "New chat"
    if base.lower().endswith(" branch"):
        return base
    return f"{base} branch"


def _temperature_dropdown_values() -> list[float]:
    return [round(step / 10, 1) for step in range(21)]


def _normalize_search_query(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _build_search_snippet(content: str, normalized_query: str, *, radius: int = 88) -> str:
    cleaned = " ".join(content.split()).strip()
    if not cleaned:
        return ""
    haystack = cleaned.casefold()
    index = haystack.find(normalized_query)
    if index < 0:
        return cleaned[: radius * 2].rstrip()
    start = max(0, index - radius)
    end = min(len(cleaned), index + len(normalized_query) + radius)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(cleaned) else ""
    return f"{prefix}{cleaned[start:end].strip()}{suffix}"


def _build_thread_search_snippet(*, title: str, last_prompt: str, normalized_query: str) -> str:
    if normalized_query in title.casefold():
        return title
    if last_prompt:
        return _build_search_snippet(last_prompt, normalized_query)
    return title


def _sort_search_results(items: list[dict[str, Any]], *, current_thread: bool) -> list[dict[str, Any]]:
    if current_thread:
        return sorted(
            items,
            key=lambda item: (
                0 if str(item.get("match_type", "")) == "thread" else 1,
                -(int(item.get("history_index", -1) or -1)),
                str(item.get("thread_title", "") or ""),
            ),
        )
    return sorted(
        items,
        key=lambda item: (
            str(item.get("updated_at", "") or ""),
            1 if str(item.get("match_type", "")) == "thread" else 0,
            int(item.get("history_index", -1) or -1),
            str(item.get("thread_title", "") or ""),
        ),
        reverse=True,
    )


def _persistent_thread_timeline_events(items: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("type", "")).strip() == "context_compacted"
    ]


def _sorted_thread_timeline_events(items: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    filtered = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("type", "")).strip()
    ]
    return sorted(
        filtered,
        key=lambda item: (
            int(item.get("after_message_count", 0) or 0),
            str(item.get("timestamp", "") or ""),
        ),
    )


def _timeline_event_to_history_item(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type", "") or "")
    if item_type == "context_compacted":
        compacted_message_count = int(item.get("compacted_message_count", 0) or 0)
        detected_context_window = int(item.get("detected_context_window", 0) or 0)
        representation_before = int(item.get("history_representation_tokens_before_compaction", 0) or 0)
        representation_after = int(item.get("history_representation_tokens_after_compaction", 0) or 0)
        return {
            "role": "system",
            "kind": "context_compacted",
            "content": "Context compacted",
            "attachments": [],
            "run_id": str(item.get("run_id", "") or ""),
            "timestamp": str(item.get("timestamp", "") or ""),
            "thread_summary": str(item.get("thread_summary", "") or ""),
            "compaction_reason": str(item.get("compaction_reason", "") or ""),
            "compacted_message_count": compacted_message_count,
            "newly_compacted_message_count": int(item.get("newly_compacted_message_count", 0) or 0),
            "detected_context_window": detected_context_window,
            "history_representation_tokens_before_compaction": representation_before,
            "history_representation_tokens_after_compaction": representation_after,
        }

    return {
        "role": "system",
        "kind": item_type,
        "content": "System event",
        "attachments": [],
        "run_id": str(item.get("run_id", "") or ""),
        "timestamp": str(item.get("timestamp", "") or ""),
    }
