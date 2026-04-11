from contextlib import closing
import tempfile
import unittest
from pathlib import Path
import sqlite3

from atlas_local.config import load_config
from atlas_local.world.store import WorldStore


class WorldStoreTests(unittest.TestCase):
    def test_add_and_query_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            store = WorldStore(config)
            entity = store.ensure_entity(user_id="u1", name="user")
            store.add_claim(
                user_id="u1",
                entity_id=entity.entity_id,
                predicate="goal",
                value="build a research agent",
                claim_type="goal",
                confidence=0.9,
                source_id=None,
            )
            claims = store.query_relevant_claims(user_id="u1", query="research agent")
            self.assertEqual(len(claims), 1)
            self.assertEqual(claims[0].predicate, "goal")

    def test_purge_thread_removes_thread_linked_claims_sources_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            store = WorldStore(config)
            entity = store.ensure_entity(user_id="u1", name="user")
            source = store.add_source(
                user_id="u1",
                url="https://example.com",
                title="Example",
                supporting_text="Thread-linked evidence",
                created_in_thread_id="thread-a",
            )
            claim = store.add_claim(
                user_id="u1",
                entity_id=entity.entity_id,
                predicate="goal",
                value="preserve only this thread",
                claim_type="goal",
                confidence=0.9,
                source_id=source.source_id,
                created_in_thread_id="thread-a",
            )
            store.upsert_memory_record(
                user_id="u1",
                claim_id=claim.claim_id,
                mem0_id="mem0-1",
                text="goal: preserve only this thread",
                status="active",
            )
            store.record_event(
                user_id="u1",
                event_type="claim.accept_new",
                thread_id="thread-a",
                payload={"claim_id": claim.claim_id},
            )

            result = store.purge_thread(user_id="u1", thread_id="thread-a")

            self.assertEqual(result["claims"], 1)
            self.assertEqual(result["memory_records"], 1)
            self.assertEqual(result["sources"], 1)
            self.assertEqual(result["events"], 1)
            self.assertEqual(store.query_relevant_claims(user_id="u1", query="preserve"), [])
            self.assertEqual(store.list_recent_events(user_id="u1", limit=10), [])
            self.assertIsNone(store.get_memory_record(user_id="u1", claim_id=claim.claim_id))

    def test_retroactive_thread_backfill_supports_old_claim_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            store = WorldStore(config)
            entity = store.ensure_entity(user_id="u1", name="user")

            source_id = "legacy-source"
            claim_id = "legacy-claim"
            with closing(sqlite3.connect(config.world_db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO sources (source_id, user_id, url, title, accessed_at, supporting_text, created_in_thread_id)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (source_id, "u1", "https://example.com/legacy", "Legacy source", "2026-01-01T00:00:00+00:00", "legacy"),
                )
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, user_id, entity_id, predicate, value, claim_type, status,
                        confidence, source_id, created_at, updated_at, supersedes_claim_id, created_in_thread_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        claim_id,
                        "u1",
                        entity.entity_id,
                        "goal",
                        "legacy cleanup",
                        "goal",
                        "active",
                        0.9,
                        source_id,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                        None,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO memory_records (memory_record_id, user_id, claim_id, mem0_id, text, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("legacy-memory", "u1", claim_id, "mem0-legacy", "goal: legacy cleanup", "active", "2026-01-01T00:00:00+00:00"),
                )
                conn.execute(
                    """
                    INSERT INTO world_events (event_id, user_id, event_type, thread_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-event",
                        "u1",
                        "claim.accept_new",
                        "legacy-thread",
                        '{"claim_id":"legacy-claim"}',
                        "2026-01-01T00:00:01+00:00",
                    ),
                )
                conn.commit()

            migrated = WorldStore(config)
            migrated_claim = migrated.get_claim(claim_id)
            self.assertIsNotNone(migrated_claim)
            self.assertEqual(migrated_claim.created_in_thread_id, "legacy-thread")

            result = migrated.purge_thread(user_id="u1", thread_id="legacy-thread")

            self.assertEqual(result["claims"], 1)
            self.assertEqual(result["memory_records"], 1)
            self.assertEqual(result["sources"], 1)
            self.assertEqual(result["events"], 1)
            self.assertIsNone(migrated.get_claim(claim_id))

    def test_initialize_migrates_legacy_schema_without_thread_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(project_root=Path(tmp), env={})
            with closing(sqlite3.connect(config.world_db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE entities (
                        entity_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE sources (
                        source_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        accessed_at TEXT NOT NULL,
                        supporting_text TEXT NOT NULL
                    );
                    CREATE TABLE claims (
                        claim_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        predicate TEXT NOT NULL,
                        value TEXT NOT NULL,
                        claim_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        source_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        supersedes_claim_id TEXT
                    );
                    CREATE TABLE memory_records (
                        memory_record_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        claim_id TEXT NOT NULL,
                        mem0_id TEXT NOT NULL,
                        text TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE world_events (
                        event_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()

            migrated = WorldStore(config)
            self.assertIsInstance(migrated, WorldStore)

            with closing(sqlite3.connect(config.world_db_path)) as conn:
                sources_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
                }
                claims_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()
                }

            self.assertIn("created_in_thread_id", sources_columns)
            self.assertIn("created_in_thread_id", claims_columns)


if __name__ == "__main__":
    unittest.main()
