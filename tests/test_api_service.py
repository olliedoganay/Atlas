import unittest
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from atlas_local.api_service import AtlasBackendService, _estimate_thread_representation_tokens
from atlas_local.config import load_config
from atlas_local.graph.builder import execution_node_sequence, post_synthesis_node_sequence, pre_synthesis_node_sequence
from atlas_local.llm import OllamaCatalogSnapshot, OllamaModelInfo
from atlas_local.run_contract import RunHub
from atlas_local.run_store import RunStore
from atlas_local.security import application_secret_protection_available, local_secret_storage_label, sqlcipher_enabled


class ApiServiceCreateTests(unittest.TestCase):
    @patch("atlas_local.api_service.RunStore")
    @patch("atlas_local.api_service.build_chat_application")
    def test_create_uses_chat_only_builder(self, build_chat_application, run_store_cls) -> None:
        fake_config = object()
        fake_app = object()
        fake_store = object()
        build_chat_application.return_value = fake_app
        run_store_cls.return_value = fake_store

        service = AtlasBackendService.create(config=fake_config)

        build_chat_application.assert_called_once_with(fake_config)
        run_store_cls.assert_called_once_with(fake_config)
        self.assertIs(service.config, fake_config)
        self.assertIs(service.app, fake_app)
        self.assertIs(service.run_store, fake_store)

    def test_list_users_returns_store_entries_without_synthetic_default_user(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            list_users=lambda: [{"user_id": "other_user", "updated_at": "2026-04-11T00:00:00Z"}]
        )

        users = AtlasBackendService.list_users(service)

        self.assertEqual(
            users,
            [
                {
                    "user_id": "other_user",
                    "updated_at": "2026-04-11T00:00:00Z",
                    "protection": "passwordless",
                    "locked": False,
                }
            ],
        )

    def test_status_reports_current_storage_protection_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(close=lambda: None),
                run_store=RunStore(config),
                run_hub=RunHub(),
            )

            payload = service.status()

            self.assertIn("security", payload)
            self.assertEqual(payload["security"]["profile_key_protection"], local_secret_storage_label())
            self.assertEqual(payload["security"]["run_artifacts_encrypted_at_rest"], application_secret_protection_available())
            self.assertEqual(payload["security"]["run_index_encrypted_at_rest"], application_secret_protection_available())
            self.assertEqual(payload["security"]["sqlite_encrypted_at_rest"], sqlcipher_enabled())
            self.assertEqual(payload["security"]["vector_store"], "local-qdrant")
            self.assertEqual(payload["security"]["vector_store_encrypted_at_rest"], sqlcipher_enabled())


class UserProtectionTests(unittest.TestCase):
    def test_list_users_marks_password_profiles_locked_until_unlocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            store.create_user("protected_user", password="atlas-secret")
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(close=lambda: None),
                run_store=store,
                run_hub=RunHub(),
            )

            users = service.list_users()

            self.assertEqual(users[0]["protection"], "password")
            self.assertTrue(users[0]["locked"])

    def test_unlock_user_requires_matching_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            store.create_user("protected_user", password="atlas-secret")
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(close=lambda: None),
                run_store=store,
                run_hub=RunHub(),
            )

            with self.assertRaisesRegex(RuntimeError, "Password did not match"):
                service.unlock_user(user_id="protected_user", password="wrong-secret")

            unlocked = service.unlock_user(user_id="protected_user", password="atlas-secret")

            self.assertFalse(unlocked["locked"])

    def test_locked_user_cannot_list_threads_until_unlocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            store.create_user("protected_user", password="atlas-secret")
            store.upsert_thread(
                user_id="protected_user",
                thread_id="main",
                title="main",
                chat_model="gpt-oss:20b",
                temperature=0.2,
            )
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(close=lambda: None),
                run_store=store,
                run_hub=RunHub(),
            )

            with self.assertRaisesRegex(RuntimeError, "Unlock this user"):
                service.list_threads(user_id="protected_user")

            service.unlock_user(user_id="protected_user", password="atlas-secret")
            threads = service.list_threads(user_id="protected_user")

            self.assertEqual(threads[0]["thread_id"], "main")


class GraphExecutionSequenceTests(unittest.TestCase):
    def test_sequences_match_chat_only_runtime(self) -> None:
        self.assertEqual(
            pre_synthesis_node_sequence(),
            ("retrieve_memories", "retrieve_web"),
        )
        self.assertEqual(
            post_synthesis_node_sequence(),
            ("extract_updates", "persist"),
        )
        self.assertEqual(
            execution_node_sequence(),
            (
                "retrieve_memories",
                "retrieve_web",
                "synthesize_answer",
                "extract_updates",
                "persist",
            ),
        )


