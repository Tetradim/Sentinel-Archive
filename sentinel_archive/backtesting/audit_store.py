from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite


class AuditStore:
    def __init__(self, db_path: str | Path = "data/sentinel_archive.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        async with self._connect() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_derivatives_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    bot_id TEXT,
                    symbol TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_derivatives_created
                    ON archive_derivatives_runs(created_at);
                CREATE INDEX IF NOT EXISTS idx_archive_derivatives_symbol
                    ON archive_derivatives_runs(symbol);
                CREATE INDEX IF NOT EXISTS idx_archive_derivatives_kind
                    ON archive_derivatives_runs(kind);
                """
            )
            await conn.commit()
        self._initialized = True

    async def save(self, *, run_id: str, kind: str, bot_id: str | None, symbol: str, fingerprint: str, payload: dict[str, Any]) -> None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO archive_derivatives_runs
                (run_id, created_at, kind, bot_id, symbol, fingerprint, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    kind,
                    bot_id,
                    symbol.upper(),
                    fingerprint,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
            await conn.commit()

    async def get(self, run_id: str) -> dict[str, Any] | None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_derivatives_runs WHERE run_id = ?", (run_id,)) as cursor:
                row = await cursor.fetchone()
        return json.loads(row["data"]) if row else None

    async def list(self, *, limit: int = 100, kind: str | None = None, bot_id: str | None = None, symbol: str | None = None) -> list[dict[str, Any]]:
        await self._ensure_initialized()
        clauses: list[str] = []
        values: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            values.append(kind)
        if bot_id:
            clauses.append("bot_id = ?")
            values.append(bot_id)
        if symbol:
            clauses.append("symbol = ?")
            values.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1000)))
        async with self._connect() as conn:
            async with conn.execute(
                f"SELECT data FROM archive_derivatives_runs {where} ORDER BY created_at DESC LIMIT ?",
                values,
            ) as cursor:
                rows = await cursor.fetchall()
        return [json.loads(row["data"]) for row in rows]

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn
