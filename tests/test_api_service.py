import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from atlas_local.api_service import AtlasBackendService
from atlas_local.graph.builder import execution_node_sequence, post_synthesis_node_sequence, pre_synthesis_node_sequence
from atlas_local.llm import OllamaModelInfo


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

        self.assertEqual(users, [{"user_id": "other_user", "updated_at": "2026-04-11T00:00:00Z"}])


class GraphExecutionSequenceTests(unittest.TestCase):
    def test_sequences_share_browser_and_non_browser_order(self) -> None:
        self.assertEqual(
            pre_synthesis_node_sequence(include_browser=False),
            ("retrieve_memories", "retrieve_world_state"),
        )
        self.assertEqual(
            pre_synthesis_node_sequence(include_browser=True),
            ("retrieve_memories", "retrieve_world_state", "plan_browser_research", "browser_loop"),
        )
        self.assertEqual(
            post_synthesis_node_sequence(),
            ("extract_updates", "adjudicate_updates", "persist"),
        )
        self.assertEqual(
            execution_node_sequence(include_browser=True),
            (
                "retrieve_memories",
                "retrieve_world_state",
                "plan_browser_research",
                "browser_loop",
                "synthesize_answer_with_citations",
                "extract_updates",
                "adjudicate_updates",
                "persist",
            ),
        )


class ModelCatalogCachingTests(unittest.TestCase):
    @patch("atlas_local.api_service.list_local_ollama_model_info")
    @patch("atlas_local.api_service.monotonic")
    def test_model_catalog_is_cached_across_calls(self, monotonic_mock, model_info_mock) -> None:
        monotonic_mock.side_effect = [10.0, 11.0]
        model_info_mock.return_value = [OllamaModelInfo(name="qwen", supports_images=True)]

        service = AtlasBackendService.__new__(AtlasBackendService)
        service.config = SimpleNamespace(chat_model="qwen", chat_temperature=0.2)
        service._model_catalog_cache = None

        payload = AtlasBackendService.list_models(service)
        supports_images = AtlasBackendService._model_supports_images(service, "qwen")

        self.assertEqual(payload["models"], ["qwen"])
        self.assertTrue(supports_images)
        self.assertEqual(model_info_mock.call_count, 1)


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
    def test_reset_user_clears_user_data_and_resets_threads(self) -> None:
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        world_db_path = Path(temp_dir) / "world.sqlite"
        with sqlite3.connect(world_db_path) as conn:
            conn.execute("CREATE TABLE world_events (user_id TEXT NOT NULL, thread_id TEXT)")
            conn.execute("CREATE TABLE memory_records (user_id TEXT NOT NULL)")
            conn.execute("CREATE TABLE claims (user_id TEXT NOT NULL)")
            conn.execute("CREATE TABLE sources (user_id TEXT NOT NULL)")
            conn.execute("CREATE TABLE entities (user_id TEXT NOT NULL)")
            conn.executemany(
                "INSERT INTO world_events (user_id, thread_id) VALUES (?, ?)",
                [("research_user", "main"), ("research_user", "notes"), ("other_user", "other")],
            )
            for table in ("memory_records", "claims", "sources", "entities"):
                conn.executemany(
                    f"INSERT INTO {table} (user_id) VALUES (?)",
                    [("research_user",), ("other_user",)],
                )
            conn.commit()

        service = AtlasBackendService.__new__(AtlasBackendService)
        service.config = SimpleNamespace(world_db_path=world_db_path)
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

        with sqlite3.connect(world_db_path) as conn:
            for table in ("world_events", "memory_records", "claims", "sources", "entities"):
                remaining = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?",
                    ("research_user",),
                ).fetchone()
                self.assertEqual(remaining[0], 0)
            other_user_events = conn.execute(
                "SELECT COUNT(*) FROM world_events WHERE user_id = ?",
                ("other_user",),
            ).fetchone()
            self.assertEqual(other_user_events[0], 1)


class ContextCompactionTests(unittest.TestCase):
    def test_compaction_uses_full_uncompacted_history_budget(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        summarized_batches: list[list[HumanMessage | AIMessage]] = []

        def summarize_message_batch(*, model: str, existing_summary: str, messages: list[HumanMessage | AIMessage]) -> str:
            summarized_batches.append(messages)
            return "summary"

        service._summarize_message_batch = summarize_message_batch
        state = {
            "messages": [
                HumanMessage(content="u" * 1800),
                AIMessage(content="a" * 1800),
                HumanMessage(content="u" * 1800),
                AIMessage(content="a" * 1800),
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

    def test_get_run_includes_compaction_metadata_from_snapshot(self) -> None:
        service = AtlasBackendService.__new__(AtlasBackendService)
        service.run_store = SimpleNamespace(
            get_run=lambda run_id: {
                "run_id": run_id,
                "user_id": "research_user",
                "thread_id": "main",
                "status": "completed",
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


if __name__ == "__main__":
    unittest.main()