class ModelCatalogCachingTests(unittest.TestCase):
    @patch("atlas_local.api_service.inspect_local_ollama_models")
    @patch("atlas_local.api_service.monotonic")
    def test_model_catalog_is_cached_across_calls(self, monotonic_mock, model_info_mock) -> None:
        monotonic_mock.side_effect = [10.0, 11.0]
        model_info_mock.return_value = OllamaCatalogSnapshot(
            models=(OllamaModelInfo(name="qwen", supports_images=True),),
            ollama_online=True,
            has_local_models=True,
            source="ollama",
        )

        service = AtlasBackendService.__new__(AtlasBackendService)
        service.config = SimpleNamespace(chat_model="qwen", chat_temperature=0.2)
        service._model_catalog_cache = None

        payload = AtlasBackendService.list_models(service)
        supports_images = AtlasBackendService._model_supports_images(service, "qwen")

        self.assertEqual(payload["models"], ["qwen"])
        self.assertTrue(payload["ollama_online"])
        self.assertTrue(payload["has_local_models"])
        self.assertEqual(payload["catalog_source"], "ollama")
        self.assertTrue(supports_images)
        self.assertEqual(model_info_mock.call_count, 1)

    @patch("atlas_local.api_service.inspect_local_ollama_models")
    def test_model_catalog_reports_ollama_offline_without_local_models(self, model_info_mock) -> None:
        model_info_mock.return_value = OllamaCatalogSnapshot()

        service = AtlasBackendService.__new__(AtlasBackendService)
        service.config = SimpleNamespace(chat_model="qwen", chat_temperature=0.2)
        service._model_catalog_cache = None

        payload = AtlasBackendService.list_models(service)

        self.assertFalse(payload["ollama_online"])
        self.assertFalse(payload["has_local_models"])
        self.assertEqual(payload["catalog_source"], "fallback")
        self.assertEqual(payload["models"], [])


class ThreadTemperatureResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AtlasBackendService.__new__(AtlasBackendService)
        self.service.config = SimpleNamespace(chat_model="qwen", chat_temperature=0.2)
        self.service.run_store = SimpleNamespace(get_thread=lambda **_: None)

    def test_new_thread_without_requested_temperature_uses_model_default(self) -> None:
        self.assertIsNone(
            AtlasBackendService._resolve_thread_temperature(
                self.service,
                user_id="research_user",
                thread_id="main",
                requested_temperature=None,
            )
        )

    def test_existing_thread_can_lock_to_model_default(self) -> None:
        self.service.run_store = SimpleNamespace(
            get_thread=lambda **_: {"thread_id": "main", "last_run_id": "run-1", "temperature": None}
        )

        self.assertIsNone(
            AtlasBackendService._resolve_thread_temperature(
                self.service,
                user_id="research_user",
                thread_id="main",
                requested_temperature=None,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "locked to model default temperature"):
            AtlasBackendService._resolve_thread_temperature(
                self.service,
                user_id="research_user",
                thread_id="main",
                requested_temperature=0.6,
            )

    def test_existing_thread_preserves_numeric_temperature(self) -> None:
        self.service.run_store = SimpleNamespace(
            get_thread=lambda **_: {"thread_id": "main", "last_run_id": "run-1", "temperature": 0.6}
        )

        self.assertEqual(
            AtlasBackendService._resolve_thread_temperature(
                self.service,
                user_id="research_user",
                thread_id="main",
                requested_temperature=None,
            ),
            0.6,
        )

    def test_legacy_thread_without_temperature_field_falls_back_to_config_default(self) -> None:
        self.service.run_store = SimpleNamespace(get_thread=lambda **_: {"thread_id": "main", "last_run_id": "run-1"})

        self.assertEqual(
            AtlasBackendService._resolve_thread_temperature(
                self.service,
                user_id="research_user",
                thread_id="main",
                requested_temperature=None,
            ),
            0.2,
        )


class ResetUserTests(unittest.TestCase):
    def test_reset_user_clears_memories_and_resets_threads(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.app = SimpleNamespace(memory_service=SimpleNamespace(delete_all=lambda **_: None))
        service.run_store = SimpleNamespace(
            list_threads=lambda **_: [{"thread_id": "main"}, {"thread_id": "notes"}],
            delete_user=lambda user_id: None,
        )
        reset_thread_calls: list[tuple[str, str | None]] = []
        delete_all_calls: list[str] = []
        deleted_users: list[str] = []

        def delete_all(*, user_id: str) -> None:
            delete_all_calls.append(user_id)

        def delete_user(user_id: str) -> None:
            deleted_users.append(user_id)

        def reset_thread(*, thread_id: str, user_id: str | None = None) -> dict[str, object]:
            reset_thread_calls.append((thread_id, user_id))
            return {"status": "ok"}

        service.app.memory_service = SimpleNamespace(delete_all=delete_all)
        service.run_store = SimpleNamespace(
            list_threads=lambda **_: [{"thread_id": "main"}, {"thread_id": "notes"}],
            delete_user=delete_user,
        )
        service.reset_thread = reset_thread

        result = AtlasBackendService.reset_user(
            service,
            user_id="research_user",
            confirmation_user_id="research_user",
        )

        self.assertEqual(result, {"status": "ok", "user_id": "research_user"})
        self.assertEqual(delete_all_calls, ["research_user"])
        self.assertEqual(deleted_users, ["research_user"])
        self.assertCountEqual(
            reset_thread_calls,
            [("main", "research_user"), ("notes", "research_user")],
        )


class ContextCompactionTests(unittest.TestCase):
    def test_compaction_uses_full_uncompacted_history_budget(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        summarized_batches: list[list[HumanMessage | AIMessage]] = []

        def summarize_message_batch(*, model: str, existing_summary: str, messages: list[HumanMessage | AIMessage]) -> str:
            summarized_batches.append(messages)
            return "summary"

        service.app = SimpleNamespace(
            llm_provider=SimpleNamespace(
                count_message_tokens=lambda _model, messages: len(messages) * 700,
            )
        )
        service._summarize_message_batch = summarize_message_batch
        state = {
            "messages": [
                HumanMessage(content="u1"),
                AIMessage(content="a1"),
                HumanMessage(content="u2"),
                AIMessage(content="a2"),
            ],
            "thread_summary": "",
            "compacted_message_count": 0,
        }
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                auto_compact_long_chats=True,
                effective_context_window=1024,
                chat_model="gemma4:e4b",
            )
        )

        result = AtlasBackendService._maybe_compact_context(service, state=state, runtime=runtime)

        self.assertEqual(result["detected_context_window"], 1024)
        self.assertGreater(result["compacted_message_count"], 0)
        self.assertEqual(result["thread_summary"], "summary")
        self.assertEqual(len(summarized_batches), 1)

        before_tokens = service._count_thread_representation_tokens(
            model="gemma4:e4b",
            messages=state["messages"],
            thread_summary="",
            compacted_message_count=0,
        )
        after_tokens = service._count_thread_representation_tokens(
            model="gemma4:e4b",
            messages=state["messages"],
            thread_summary=result["thread_summary"],
            compacted_message_count=result["compacted_message_count"],
        )
        self.assertLess(after_tokens, before_tokens)

    def test_summarize_message_batch_disables_reasoning(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        captured: dict[str, object] = {}

        class _FakeChat:
            def invoke(self, messages: list[HumanMessage]) -> SimpleNamespace:
                captured["prompt"] = str(messages[0].content)
                return SimpleNamespace(content="summary output")

        def fake_chat(model: str, temperature: float | None = None, reasoning: bool | str | None = None):
            captured["model"] = model
            captured["temperature"] = temperature
            captured["reasoning"] = reasoning
            return _FakeChat()

        service.app = SimpleNamespace(llm_provider=SimpleNamespace(chat=fake_chat))

        summary = AtlasBackendService._summarize_message_batch(
            service,
            model="gpt-oss:20b",
            existing_summary="",
            messages=[HumanMessage(content="u1"), AIMessage(content="a1")],
        )

        self.assertEqual(summary, "summary output")
        self.assertEqual(captured["model"], "gpt-oss:20b")
        self.assertEqual(captured["temperature"], 0.0)
        self.assertIs(captured["reasoning"], False)
        prompt = str(captured["prompt"])
        self.assertIn("preserves exact details", prompt)
        self.assertIn("Canon details", prompt)
        self.assertIn("Do not replace specific details with vague phrases", prompt)

    def test_execute_run_stops_before_synthesis_if_cancelled_during_auto_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(
                    llm_provider=SimpleNamespace(
                        abort_active_requests=lambda: None,
                        effective_context_window=lambda _model: 1024,
                        count_message_tokens=lambda _model, messages: len(messages) * 700,
                    ),
                    graph=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
                    close=lambda: None,
                ),
                run_store=store,
                run_hub=RunHub(),
            )

            service._run_graph_node = lambda **_: None  # type: ignore[method-assign]
            service._stream_answer = lambda **_: (_ for _ in ()).throw(AssertionError("synthesis should not start"))  # type: ignore[method-assign]

            artifact = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="main",
                chat_model="gpt-oss:20b",
                temperature=0.2,
                prompt="continue",
                status="running",
            )
            run_id = artifact["run_id"]

            def summarize_message_batch(*, model: str, existing_summary: str, messages: list[HumanMessage | AIMessage]) -> str:
                service._cancelled_runs.add(run_id)
                return "summary"

            service._summarize_message_batch = summarize_message_batch  # type: ignore[method-assign]
            service._get_snapshot = lambda **_: SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="u1"),
                        AIMessage(content="a1"),
                        HumanMessage(content="u2"),
                        AIMessage(content="a2"),
                    ],
                    "thread_summary": "",
                    "compacted_message_count": 0,
                    "timeline_events": [],
                }
            )

            service._execute_run(
                run_id=run_id,
                prompt="continue",
                user_id="research_user",
                thread_id="main",
                chat_model="gpt-oss:20b",
                temperature=0.2,
                reasoning_mode=None,
                web_search_enabled=False,
                cross_chat_memory=False,
                auto_compact_long_chats=True,
                attachments=[],
            )

            stored = store.get_run(run_id)
            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["error"], "Run stopped by user.")
            stage_events = [event for event in stored["events"] if event["type"] == "stage_changed"]
            self.assertIn("compaction", [event["payload"]["stage"] for event in stage_events])
            self.assertNotIn("synthesis", [event["payload"]["stage"] for event in stage_events])

    def test_get_run_includes_compaction_metadata_from_snapshot(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            get_run=lambda run_id: {
                "run_id": run_id,
                "user_id": "research_user",
                "thread_id": "main",
                "status": "completed",
                "started_at": "2026-04-11T10:00:00+00:00",
                "completed_at": "2026-04-11T10:00:04+00:00",
                "answer": "hello world" * 20,
                "events": [
                    {"type": "token", "timestamp": "2026-04-11T10:00:01+00:00", "payload": {"text": "hello"}},
                    {
                        "type": "context_compacted",
                        "timestamp": "2026-04-11T10:00:02+00:00",
                        "payload": {
                            "history_representation_tokens_before_compaction": 1800,
                            "history_representation_tokens_after_compaction": 900,
                        },
                    },
                ],
            }
        )
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "thread_summary": "summary",
                "compacted_message_count": 4,
                "detected_context_window": 4096,
            }
        )

        artifact = AtlasBackendService.get_run(service, "run-123")

        self.assertEqual(artifact["thread_summary"], "summary")
        self.assertEqual(artifact["compacted_message_count"], 4)
        self.assertEqual(artifact["detected_context_window"], 4096)
        self.assertEqual(artifact["diagnostics"]["first_token_latency_ms"], 1000)
        self.assertEqual(artifact["diagnostics"]["total_duration_ms"], 4000)
        self.assertEqual(artifact["diagnostics"]["compaction_gain_tokens_estimate"], 900)

    def test_thread_history_inserts_context_compaction_marker_at_message_boundary(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(list_runs_for_thread=lambda **_: [])
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "messages": [
                    HumanMessage(content="first question"),
                    AIMessage(content="first answer"),
                    HumanMessage(content="second question"),
                    AIMessage(content="second answer"),
                ],
                "timeline_events": [
                    {
                        "type": "context_compacted",
                        "timestamp": "2026-04-11T00:00:00Z",
                        "run_id": "run-2",
                        "after_message_count": 3,
                        "compacted_message_count": 2,
                        "newly_compacted_message_count": 2,
                        "thread_summary": "- first turn summary",
                        "detected_context_window": 4096,
                        "compaction_reason": "auto",
                        "history_representation_tokens_before_compaction": 1800,
                        "history_representation_tokens_after_compaction": 640,
                    }
                ],
            }
        )

        history = AtlasBackendService.get_thread_history(service, user_id="research_user", thread_id="main")

        self.assertEqual(
            [item["role"] for item in history],
            ["user", "assistant", "user", "system", "assistant"],
        )
        marker = history[3]
        self.assertEqual(marker["kind"], "context_compacted")
        self.assertEqual(marker["run_id"], "run-2")
        self.assertEqual(marker["thread_summary"], "- first turn summary")
        self.assertEqual(marker["compaction_reason"], "auto")
        self.assertEqual(marker["history_representation_tokens_before_compaction"], 1800)
        self.assertEqual(marker["history_representation_tokens_after_compaction"], 640)

    def test_thread_history_ignores_run_lifecycle_events_from_run_artifacts(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            list_runs_for_thread=lambda **_: [
                {
                    "run_id": "run-chat",
                    "mode": "chat",
                    "chat_model": "gemma4:e4b",
                    "temperature": 0.2,
                    "history_after_message_count": 1,
                    "events": [
                        {"type": "run_started", "timestamp": "2026-04-11T00:00:00Z", "payload": {}},
                    ],
                },
                {
                    "run_id": "run-restart",
                    "mode": "compact",
                    "chat_model": "gemma4:e4b",
                    "temperature": 0.0,
                    "history_after_message_count": 2,
                    "events": [
                        {
                            "type": "run_failed",
                            "timestamp": "2026-04-11T00:00:01Z",
                            "payload": {"error": "Atlas backend restarted while this run was active."},
                        }
                    ],
                },
            ]
        )
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "messages": [
                    HumanMessage(content="first question"),
                    AIMessage(content="first answer"),
                ],
                "timeline_events": [],
            }
        )

        history = AtlasBackendService.get_thread_history(service, user_id="research_user", thread_id="main")

        self.assertEqual(
            [(item["role"], item.get("kind")) for item in history],
            [
                ("user", None),
                ("assistant", None),
            ],
        )

    def test_thread_history_ignores_legacy_lifecycle_events_stored_in_snapshot(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(list_runs_for_thread=lambda **_: [])
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "messages": [],
                "timeline_events": [
                    {
                        "type": "run_started",
                        "timestamp": "2026-04-11T00:00:00Z",
                        "run_id": "run-chat",
                        "chat_model": "gemma4:e4b",
                    },
                    {
                        "type": "context_compacted",
                        "timestamp": "2026-04-11T00:00:01Z",
                        "run_id": "run-compact",
                        "after_message_count": 0,
                        "compacted_message_count": 2,
                        "newly_compacted_message_count": 2,
                        "thread_summary": "- summary",
                        "detected_context_window": 4096,
                        "compaction_reason": "auto",
                        "history_representation_tokens_before_compaction": 1800,
                        "history_representation_tokens_after_compaction": 640,
                    },
                ],
            }
        )

        history = AtlasBackendService.get_thread_history(service, user_id="research_user", thread_id="main")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], "context_compacted")
        self.assertEqual(history[0]["run_id"], "run-compact")

    def test_branch_thread_keeps_only_selected_prefix_and_resets_compaction_state(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        graph_updates: list[dict[str, object]] = []
        service.config = SimpleNamespace(chat_model="gemma4:e4b", chat_temperature=0.2)
        service.run_store = SimpleNamespace(
            get_thread=lambda **_: {
                "thread_id": "main",
                "title": "Novel outline",
                "chat_model": "gemma4:e4b",
                "temperature": 0.2,
                "last_mode": "chat",
                "last_prompt": "latest prompt",
            },
            upsert_thread=lambda **kwargs: kwargs,
        )
        service.app = SimpleNamespace(
            graph=SimpleNamespace(update_state=lambda _config, payload, as_node=None: graph_updates.append(payload)),
        )
        service._ensure_user_unlocked = lambda _user_id: None
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "messages": [
                    HumanMessage(content="u1"),
                    AIMessage(content="a1"),
                    HumanMessage(content="u2"),
                    AIMessage(content="a2"),
                ],
                "thread_summary": "- summary",
                "compacted_message_count": 2,
                "timeline_events": [
                    {
                        "type": "context_compacted",
                        "after_message_count": 3,
                    }
                ],
            }
        )

        branched = AtlasBackendService.branch_thread(
            service,
            user_id="research_user",
            thread_id="main",
            after_message_count=2,
        )

        self.assertEqual(branched["title"], "Novel outline branch")
        self.assertEqual(branched["last_prompt"], "u1")
        self.assertTrue(graph_updates)
        self.assertEqual(len(graph_updates[0]["messages"]), 2)
        self.assertEqual(graph_updates[0]["thread_summary"], "")
        self.assertEqual(graph_updates[0]["compacted_message_count"], 0)
        self.assertEqual(graph_updates[0]["timeline_events"], [])


