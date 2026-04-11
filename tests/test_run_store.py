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


if __name__ == "__main__":
    unittest.main()
