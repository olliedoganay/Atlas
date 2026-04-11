import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from qdrant_client.http import models
from qdrant_client.local.persistence import CollectionPersistence

from atlas_local.config import load_config
from atlas_local.memory.mem0_service import Mem0Service, _local_collection_points, _reconcile_legacy_qdrant_collections
from atlas_local.security import open_application_sqlite


class Mem0ServiceCollectionMigrationTests(unittest.TestCase):
    def test_legacy_collection_replaces_empty_current_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            collection_root = config.qdrant_path / "collection"
            legacy_dir = collection_root / "legacy_memory"
            current_dir = collection_root / config.mem0_collection
            self._create_collection(legacy_dir, point_count=3)
            self._create_collection(current_dir, point_count=0)
            self._write_meta(
                config.qdrant_path / "meta.json",
                {
                    "collections": {
                        "legacy_memory": {"vectors": {"size": 768}},
                        config.mem0_collection: {"vectors": {"size": 768}},
                    }
                },
            )

            _reconcile_legacy_qdrant_collections(config)

            self.assertFalse(legacy_dir.exists())
            self.assertTrue(current_dir.exists())
            self.assertEqual(_local_collection_points(current_dir), 3)
            metadata = json.loads((config.qdrant_path / "meta.json").read_text(encoding="utf-8"))
            self.assertNotIn("legacy_memory", metadata.get("collections", {}))
            self.assertIn(config.mem0_collection, metadata.get("collections", {}))

    def test_multiple_populated_legacy_collections_do_not_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            collection_root = config.qdrant_path / "collection"
            legacy_dir = collection_root / "legacy_memory"
            secondary_legacy_dir = collection_root / "legacy_memory_two"
            current_dir = collection_root / config.mem0_collection
            self._create_collection(legacy_dir, point_count=2)
            self._create_collection(secondary_legacy_dir, point_count=1)
            self._create_collection(current_dir, point_count=0)
            self._write_meta(
                config.qdrant_path / "meta.json",
                {
                    "collections": {
                        "legacy_memory": {"vectors": {"size": 768}},
                        "legacy_memory_two": {"vectors": {"size": 768}},
                        config.mem0_collection: {"vectors": {"size": 768}},
                    }
                },
            )

            _reconcile_legacy_qdrant_collections(config)

            self.assertTrue(legacy_dir.exists())
            self.assertTrue(secondary_legacy_dir.exists())
            self.assertEqual(_local_collection_points(current_dir), 0)
            metadata = json.loads((config.qdrant_path / "meta.json").read_text(encoding="utf-8"))
            self.assertIn("legacy_memory", metadata.get("collections", {}))
            self.assertIn("legacy_memory_two", metadata.get("collections", {}))
            self.assertIn(config.mem0_collection, metadata.get("collections", {}))

    def test_constructor_does_not_require_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            with patch("atlas_local.memory.mem0_service.Memory.from_config", side_effect=ConnectionError("offline")) as factory:
                service = Mem0Service(config)

            self.assertIsNone(service._memory)
            factory.assert_not_called()

    def test_memory_access_reports_ollama_unavailability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            service = Mem0Service(config)
            with patch("atlas_local.memory.mem0_service.Memory.from_config", side_effect=ConnectionError("offline")):
                with self.assertRaisesRegex(RuntimeError, "memory service is unavailable"):
                    service.list(user_id="research_user", limit=10)

    def test_constructor_patches_qdrant_local_storage_to_encrypted_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            service = Mem0Service(config)
            collection_dir = config.qdrant_path / "collection" / config.mem0_collection
            persistence = CollectionPersistence(str(collection_dir))
            try:
                persistence.persist(models.PointStruct(id=1, vector=[1.0, 2.0], payload={"source": "test"}))
            finally:
                persistence.close()
                service.close()

            header = (collection_dir / "storage.sqlite").read_bytes()[:16]
            self.assertNotEqual(header, b"SQLite format 3\x00")

    @staticmethod
    def _create_collection(path: Path, *, point_count: int) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with closing(open_application_sqlite(path / "storage.sqlite", data_dir=path.parents[2])) as conn:
            conn.execute("CREATE TABLE points (id TEXT PRIMARY KEY)")
            for index in range(point_count):
                conn.execute("INSERT INTO points (id) VALUES (?)", (str(index),))
            conn.commit()

    @staticmethod
    def _write_meta(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
