from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ..config import AppConfig
from .models import Claim, Entity, Source, WorldEvent


class WorldStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.path = Path(config.world_db_path)
        self._initialize()

    def ensure_entity(self, *, user_id: str, name: str, entity_type: str = "user") -> Entity:
        now = _now()
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE user_id = ? AND entity_type = ? AND name = ?",
                (user_id, entity_type, name),
            ).fetchone()
            if row:
                return _entity_from_row(row)

            entity = Entity(
                entity_id=str(uuid.uuid4()),
                user_id=user_id,
                entity_type=entity_type,
                name=name,
                created_at=now,
            )
            conn.execute(
                """
                INSERT INTO entities (entity_id, user_id, entity_type, name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entity.entity_id, entity.user_id, entity.entity_type, entity.name, entity.created_at),
            )
            return entity

    def add_source(
        self,
        *,
        user_id: str,
        url: str,
        title: str,
        supporting_text: str,
        accessed_at: str | None = None,
        created_in_thread_id: str | None = None,
    ) -> Source:
        source = Source(
            source_id=str(uuid.uuid4()),
            user_id=user_id,
            url=url,
            title=title,
            accessed_at=accessed_at or _now(),
            supporting_text=supporting_text[:500],
            created_in_thread_id=created_in_thread_id,
        )
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO sources (source_id, user_id, url, title, accessed_at, supporting_text, created_in_thread_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.user_id,
                    source.url,
                    source.title,
                    source.accessed_at,
                    source.supporting_text,
                    source.created_in_thread_id,
                ),
            )
        return source

    def add_claim(
        self,
        *,
        user_id: str,
        entity_id: str,
        predicate: str,
        value: str,
        claim_type: str,
        confidence: float,
        source_id: str | None,
        status: str = "active",
        supersedes_claim_id: str | None = None,
        created_in_thread_id: str | None = None,
    ) -> Claim:
        now = _now()
        claim = Claim(
            claim_id=str(uuid.uuid4()),
            user_id=user_id,
            entity_id=entity_id,
            predicate=predicate,
            value=value,
            claim_type=claim_type,
            status=status,
            confidence=confidence,
            source_id=source_id,
            created_at=now,
            updated_at=now,
            supersedes_claim_id=supersedes_claim_id,
            created_in_thread_id=created_in_thread_id,
        )
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    claim_id, user_id, entity_id, predicate, value, claim_type, status,
                    confidence, source_id, created_at, updated_at, supersedes_claim_id, created_in_thread_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.claim_id,
                    claim.user_id,
                    claim.entity_id,
                    claim.predicate,
                    claim.value,
                    claim.claim_type,
                    claim.status,
                    claim.confidence,
                    claim.source_id,
                    claim.created_at,
                    claim.updated_at,
                    claim.supersedes_claim_id,
                    claim.created_in_thread_id,
                ),
            )
        return claim

    def update_claim_status(self, claim_id: str, *, status: str) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                (status, _now(), claim_id),
            )

    def find_active_claims(
        self,
        *,
        user_id: str,
        predicate: str | None = None,
        entity_id: str | None = None,
        value: str | None = None,
    ) -> list[Claim]:
        sql = "SELECT * FROM claims WHERE user_id = ? AND status = 'active'"
        params: list[object] = [user_id]
        if predicate:
            sql += " AND predicate = ?"
            params.append(predicate)
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if value:
            sql += " AND lower(value) = lower(?)"
            params.append(value)
        sql += " ORDER BY updated_at DESC"
        with self._session() as conn:
            return [_claim_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def query_relevant_claims(self, *, user_id: str, query: str, limit: int = 12) -> list[Claim]:
        claims = self.find_active_claims(user_id=user_id)
        if not query.strip():
            return claims[:limit]
        query_terms = {token.lower() for token in query.split() if len(token) > 2}
        scored: list[tuple[int, Claim]] = []
        for claim in claims:
            haystack = f"{claim.predicate} {claim.value} {claim.claim_type}".lower()
            score = sum(1 for term in query_terms if term in haystack)
            scored.append((score, claim))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [claim for _, claim in scored[:limit]]

    def list_recent_events(self, *, user_id: str, limit: int = 20) -> list[WorldEvent]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM world_events WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def record_event(
        self,
        *,
        user_id: str,
        event_type: str,
        thread_id: str,
        payload: dict[str, object],
    ) -> WorldEvent:
        event = WorldEvent(
            event_id=str(uuid.uuid4()),
            user_id=user_id,
            event_type=event_type,
            thread_id=thread_id,
            payload=payload,
            created_at=_now(),
        )
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO world_events (event_id, user_id, event_type, thread_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.event_type,
                    event.thread_id,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )
        return event

    def get_claim(self, claim_id: str) -> Claim | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        return _claim_from_row(row) if row else None

    def get_memory_record(self, *, user_id: str, claim_id: str) -> dict[str, str] | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE user_id = ? AND claim_id = ?",
                (user_id, claim_id),
            ).fetchone()
        if not row:
            return None
        return {
            "memory_record_id": row["memory_record_id"],
            "mem0_id": row["mem0_id"],
            "text": row["text"],
            "status": row["status"],
        }

    def upsert_memory_record(
        self,
        *,
        user_id: str,
        claim_id: str,
        mem0_id: str,
        text: str,
        status: str,
    ) -> None:
        existing = self.get_memory_record(user_id=user_id, claim_id=claim_id)
        with self._session() as conn:
            if existing:
                conn.execute(
                    """
                    UPDATE memory_records
                    SET mem0_id = ?, text = ?, status = ?, updated_at = ?
                    WHERE user_id = ? AND claim_id = ?
                    """,
                    (mem0_id, text, status, _now(), user_id, claim_id),
                )
                return
            conn.execute(
                """
                INSERT INTO memory_records (memory_record_id, user_id, claim_id, mem0_id, text, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), user_id, claim_id, mem0_id, text, status, _now()),
            )

    def inspect_user(self, *, user_id: str, limit: int = 20) -> dict[str, object]:
        with self._session() as conn:
            entities = [_entity_from_row(row).to_dict() for row in conn.execute(
                "SELECT * FROM entities WHERE user_id = ? ORDER BY created_at ASC LIMIT ?",
                (user_id, limit),
            ).fetchall()]
            sources = [_source_from_row(row).to_dict() for row in conn.execute(
                "SELECT * FROM sources WHERE user_id = ? ORDER BY accessed_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()]
            claims = [_claim_from_row(row).to_dict() for row in conn.execute(
                "SELECT * FROM claims WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()]
            events = [_event_from_row(row).to_dict() for row in conn.execute(
                "SELECT * FROM world_events WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()]
        return {
            "entities": entities,
            "sources": sources,
            "claims": claims,
            "events": events,
        }

    def list_claim_ids_for_thread(self, *, user_id: str, thread_id: str) -> list[str]:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT claim_id
                FROM claims
                WHERE user_id = ? AND created_in_thread_id = ?
                ORDER BY created_at ASC
                """,
                (user_id, thread_id),
            ).fetchall()
            claim_ids = [str(row["claim_id"]) for row in rows if row and row["claim_id"]]
            claim_ids.extend(
                claim_id
                for claim_id in self._claim_ids_inferred_from_events(conn, user_id=user_id, thread_id=thread_id)
                if claim_id not in claim_ids
            )
        return claim_ids

    def purge_thread(self, *, user_id: str, thread_id: str) -> dict[str, int]:
        with self._session() as conn:
            direct_rows = conn.execute(
                """
                SELECT claim_id, source_id
                FROM claims
                WHERE user_id = ? AND created_in_thread_id = ?
                """,
                (user_id, thread_id),
            ).fetchall()
            claim_rows = {str(row["claim_id"]): row for row in direct_rows if row["claim_id"]}
            inferred_claim_ids = self._claim_ids_inferred_from_events(conn, user_id=user_id, thread_id=thread_id)
            if inferred_claim_ids:
                placeholders = ", ".join("?" for _ in inferred_claim_ids)
                inferred_rows = conn.execute(
                    f"""
                    SELECT claim_id, source_id
                    FROM claims
                    WHERE user_id = ? AND claim_id IN ({placeholders})
                    """,
                    (user_id, *sorted(inferred_claim_ids)),
                ).fetchall()
                for row in inferred_rows:
                    if row["claim_id"]:
                        claim_rows[str(row["claim_id"])] = row

            claim_ids = sorted(claim_rows)
            source_ids = [str(row["source_id"]) for row in claim_rows.values() if row["source_id"]]

            deleted_memory_records = 0
            deleted_claims = 0
            deleted_sources = 0
            deleted_events = conn.execute(
                "DELETE FROM world_events WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            ).rowcount

            if claim_ids:
                placeholders = ", ".join("?" for _ in claim_ids)
                deleted_memory_records = conn.execute(
                    f"DELETE FROM memory_records WHERE user_id = ? AND claim_id IN ({placeholders})",
                    (user_id, *claim_ids),
                ).rowcount
                deleted_claims = conn.execute(
                    f"DELETE FROM claims WHERE user_id = ? AND claim_id IN ({placeholders})",
                    (user_id, *claim_ids),
                ).rowcount

            if source_ids:
                unique_source_ids = sorted(set(source_ids))
                placeholders = ", ".join("?" for _ in unique_source_ids)
                referenced_rows = conn.execute(
                    f"""
                    SELECT DISTINCT source_id
                    FROM claims
                    WHERE user_id = ? AND source_id IN ({placeholders}) AND source_id IS NOT NULL
                    """,
                    (user_id, *unique_source_ids),
                ).fetchall()
                referenced_source_ids = {str(row["source_id"]) for row in referenced_rows if row["source_id"]}
                deletable_source_ids = [source_id for source_id in unique_source_ids if source_id not in referenced_source_ids]
                if deletable_source_ids:
                    delete_placeholders = ", ".join("?" for _ in deletable_source_ids)
                    deleted_sources = conn.execute(
                        f"""
                        DELETE FROM sources
                        WHERE user_id = ? AND source_id IN ({delete_placeholders})
                        """,
                        (user_id, *deletable_source_ids),
                    ).rowcount

        return {
            "claims": deleted_claims,
            "memory_records": deleted_memory_records,
            "sources": deleted_sources,
            "events": deleted_events,
        }

    def _initialize(self) -> None:
        with self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    supporting_text TEXT NOT NULL,
                    created_in_thread_id TEXT
                );
                CREATE TABLE IF NOT EXISTS claims (
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
                    supersedes_claim_id TEXT,
                    created_in_thread_id TEXT
                );
                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_record_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    mem0_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS world_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "sources", "created_in_thread_id", "TEXT")
            self._ensure_column(conn, "claims", "created_in_thread_id", "TEXT")
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_claims_user_status ON claims (user_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_claims_user_predicate ON claims (user_id, predicate);
                CREATE INDEX IF NOT EXISTS idx_claims_user_thread ON claims (user_id, created_in_thread_id);
                CREATE INDEX IF NOT EXISTS idx_sources_user_thread ON sources (user_id, created_in_thread_id);
                CREATE INDEX IF NOT EXISTS idx_events_user_created ON world_events (user_id, created_at);
                """
            )
            self._backfill_thread_provenance(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _backfill_thread_provenance(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT thread_id, payload_json
            FROM world_events
            WHERE event_type IN ('claim.accept_new', 'claim.revise')
            ORDER BY created_at ASC
            """
        ).fetchall()
        claim_threads: dict[str, str] = {}
        for row in rows:
            thread_id = str(row["thread_id"] or "").strip()
            if not thread_id:
                continue
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            claim_id = str(payload.get("claim_id", "")).strip()
            if claim_id and claim_id not in claim_threads:
                claim_threads[claim_id] = thread_id

        for claim_id, thread_id in claim_threads.items():
            conn.execute(
                """
                UPDATE claims
                SET created_in_thread_id = ?
                WHERE claim_id = ? AND (created_in_thread_id IS NULL OR created_in_thread_id = '')
                """,
                (thread_id, claim_id),
            )

        conn.execute(
            """
            UPDATE sources
            SET created_in_thread_id = (
                SELECT claims.created_in_thread_id
                FROM claims
                WHERE claims.source_id = sources.source_id
                  AND claims.created_in_thread_id IS NOT NULL
                  AND claims.created_in_thread_id <> ''
                ORDER BY claims.created_at ASC
                LIMIT 1
            )
            WHERE created_in_thread_id IS NULL OR created_in_thread_id = ''
            """
        )

    @staticmethod
    def _claim_ids_inferred_from_events(
        conn: sqlite3.Connection,
        *,
        user_id: str,
        thread_id: str,
    ) -> set[str]:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM world_events
            WHERE user_id = ? AND thread_id = ? AND event_type IN ('claim.accept_new', 'claim.revise')
            ORDER BY created_at ASC
            """,
            (user_id, thread_id),
        ).fetchall()
        claim_ids: set[str] = set()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            claim_id = str(payload.get("claim_id", "")).strip()
            if claim_id:
                claim_ids.add(claim_id)
        return claim_ids


def _entity_from_row(row: sqlite3.Row) -> Entity:
    return Entity(
        entity_id=row["entity_id"],
        user_id=row["user_id"],
        entity_type=row["entity_type"],
        name=row["name"],
        created_at=row["created_at"],
    )


def _source_from_row(row: sqlite3.Row) -> Source:
    return Source(
        source_id=row["source_id"],
        user_id=row["user_id"],
        url=row["url"],
        title=row["title"],
        accessed_at=row["accessed_at"],
        supporting_text=row["supporting_text"],
        created_in_thread_id=row["created_in_thread_id"],
    )


def _claim_from_row(row: sqlite3.Row) -> Claim:
    return Claim(
        claim_id=row["claim_id"],
        user_id=row["user_id"],
        entity_id=row["entity_id"],
        predicate=row["predicate"],
        value=row["value"],
        claim_type=row["claim_type"],
        status=row["status"],
        confidence=float(row["confidence"]),
        source_id=row["source_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        supersedes_claim_id=row["supersedes_claim_id"],
        created_in_thread_id=row["created_in_thread_id"],
    )


def _event_from_row(row: sqlite3.Row) -> WorldEvent:
    return WorldEvent(
        event_id=row["event_id"],
        user_id=row["user_id"],
        event_type=row["event_type"],
        thread_id=row["thread_id"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
