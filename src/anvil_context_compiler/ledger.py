from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .hashing import sha256_json, sha256_text
from .models import EvidenceSpan, utc_now
from .token_meter import estimate_tokens

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    token_estimate INTEGER NOT NULL,
    importance REAL NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS compile_events (
    event_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    previous_sha256 TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL DEFAULT '',
    event_sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_source_hash ON spans(source_hash);
CREATE INDEX IF NOT EXISTS idx_spans_last_used ON spans(last_used_at);
"""


class ContextLedger:
    """SQLite-backed reversible context ledger.

    Full evidence text is stored locally and referenced in prompts by span IDs.
    This lets the agent compress aggressively while still rehydrating exact source
    slices when accuracy risk increases.
    """

    def __init__(self, path: str = ".anvil/anvil_ledger.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate_compile_events(conn)
            conn.commit()

    @staticmethod
    def _migrate_compile_events(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(compile_events)").fetchall()}
        for name, ddl in {
            "previous_sha256": "ALTER TABLE compile_events ADD COLUMN previous_sha256 TEXT NOT NULL DEFAULT ''",
            "payload_sha256": "ALTER TABLE compile_events ADD COLUMN payload_sha256 TEXT NOT NULL DEFAULT ''",
            "event_sha256": "ALTER TABLE compile_events ADD COLUMN event_sha256 TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in existing:
                conn.execute(ddl)

    def put_span(
        self,
        *,
        text: str,
        source_uri: str = "inline",
        title: str = "",
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceSpan:
        metadata = metadata or {}
        source_hash = sha256_text(text)
        span_id = "span_" + sha256_text(f"{source_uri}\n{title}\n{source_hash}")[:24]
        now = utc_now()
        span = EvidenceSpan(
            span_id=span_id,
            source_uri=source_uri,
            title=title,
            text=text,
            source_hash=source_hash,
            token_estimate=estimate_tokens(text),
            importance=float(importance),
            metadata=metadata,
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO spans(span_id, source_uri, title, text, source_hash, token_estimate, importance, metadata_json, created_at, last_used_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(span_id) DO UPDATE SET
                    text=excluded.text,
                    token_estimate=excluded.token_estimate,
                    importance=MAX(spans.importance, excluded.importance),
                    metadata_json=excluded.metadata_json,
                    last_used_at=excluded.last_used_at
                """,
                (
                    span.span_id,
                    span.source_uri,
                    span.title,
                    span.text,
                    span.source_hash,
                    span.token_estimate,
                    span.importance,
                    json.dumps(span.metadata, sort_keys=True),
                    span.created_at,
                    now,
                ),
            )
            conn.commit()
        return span

    def get_span(self, span_id: str) -> EvidenceSpan | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM spans WHERE span_id = ?", (span_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE spans SET last_used_at = ? WHERE span_id = ?", (utc_now(), span_id))
            conn.commit()
        return EvidenceSpan(
            span_id=row["span_id"],
            source_uri=row["source_uri"],
            title=row["title"],
            text=row["text"],
            source_hash=row["source_hash"],
            token_estimate=int(row["token_estimate"]),
            importance=float(row["importance"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
        )

    def rehydrate(self, span_ids: list[str], max_tokens: int | None = None) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        used = 0
        for span_id in span_ids:
            span = self.get_span(span_id)
            if not span:
                continue
            if max_tokens is not None and used + span.token_estimate > max_tokens:
                break
            spans.append(span)
            used += span.token_estimate
        return spans

    def list_spans(self, limit: int = 50) -> list[EvidenceSpan]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM spans ORDER BY last_used_at DESC LIMIT ?",
                (max(1, min(1000, int(limit))),),
            ).fetchall()
        return [
            EvidenceSpan(
                span_id=row["span_id"],
                source_uri=row["source_uri"],
                title=row["title"],
                text=row["text"],
                source_hash=row["source_hash"],
                token_estimate=int(row["token_estimate"]),
                importance=float(row["importance"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def put_compile_event(self, event_id: str, request_hash: str, plan_hash: str, metrics: dict[str, Any]) -> str:
        with self._connect() as conn:
            stored_event_id = self._unique_compile_event_id(conn, event_id)
            previous_row = conn.execute(
                "SELECT event_sha256 FROM compile_events WHERE event_sha256 != '' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            previous_sha256 = previous_row["event_sha256"] if previous_row else "GENESIS"
            created_at = utc_now()
            payload = {
                "event_id": stored_event_id,
                "request_hash": request_hash,
                "plan_hash": plan_hash,
                "metrics": metrics,
                "created_at": created_at,
            }
            payload_sha256 = sha256_json(payload)
            event_sha256 = sha256_json({"payload_sha256": payload_sha256, "previous_sha256": previous_sha256})
            conn.execute(
                """
                INSERT INTO compile_events(
                    event_id,
                    request_hash,
                    plan_hash,
                    metrics_json,
                    previous_sha256,
                    payload_sha256,
                    event_sha256,
                    created_at
                )
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    stored_event_id,
                    request_hash,
                    plan_hash,
                    json.dumps(metrics, sort_keys=True),
                    previous_sha256,
                    payload_sha256,
                    event_sha256,
                    created_at,
                ),
            )
            conn.commit()
        return event_sha256

    @staticmethod
    def _unique_compile_event_id(conn: sqlite3.Connection, event_id: str) -> str:
        candidate = event_id
        suffix = 1
        while conn.execute("SELECT 1 FROM compile_events WHERE event_id = ?", (candidate,)).fetchone():
            candidate = f"{event_id}.{suffix}"
            suffix += 1
        return candidate

    def verify_compile_events(self) -> bool:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM compile_events ORDER BY rowid ASC").fetchall()

        expected_previous = "GENESIS"
        for row in rows:
            if not row["previous_sha256"] or not row["payload_sha256"] or not row["event_sha256"]:
                return False
            try:
                metrics = json.loads(row["metrics_json"] or "{}")
            except json.JSONDecodeError:
                return False
            payload = {
                "event_id": row["event_id"],
                "request_hash": row["request_hash"],
                "plan_hash": row["plan_hash"],
                "metrics": metrics,
                "created_at": row["created_at"],
            }
            payload_sha256 = sha256_json(payload)
            event_sha256 = sha256_json({"payload_sha256": payload_sha256, "previous_sha256": expected_previous})
            if row["previous_sha256"] != expected_previous:
                return False
            if row["payload_sha256"] != payload_sha256:
                return False
            if row["event_sha256"] != event_sha256:
                return False
            expected_previous = row["event_sha256"]
        return True