class SearchTests(unittest.TestCase):
    def test_search_threads_returns_current_and_other_thread_matches(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            list_threads=lambda **_: [
                {
                    "user_id": "research_user",
                    "thread_id": "current",
                    "title": "Novel outline",
                    "chat_model": "gemma4:e4b",
                    "updated_at": "2026-04-11T10:00:00Z",
                    "last_prompt": "let's build the world",
                },
                {
                    "user_id": "research_user",
                    "thread_id": "archive",
                    "title": "Atlantis notes",
                    "chat_model": "gpt-oss:20b",
                    "updated_at": "2026-04-10T09:00:00Z",
                    "last_prompt": "summarize the ruins",
                },
            ]
        )
        snapshots = {
            "current": SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="draft the opening scene"),
                        AIMessage(content="The opening scene begins in silence."),
                    ],
                    "timeline_events": [],
                }
            ),
            "archive": SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="what do we know about Atlantis?"),
                        AIMessage(content="Atlantis is described as a lost island civilization."),
                    ],
                    "timeline_events": [],
                }
            ),
        }
        service._get_snapshot = lambda **kwargs: snapshots[kwargs["thread_id"]]

        payload = AtlasBackendService.search_threads(
            service,
            user_id="research_user",
            query="Atlantis",
            current_thread_id="current",
            limit=5,
        )

        self.assertEqual(payload["query"], "Atlantis")
        self.assertEqual(payload["current_thread_results"], [])
        self.assertEqual(payload["other_thread_results"][0]["thread_id"], "archive")
        self.assertEqual(payload["other_thread_results"][0]["match_type"], "thread")
        self.assertEqual(payload["other_thread_results"][1]["history_index"], 1)

    def test_search_threads_returns_message_match_in_current_thread(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            list_threads=lambda **_: [
                {
                    "user_id": "research_user",
                    "thread_id": "main",
                    "title": "Novel outline",
                    "chat_model": "gemma4:e4b",
                    "updated_at": "2026-04-11T10:00:00Z",
                    "last_prompt": "draft the opening",
                },
            ]
        )
        service._get_snapshot = lambda **_: SimpleNamespace(
            values={
                "messages": [
                    HumanMessage(content="draft the opening scene"),
                    AIMessage(content="The opening scene begins in silence."),
                ],
                "timeline_events": [],
            }
        )

        payload = AtlasBackendService.search_threads(
            service,
            user_id="research_user",
            query="opening",
            current_thread_id="main",
            limit=5,
        )

        self.assertEqual(len(payload["current_thread_results"]), 3)
        self.assertEqual(payload["current_thread_results"][0]["match_type"], "thread")
        self.assertEqual(payload["current_thread_results"][1]["history_index"], 1)


