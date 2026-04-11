from __future__ import annotations

import base64
import queue
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from .browser.models import Citation
from .config import AppConfig, load_config
from .graph.builder import AgentApplication, build_chat_application
from .graph.builder import post_synthesis_node_sequence, pre_synthesis_node_sequence
from .graph.context import GraphContext
from .graph.nodes import (
    _build_answer_messages,
    _finalize_answer_text,
    _grounded_research_answer,
    _latest_user_text,
)
from .llm import OllamaModelInfo, list_local_ollama_model_info
from .memory.models import MemoryRecord
from .reasoning.models import ReasoningReport
from .reasoning.rules import evaluate_world_state
from .run_contract import RunEvent, RunHub, TERMINAL_EVENT_TYPES
from .run_store import RunStore
from .session import scoped_thread_id
from .text_normalization import MojibakeRepairStream


@dataclass
class AtlasBackendService:
    config: AppConfig
    app: AgentApplication
    run_store: RunStore
    run_hub: RunHub
    _execution_lock: threading.Lock
    _control_lock: threading.Lock = field(default_factory=threading.Lock)
    _active_run_id: str | None = None
    _cancelled_runs: set[str] = field(default_factory=set)
    _model_catalog_cache: tuple[float, list[OllamaModelInfo]] | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(cls, config: AppConfig | None = None) -> "AtlasBackendService":
        resolved = config or load_config()
        return cls(
            config=resolved,
            app=build_chat_application(resolved),
            run_store=RunStore(resolved),
            run_hub=RunHub(),
            _execution_lock=threading.Lock(),
        )

    def close(self) -> None:
        self.app.close()

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "product": "Atlas"}

    def status(self) -> dict[str, Any]:
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
            "active_profile": self.app.profile.name,
            "busy": self._execution_lock.locked(),
        }

    def list_models(self) -> dict[str, Any]:
        catalog = self._get_model_catalog()
        return {
            "default_model": self.config.chat_model,
            "default_temperature": self.config.chat_temperature,
            "temperature_presets": [
                {"label": f"{value:.1f}", "value": value}
                for value in _temperature_dropdown_values()
            ],
            "models": [item.name for item in catalog],
            "model_details": [item.to_dict() for item in catalog],
        }

    def list_users(self) -> list[dict[str, Any]]:
        items = self.run_store.list_users()
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def create_user(self, *, user_id: str) -> dict[str, Any]:
        resolved = user_id.strip()
        if not resolved:
            raise RuntimeError("User id is required.")
        return self.run_store.upsert_user(resolved)

    def add_memory(self, *, user_id: str, text: str) -> dict[str, Any]:
        resolved_user_id = user_id.strip()
        resolved_text = text.strip()
        if not resolved_user_id:
            raise RuntimeError("User id is required.")
        if not resolved_text:
            raise RuntimeError("Memory text is required.")
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
        self.app.memory_service.delete(resolved_memory_id)
        return {"status": "ok", "user_id": resolved_user_id, "memory_id": resolved_memory_id}

    def list_threads(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        items = self.run_store.list_threads(user_id=user_id)
        if user_id:
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
        return self.run_store.rename_thread(user_id=user_id, thread_id=thread_id, title=title)

    def duplicate_thread(self, *, user_id: str, thread_id: str) -> dict[str, Any]:
        if not user_id.strip():
            raise RuntimeError("User id is required.")
        if not thread_id.strip():
            raise RuntimeError("Thread id is required.")
        source_thread = self.run_store.get_thread(user_id=user_id, thread_id=thread_id)
        if not source_thread:
            raise RuntimeError(f"Thread not found: {thread_id}")

        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        history_messages = list(snapshot.values.get("messages", []))
        duplicate_thread_id = f"atlas-{datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S')}-{uuid4().hex[:4]}"
        duplicate_title = _duplicate_thread_title(source_thread.get("title") or thread_id)
        duplicate_session_id = scoped_thread_id(user_id, duplicate_thread_id)

        if history_messages:
            self.app.graph.update_state(
                {"configurable": {"thread_id": duplicate_session_id}},
                {
                    "messages": history_messages,
                    "thread_summary": str(snapshot.values.get("thread_summary", "") or ""),
                    "compacted_message_count": int(snapshot.values.get("compacted_message_count", 0) or 0),
                    "detected_context_window": int(snapshot.values.get("detected_context_window", 0) or 0),
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

    def get_thread_history(self, *, user_id: str | None, thread_id: str) -> list[dict[str, Any]]:
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        history: list[dict[str, Any]] = []
        for message in snapshot.values.get("messages", []):
            role = "system"
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            content, attachments = _message_content_to_history_parts(message.content)
            history.append({"role": role, "content": content, "attachments": attachments})
        return history

    def get_run(self, run_id: str) -> dict[str, Any]:
        artifact = self.run_store.get_run(run_id)
        user_id = str(artifact.get("user_id", "") or "").strip() or None
        thread_id = str(artifact.get("thread_id", "") or "").strip()
        if not thread_id:
            return artifact
        snapshot = self._get_snapshot(user_id=user_id, thread_id=thread_id)
        artifact["thread_summary"] = str(snapshot.values.get("thread_summary", "") or "")
        artifact["compacted_message_count"] = int(snapshot.values.get("compacted_message_count", 0) or 0)
        artifact["detected_context_window"] = int(snapshot.values.get("detected_context_window", 0) or 0)
        return artifact

    def subscribe(self, run_id: str) -> queue.Queue[RunEvent]:
        return self.run_hub.subscribe(run_id)

    def unsubscribe(self, run_id: str, subscriber: queue.Queue[RunEvent]) -> None:
        self.run_hub.unsubscribe(run_id, subscriber)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        artifact = self.get_run(run_id)
        if artifact.get("status") != "running":
            return {
                "status": artifact.get("status", "unknown"),
                "run_id": run_id,
                "detail": "Run is not active.",
            }

        with self._control_lock:
            self._cancelled_runs.add(run_id)
            active_match = self._active_run_id == run_id

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
        return self._start_run(
            mode="chat",
            prompt=prompt,
            user_id=user_id,
            thread_id=thread_id,
            chat_model=chat_model,
            temperature=temperature,
            thread_title=thread_title,
            research_mode=False,
            cross_chat_memory=cross_chat_memory,
            auto_compact_long_chats=auto_compact_long_chats,
            images=images or [],
        )

    def start_research(
        self,
        *,
        prompt: str,
        user_id: str,
        thread_id: str,
        chat_model: str | None = None,
        temperature: float | None = None,
        thread_title: str | None = None,
        cross_chat_memory: bool = True,
    ) -> dict[str, Any]:
        return self._start_run(
            mode="research",
            prompt=prompt,
            user_id=user_id,
            thread_id=thread_id,
            chat_model=chat_model,
            temperature=temperature,
            thread_title=thread_title,
            research_mode=True,
            cross_chat_memory=cross_chat_memory,
            auto_compact_long_chats=True,
            images=[],
        )

    def list_memories(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [item.__dict__ for item in self.app.list_memories(user_id=user_id, limit=limit)]

    def world_inspect(self, *, user_id: str, limit: int = 50) -> dict[str, Any]:
        snapshot = self.app.world_inspect(user_id=user_id, limit=limit)
        claims = []
        for item in snapshot.get("claims", []):
            claim_id = item.get("claim_id")
            if not claim_id:
                continue
            claim = self.app.world_store.get_claim(str(claim_id))
            if claim is not None:
                claims.append(claim)
        report = evaluate_world_state(
            claims,
            self.app.world_store.list_recent_events(user_id=user_id, limit=min(limit, 20)),
        )
        snapshot["reasoning_report"] = report.to_dict()
        return snapshot

    def deprecate_claim(self, *, claim_id: str) -> dict[str, Any]:
        claim = self.app.world_store.get_claim(claim_id)
        if not claim:
            raise RuntimeError(f"Claim not found: {claim_id}")
        self.app.world_store.update_claim_status(claim_id, status="deprecated")
        self.app.nodes._delete_claim_memory(claim.user_id, claim_id)
        self.app.world_store.record_event(
            user_id=claim.user_id,
            event_type="claim.deprecated.manual",
            thread_id="atlas-desktop",
            payload={"claim_id": claim_id},
        )
        return {"status": "ok", "claim_id": claim_id}

    def browser_open(self, *, url: str, thread_id: str, user_id: str | None = None) -> dict[str, Any]:
        resolved_thread_id = scoped_thread_id(user_id, thread_id) if user_id else thread_id
        try:
            return self.app.browser_open(url, thread_id=resolved_thread_id)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Browser open failed: {exc}") from exc

    def browser_trace(
        self,
        *,
        thread_id: str | None = None,
        trace_path: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.app.browser_manager is None:
            raise RuntimeError("Browser subsystem is not available in chat-only mode.")
        if trace_path:
            return self.app.browser_replay(trace_path)
        if not thread_id:
            raise RuntimeError("thread_id or trace_path is required")
        resolved_thread_id = scoped_thread_id(user_id, thread_id) if user_id else thread_id
        latest = self.app.browser_manager.latest_trace_path(thread_id=resolved_thread_id)
        if not latest:
            return []
        return self.app.browser_replay(latest)

    def run_benchmark(self, *, suite: str, profile_name: str | None = None) -> dict[str, Any]:
        return self.app.run_benchmark(suite=suite, profile_name=profile_name).to_dict()

    def load_benchmark_report(self, run_id_or_path: str) -> dict[str, Any]:
        return self.app.load_benchmark_report(run_id_or_path).to_dict()

    def propose_improvement(self, *, run_id_or_path: str, profile_name: str | None = None) -> dict[str, Any]:
        return self.app.propose_improvement(run_id_or_path=run_id_or_path, profile_name=profile_name).to_dict()

    def promote_profile(self, *, profile_name: str) -> dict[str, Any]:
        return {"promoted": profile_name, "path": self.app.promote_profile(profile_name=profile_name)}

    def reset_thread(self, *, thread_id: str, user_id: str | None = None) -> dict[str, Any]:
        runtime_thread_ids = {thread_id}
        if user_id:
            runtime_thread_ids.add(scoped_thread_id(user_id, thread_id))
            claim_ids = self.app.world_store.list_claim_ids_for_thread(user_id=user_id, thread_id=thread_id)
            for claim_id in claim_ids:
                self.app.nodes._delete_claim_memory(user_id, claim_id)
            thread_cleanup = self.app.world_store.purge_thread(user_id=user_id, thread_id=thread_id)
        else:
            thread_cleanup = {"claims": 0, "memory_records": 0, "sources": 0, "events": 0}
        with sqlite3.connect(self.config.langgraph_checkpoint_db) as conn:
            for runtime_thread_id in runtime_thread_ids:
                conn.execute("DELETE FROM writes WHERE thread_id = ?", (runtime_thread_id,))
                conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (runtime_thread_id,))
            conn.commit()
        self.run_store.delete_thread(user_id=user_id, thread_id=thread_id)
        for runtime_thread_id in runtime_thread_ids:
            browser_dir = self.config.browser_storage_dir / _safe_name(runtime_thread_id)
            if browser_dir.exists():
                shutil.rmtree(browser_dir, ignore_errors=True)
        return {"status": "ok", "thread_id": thread_id, "deleted_world_state": thread_cleanup}

    def reset_user(self, *, user_id: str, confirmation_user_id: str) -> dict[str, Any]:
        if confirmation_user_id != user_id:
            raise RuntimeError("User confirmation did not match the requested user id.")
        thread_ids = {item["thread_id"] for item in self.run_store.list_threads(user_id=user_id)}
        with sqlite3.connect(self.config.world_db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT thread_id FROM world_events WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            thread_ids.update(row[0] for row in rows if row and row[0])
            for table in ("world_events", "memory_records", "claims", "sources", "entities"):
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            conn.commit()
        try:
            self.app.memory_service.delete_all(user_id=user_id)
        except Exception:
            pass
        for thread_id in thread_ids:
            self.reset_thread(thread_id=thread_id, user_id=user_id)
        self.run_store.delete_user(user_id)
        return {"status": "ok", "user_id": user_id}

    def reset_all(self, *, confirmation: str) -> dict[str, Any]:
        if confirmation != "RESET ATLAS":
            raise RuntimeError("Reset confirmation did not match `RESET ATLAS`.")
        if self.app.browser_manager is not None:
            self.app.browser_manager.close()
        with sqlite3.connect(self.config.langgraph_checkpoint_db) as conn:
            conn.execute("DELETE FROM writes")
            conn.execute("DELETE FROM checkpoints")
            conn.commit()
        with sqlite3.connect(self.config.world_db_path) as conn:
            for table in ("world_events", "memory_records", "claims", "sources", "entities"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        try:
            self.app.memory_service.reset()
        except Exception:
            pass
        for directory in (self.config.browser_storage_dir, self.config.evals_dir, self.config.data_dir / "runs"):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
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
        research_mode: bool,
        cross_chat_memory: bool,
        auto_compact_long_chats: bool,
        images: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not self._execution_lock.acquire(blocking=False):
            raise RuntimeError("Atlas is already running another task.")

        resolved_chat_model = self._resolve_thread_model(
            user_id=user_id,
            thread_id=thread_id,
            requested_chat_model=chat_model,
        )
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
            profile_name=self.app.profile.name,
            thread_title=resolved_thread_title,
        )
        with self._control_lock:
            self._active_run_id = artifact["run_id"]
            self._cancelled_runs.discard(artifact["run_id"])
        worker = threading.Thread(
            target=self._execute_run,
            kwargs={
                "run_id": artifact["run_id"],
                "prompt": prompt,
                "user_id": user_id,
                "thread_id": thread_id,
                "chat_model": resolved_chat_model,
                "temperature": resolved_temperature,
                "research_mode": research_mode,
                "cross_chat_memory": cross_chat_memory,
                "auto_compact_long_chats": auto_compact_long_chats,
                "images": images,
            },
            daemon=True,
        )
        worker.start()
        return {
            "run_id": artifact["run_id"],
            "status": artifact["status"],
            "chat_model": resolved_chat_model,
            "temperature": resolved_temperature,
        }

    def _execute_run(
        self,
        *,
        run_id: str,
        prompt: str,
        user_id: str,
        thread_id: str,
        chat_model: str,
        temperature: float | None,
        research_mode: bool,
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
        state["detected_context_window"] = effective_context_window
        runtime = SimpleNamespace(
            context=GraphContext(
                user_id=user_id,
                thread_id=thread_id,
                session_id=session_id,
                chat_model=chat_model,
                chat_temperature=temperature,
                research_mode=research_mode,
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
                    "mode": "research" if research_mode else "chat",
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

            self._emit_stage(run_id, "world_state_retrieval")
            self._run_graph_node(run_id=run_id, node_name="retrieve_world_state", state=state, runtime=runtime)
            report = ReasoningReport.from_dict(state.get("reasoning_report"))
            self._emit_trace(
                run_id,
                stage="world-state retrieval",
                rationale="Loaded relevant canonical claims and recent events for this user.",
                inputs={"user_id": user_id},
                outputs={
                    "claims": len(state.get("world_claims", [])),
                    "violations": [item.message for item in report.violations],
                },
            )

            if research_mode:
                self._emit_stage(run_id, "browser_planning")
                self._run_graph_node(run_id=run_id, node_name="plan_browser_research", state=state, runtime=runtime)
                self._emit_trace(
                    run_id,
                    stage="browser planning",
                    rationale="Decided whether the current request requires browser-grounded research.",
                    inputs={"research_mode": research_mode},
                    outputs=state.get("browser_plan", {}),
                )

                self._emit_stage(run_id, "browser_actions")
                try:
                    self._run_graph_node(run_id=run_id, node_name="browser_loop", state=state, runtime=runtime)
                except Exception as exc:
                    self._emit_trace(
                        run_id,
                        stage="browser actions",
                        rationale="Browser-grounded research failed before Atlas could verify any sources.",
                        inputs={"research_mode": research_mode},
                        outputs={"error": str(exc)},
                    )
                    raise
                for citation in state.get("citations", []):
                    self._emit_event(run_id, "citation_added", citation)
                self._emit_trace(
                    run_id,
                    stage="browser actions",
                    rationale="Collected browser trace steps and source citations when web context was required.",
                    inputs={"research_mode": research_mode},
                    outputs={
                        "steps": len(state.get("browser_trace", [])),
                        "citations": len(state.get("citations", [])),
                    },
                    artifacts={"citations": state.get("citations", [])},
                )
            else:
                state.setdefault("browser_plan", {"use_browser": False})
                state.setdefault("browser_trace", [])
                state.setdefault("citations", [])

            self._raise_if_cancelled(run_id)
            prior_compacted_count = int(state.get("compacted_message_count", 0) or 0)
            compaction = self._maybe_compact_context(state=state, runtime=runtime)
            if compaction:
                state.update(compaction)
                updated_compacted_count = int(state.get("compacted_message_count", 0) or 0)
                if updated_compacted_count > prior_compacted_count:
                    self._emit_event(
                        run_id,
                        "context_compacted",
                        {
                            "compacted_message_count": updated_compacted_count,
                            "newly_compacted_message_count": updated_compacted_count - prior_compacted_count,
                            "thread_summary": str(state.get("thread_summary", "") or ""),
                            "detected_context_window": int(state.get("detected_context_window", 0) or 0),
                        },
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
                rationale="Synthesized the final answer from memory, world state, and citations.",
                inputs={
                    "memory_items": len(state.get("retrieved_memories", [])),
                    "world_claims": len(state.get("world_claims", [])),
                    "citations": len(state.get("citations", [])),
                },
                outputs={"answer_chars": len(answer)},
            )

            self._run_graph_node(run_id=run_id, node_name="extract_updates", state=state, runtime=runtime)
            if state.get("update_candidates"):
                self._raise_if_cancelled(run_id)
                self._run_graph_node(run_id=run_id, node_name="adjudicate_updates", state=state, runtime=runtime)
                self._run_graph_node(run_id=run_id, node_name="persist", state=state, runtime=runtime)
                if research_mode:
                    decisions = [item.get("decision", {}).get("action", "reject") for item in state.get("adjudicated_updates", [])]
                    self._emit_stage(run_id, "claim_extraction")
                    self._emit_trace(
                        run_id,
                        stage="claim extraction",
                        rationale="Extracted durable candidates suitable for canonical storage.",
                        inputs={"answer_present": bool(answer)},
                        outputs={"candidates": len(state.get("update_candidates", []))},
                    )
                    self._emit_stage(run_id, "claim_adjudication")
                    self._emit_trace(
                        run_id,
                        stage="claim adjudication",
                        rationale="Compared candidates against active claims and selected update actions.",
                        inputs={"candidates": len(state.get("update_candidates", []))},
                        outputs={"actions": decisions},
                    )
                    self._emit_stage(run_id, "persistence")
                    final_report = ReasoningReport.from_dict(state.get("reasoning_report"))
                    self._emit_trace(
                        run_id,
                        stage="persistence",
                        rationale="Persisted accepted updates and refreshed the canonical world view.",
                        inputs={"adjudicated": len(state.get("adjudicated_updates", []))},
                        outputs={
                            "world_claims": len(state.get("world_claims", [])),
                            "violations": [item.message for item in final_report.violations],
                        },
                    )
            self.app.graph.update_state(
                config,
                {
                    "messages": [new_user_message, new_ai_message],
                    "answer": answer,
                    "citations": list(state.get("citations", [])),
                    "reasoning_report": state.get("reasoning_report", {}),
                    "thread_summary": str(state.get("thread_summary", "") or ""),
                    "compacted_message_count": int(state.get("compacted_message_count", 0) or 0),
                    "detected_context_window": int(state.get("detected_context_window", 0) or 0),
                },
                as_node="persist",
            )

            artifact = self.run_store.complete_run(
                run_id,
                answer=state.get("answer", ""),
                citations=list(state.get("citations", [])),
            )
            self._emit_event(
                run_id,
                "run_completed",
                {
                    "answer": artifact.get("answer", ""),
                    "citations": artifact.get("citations", []),
                    "reasoning_report": state.get("reasoning_report", {}),
                },
            )
        except Exception as exc:  # pragma: no cover - integration path
            error_message = "Run stopped by user." if self._is_cancelled(run_id) else str(exc)
            self.run_store.fail_run(run_id, error=error_message)
            self._emit_event(run_id, "run_failed", {"error": error_message})
        finally:
            with self._control_lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None
                self._cancelled_runs.discard(run_id)
            self._execution_lock.release()

    def _stream_answer(
        self,
        *,
        run_id: str,
        state: dict[str, Any],
        runtime: SimpleNamespace,
    ) -> str:
        citations = [Citation.from_dict(item) for item in state.get("citations", [])]
        if runtime.context.research_mode and citations:
            answer = _grounded_research_answer(
                question=_latest_user_text(state),
                citations=citations,
            )
            for chunk in _stream_chunks(answer):
                self._emit_event(run_id, "token", {"text": chunk})
            return answer

        messages = _build_answer_messages(state=state, runtime_context=runtime.context)

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
        answer = _finalize_answer_text(answer_body, state=state)
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
        include_browser = bool(runtime.context.research_mode and self.app.browser_manager is not None)
        allowed_nodes = set(pre_synthesis_node_sequence(include_browser=include_browser)) | set(post_synthesis_node_sequence())
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
        if _estimate_history_tokens(all_messages[compacted_count:]) <= threshold:
            return {"detected_context_window": effective_context_window}

        recent_window = min(8, max(2, len(all_messages) // 2))
        max_iterations = 3

        while max_iterations > 0 and _estimate_history_tokens(all_messages[compacted_count:]) > threshold:
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
        with sqlite3.connect(self.config.langgraph_checkpoint_db) as conn:
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
        for item in self._get_model_catalog():
            if item.name == model_name:
                return item.supports_images
        return False

    def _get_model_catalog(self, *, ttl_seconds: float = 10.0) -> list[OllamaModelInfo]:
        cached = self._model_catalog_cache
        now = monotonic()
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]
        catalog = list_local_ollama_model_info(self.config)
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
    content = getattr(message, "content", "")
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


def _stream_chunks(text: str, *, chunk_size: int = 120) -> list[str]:
    if not text:
        return []
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


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


def _temperature_dropdown_values() -> list[float]:
    return [round(step / 10, 1) for step in range(21)]
