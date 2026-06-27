from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .hashing import sha256_text
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
            conn.commit()

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

    def put_compile_event(self, event_id: str, request_hash: str, plan_hash: str, metrics: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO compile_events(event_id, request_hash, plan_hash, metrics_json, created_at)
                VALUES(?,?,?,?,?)
                """,
                (event_id, request_hash, plan_hash, json.dumps(metrics, sort_keys=True), utc_now()),
            )
            conn.commit()