class ManualCompactionTests(unittest.TestCase):
    def test_manual_compact_context_summarizes_older_turns(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        summarized_batches: list[list[HumanMessage | AIMessage]] = []

        def summarize_message_batch(*, model: str, existing_summary: str, messages: list[HumanMessage | AIMessage]) -> str:
            summarized_batches.append(messages)
            return "manual summary"

        service._summarize_message_batch = summarize_message_batch
        state = {
            "messages": [
                HumanMessage(content="u1" * 600),
                AIMessage(content="a1" * 600),
                HumanMessage(content="u2" * 600),
                AIMessage(content="a2" * 600),
                HumanMessage(content="u3"),
                AIMessage(content="a3"),
            ],
            "thread_summary": "",
            "compacted_message_count": 0,
        }
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                effective_context_window=4096,
                chat_model="gemma4:e4b",
            )
        )

        result = AtlasBackendService._manual_compact_context(service, state=state, runtime=runtime)

        self.assertEqual(result["thread_summary"], "manual summary")
        self.assertGreater(result["compacted_message_count"], 0)
        self.assertEqual(len(summarized_batches), 1)

        before_tokens = _estimate_thread_representation_tokens(
            messages=state["messages"],
            thread_summary="",
            compacted_message_count=0,
        )
        after_tokens = _estimate_thread_representation_tokens(
            messages=state["messages"],
            thread_summary=result["thread_summary"],
            compacted_message_count=result["compacted_message_count"],
        )
        self.assertLess(after_tokens, before_tokens)

    def test_execute_compact_run_persists_manual_timeline_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            graph_updates: list[dict[str, object]] = []
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(
                    llm_provider=SimpleNamespace(
                        abort_active_requests=lambda: None,
                        effective_context_window=lambda _model: 4096,
                    ),
                    graph=SimpleNamespace(update_state=lambda _config, payload, as_node=None: graph_updates.append(payload)),
                    close=lambda: None,
                ),
                run_store=store,
                run_hub=RunHub(),
            )
            service._summarize_message_batch = lambda **_: "manual summary"  # type: ignore[method-assign]
            service._get_snapshot = lambda **_: SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="u1" * 600),
                        AIMessage(content="a1" * 600),
                        HumanMessage(content="u2" * 600),
                        AIMessage(content="a2" * 600),
                        HumanMessage(content="u3"),
                        AIMessage(content="a3"),
                    ],
                    "thread_summary": "",
                    "compacted_message_count": 0,
                    "timeline_events": [],
                }
            )

            artifact = store.create_run(
                mode="compact",
                user_id="research_user",
                thread_id="main",
                chat_model="gemma4:e4b",
                temperature=0.0,
                prompt="",
                status="running",
            )

            service._execute_compact_run(
                run_id=artifact["run_id"],
                user_id="research_user",
                thread_id="main",
                chat_model="gemma4:e4b",
            )

            stored = store.get_run(artifact["run_id"])
            self.assertEqual(stored["status"], "completed")
            self.assertEqual(stored["events"][-1]["type"], "run_completed")
            context_event = next(event for event in stored["events"] if event["type"] == "context_compacted")
            self.assertEqual(context_event["payload"]["compaction_reason"], "manual")
            self.assertTrue(graph_updates)
            self.assertEqual(graph_updates[-1]["timeline_events"][0]["compaction_reason"], "manual")

    def test_execute_compact_run_fails_when_no_older_context_can_be_folded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)
            service = AtlasBackendService(
                config=config,
                app=SimpleNamespace(
                    llm_provider=SimpleNamespace(
                        abort_active_requests=lambda: None,
                        effective_context_window=lambda _model: 4096,
                    ),
                    graph=SimpleNamespace(update_state=lambda *_args, **_kwargs: None),
                    close=lambda: None,
                ),
                run_store=store,
                run_hub=RunHub(),
            )
            service._get_snapshot = lambda **_: SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="question"),
                        AIMessage(content="answer"),
                    ],
                    "thread_summary": "",
                    "compacted_message_count": 0,
                    "timeline_events": [],
                }
            )

            artifact = store.create_run(
                mode="compact",
                user_id="research_user",
                thread_id="main",
                chat_model="gemma4:e4b",
                temperature=0.0,
                prompt="",
                status="running",
            )

            service._execute_compact_run(
                run_id=artifact["run_id"],
                user_id="research_user",
                thread_id="main",
                chat_model="gemma4:e4b",
            )

            stored = store.get_run(artifact["run_id"])
            self.assertEqual(stored["status"], "failed")
            self.assertIn("does not have enough older context", stored["error"])


