import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from atlas_local.security import (
    get_or_create_storage_key,
    open_application_sqlite,
    prepare_encrypted_qdrant_storage,
    prepare_encrypted_sqlite,
    sqlcipher_enabled,
)


class SecurityStorageTests(unittest.TestCase):
    def test_storage_key_is_stable_per_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            first = get_or_create_storage_key(data_dir)
            second = get_or_create_storage_key(data_dir)
            self.assertEqual(first, second)

    def test_application_sqlite_writes_encrypted_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            db_path = data_dir / "secure.sqlite"
            with closing(open_application_sqlite(db_path, data_dir=data_dir)) as conn:
                conn.execute("CREATE TABLE sample (value TEXT)")
                conn.execute("INSERT INTO sample (value) VALUES ('atlas')")
                conn.commit()

            with closing(open_application_sqlite(db_path, data_dir=data_dir)) as conn:
                row = conn.execute("SELECT value FROM sample").fetchone()

            self.assertEqual(row[0], "atlas")
            header = db_path.read_bytes()[:16]
            if sqlcipher_enabled():
                self.assertNotEqual(header, b"SQLite format 3\x00")

    def test_prepare_encrypted_sqlite_removes_plaintext_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            db_path = data_dir / "legacy.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE legacy (value TEXT)")
                conn.commit()

            prepare_encrypted_sqlite(db_path, data_dir=data_dir)

            if sqlcipher_enabled():
                self.assertFalse(db_path.exists())

    def test_prepare_encrypted_qdrant_storage_resets_plaintext_local_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            qdrant_dir = data_dir / "qdrant" / "collection" / "atlas_local_memory"
            qdrant_dir.mkdir(parents=True, exist_ok=True)
            db_path = qdrant_dir / "storage.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE points (id TEXT PRIMARY KEY)")
                conn.commit()

            prepare_encrypted_qdrant_storage(data_dir / "qdrant", data_dir=data_dir)

            if sqlcipher_enabled():
                self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
