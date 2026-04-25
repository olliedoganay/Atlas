import tempfile
import unittest
from pathlib import Path

from atlas_local.config import load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(project_root=root, env={})
            self.assertEqual(config.chat_model, "")
            self.assertIsNone(config.chat_temperature)
            self.assertEqual(config.embed_model, "nomic-embed-text:latest")
            self.assertEqual(config.embed_dim, 768)
            self.assertTrue(config.qdrant_path.exists())
            self.assertTrue(config.langgraph_checkpoint_db.parent.exists())
            self.assertTrue(config.mem0_history_db.parent.exists())


if __name__ == "__main__":
    unittest.main()