class QueuedExecutionTests(unittest.TestCase):
    def _make_service(self, temp_dir: str, abort_calls: list[str]) -> AtlasBackendService:
        config = load_config(project_root=Path(temp_dir), env={})
        service = AtlasBackendService(
            config=config,
            app=SimpleNamespace(
                llm_provider=SimpleNamespace(abort_active_requests=lambda: abort_calls.append("abort")),
                graph=SimpleNamespace(get_state=lambda *_args, **_kwargs: SimpleNamespace(values={"messages": []})),
                close=lambda: None,
            ),
            run_store=RunStore(config),
            run_hub=RunHub(),
        )
        service.run_store.create_user("research_user")
        return service

    def test_runs_execute_serially_through_single_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            abort_calls: list[str] = []
            service = self._make_service(temp_dir, abort_calls)
            started: list[str] = []
            first_started = threading.Event()
            second_started = threading.Event()
            release_first = threading.Event()
            release_second = threading.Event()

            def fake_execute_run(**kwargs) -> None:
                run_id = kwargs["run_id"]
                started.append(run_id)
                if len(started) == 1:
                    first_started.set()
                    self.assertTrue(release_first.wait(2.0))
                else:
                    second_started.set()
                    self.assertTrue(release_second.wait(2.0))
                service.run_store.complete_run(run_id, answer=f"done:{run_id}")
                service._emit_event(run_id, "run_completed", {"answer": f"done:{run_id}"})

            service._execute_run = fake_execute_run  # type: ignore[method-assign]
            try:
                first = service.start_chat(prompt="first", user_id="research_user", thread_id="one")
                second = service.start_chat(prompt="second", user_id="research_user", thread_id="two")

                self.assertEqual(first["status"], "queued")
                self.assertEqual(second["status"], "queued")
                self.assertTrue(first_started.wait(1.0))
                time.sleep(0.05)
                self.assertEqual(started, [first["run_id"]])
                self.assertEqual(service.run_store.get_run(first["run_id"])["status"], "running")
                self.assertEqual(service.run_store.get_run(second["run_id"])["status"], "queued")
                self.assertEqual(service.run_store.get_run(second["run_id"])["events"][0]["type"], "run_queued")
                self.assertTrue(service.status()["busy"])

                release_first.set()
                self.assertTrue(second_started.wait(1.0))
                self.assertEqual(started, [first["run_id"], second["run_id"]])

                release_second.set()
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if service.run_store.get_run(second["run_id"])["status"] == "completed":
                        break
                    time.sleep(0.02)

                self.assertEqual(service.run_store.get_run(first["run_id"])["status"], "completed")
                self.assertEqual(service.run_store.get_run(second["run_id"])["status"], "completed")
                deadline = time.time() + 2.0
                while time.time() < deadline and service.status()["busy"]:
                    time.sleep(0.02)
                self.assertFalse(service.status()["busy"])
                self.assertEqual(abort_calls, [])
            finally:
                service.close()

    def test_cancel_run_removes_queued_job_before_it_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            abort_calls: list[str] = []
            service = self._make_service(temp_dir, abort_calls)
            started: list[str] = []
            first_started = threading.Event()
            second_started = threading.Event()
            release_first = threading.Event()

            def fake_execute_run(**kwargs) -> None:
                run_id = kwargs["run_id"]
                started.append(run_id)
                if len(started) == 1:
                    first_started.set()
                    self.assertTrue(release_first.wait(2.0))
                else:
                    second_started.set()
                service.run_store.complete_run(run_id, answer=f"done:{run_id}")
                service._emit_event(run_id, "run_completed", {"answer": f"done:{run_id}"})

            service._execute_run = fake_execute_run  # type: ignore[method-assign]
            try:
                first = service.start_chat(prompt="first", user_id="research_user", thread_id="one")
                second = service.start_chat(prompt="second", user_id="research_user", thread_id="two")

                self.assertTrue(first_started.wait(1.0))
                response = service.cancel_run(second["run_id"])
                self.assertEqual(response["status"], "cancelling")
                cancelled = service.run_store.get_run(second["run_id"])
                self.assertEqual(cancelled["status"], "failed")
                self.assertEqual(cancelled["error"], "Run stopped by user.")
                self.assertFalse(second_started.wait(0.2))

                release_first.set()
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if service.run_store.get_run(first["run_id"])["status"] == "completed":
                        break
                    time.sleep(0.02)

                self.assertEqual(started, [first["run_id"]])
                self.assertEqual(abort_calls, [])
                self.assertEqual(cancelled["events"][-1]["type"], "run_failed")
            finally:
                service.close()

    def test_cancel_run_marks_running_job_cancelling_and_aborts_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            abort_calls: list[str] = []
            service = self._make_service(temp_dir, abort_calls)
            started = threading.Event()

            def fake_execute_run(**kwargs) -> None:
                run_id = kwargs["run_id"]
                started.set()
                deadline = time.time() + 2.0
                while time.time() < deadline and not service._is_cancelled(run_id):
                    time.sleep(0.01)
                if service._is_cancelled(run_id):
                    service.run_store.fail_run(run_id, error="Run stopped by user.")
                    service._emit_event(run_id, "run_failed", {"error": "Run stopped by user."})
                    return
                service.run_store.complete_run(run_id, answer=f"done:{run_id}")
                service._emit_event(run_id, "run_completed", {"answer": f"done:{run_id}"})

            service._execute_run = fake_execute_run  # type: ignore[method-assign]
            try:
                run = service.start_chat(prompt="first", user_id="research_user", thread_id="one")
                self.assertTrue(started.wait(1.0))
                response = service.cancel_run(run["run_id"])

                self.assertEqual(response["status"], "cancelling")
                self.assertIn(service.run_store.get_run(run["run_id"])["status"], {"cancelling", "failed"})
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if service.run_store.get_run(run["run_id"])["status"] == "failed":
                        break
                    time.sleep(0.02)
                self.assertEqual(service.run_store.get_run(run["run_id"])["status"], "failed")
                self.assertEqual(abort_calls, ["abort"])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
