import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas_local.config import load_config
from atlas_local.run_store import RunStore
from atlas_local.run_store import _atomic_write_json


class RunStoreTests(unittest.TestCase):
    def test_atomic_write_retries_after_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.json"
            original_replace = __import__("os").replace
            attempts = {"count": 0}

            def flaky_replace(src, dst):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise PermissionError("simulated windows file lock")
                return original_replace(src, dst)

            with mock.patch("atlas_local.run_store.os.replace", side_effect=flaky_replace):
                _atomic_write_json(path, {"status": "ok"})

            self.assertEqual(path.read_text(encoding="utf-8").strip(), '{\n  "status": "ok"\n}')
            self.assertEqual(attempts["count"], 2)

    def test_create_run_preserves_model_default_temperature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)

            artifact = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="main",
                chat_model="gpt-oss:20b",
                temperature=None,
                prompt="hello",
            )

            self.assertIsNone(artifact["temperature"])
            self.assertIsNone(store.get_run(artifact["run_id"])["temperature"])
            self.assertIsNone(store.get_thread(user_id="research_user", thread_id="main")["temperature"])

    def test_fail_incomplete_runs_marks_queued_and_running_runs_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)

            queued = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="queued",
                chat_model="gpt-oss:20b",
                temperature=0.2,
                prompt="queued",
                status="queued",
            )
            running = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="running",
                chat_model="gpt-oss:20b",
                temperature=0.2,
                prompt="running",
            )
            completed = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="completed",
                chat_model="gpt-oss:20b",
                temperature=0.2,
                prompt="completed",
            )
            store.complete_run(completed["run_id"], answer="done")

            recovered = store.fail_incomplete_runs(error="Atlas backend restarted while this run was active.")

            self.assertCountEqual(recovered, [queued["run_id"], running["run_id"]])
            self.assertEqual(store.get_run(queued["run_id"])["status"], "failed")
            self.assertEqual(store.get_run(running["run_id"])["status"], "failed")
            self.assertEqual(store.get_run(completed["run_id"])["status"], "completed")
            self.assertEqual(store.get_run(queued["run_id"])["events"][-1]["type"], "run_failed")

    def test_non_thread_touching_runs_do_not_overwrite_thread_lock_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(project_root=Path(temp_dir), env={})
            store = RunStore(config)

            chat_run = store.create_run(
                mode="chat",
                user_id="research_user",
                thread_id="main",
                chat_model="gpt-oss:20b",
                temperature=0.7,
                prompt="hello",
            )
            store.create_run(
                mode="compact",
                user_id="research_user",
                thread_id="main",
                chat_model="gpt-oss:20b",
                temperature=0.0,
                prompt="",
                status="queued",
                touch_thread=False,
            )

            thread = store.get_thread(user_id="research_user", thread_id="main")

            self.assertEqual(thread["last_mode"], "chat")
            self.assertEqual(thread["last_run_id"], chat_run["run_id"])
            self.assertEqual(thread["temperature"], 0.7)


if __name__ == "__main__":
    unittest.main()
