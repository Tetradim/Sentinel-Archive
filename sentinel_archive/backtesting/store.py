from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from sentinel_archive.backtesting.models import BacktestRunRecord


class BacktestStore:
    def __init__(self, db_path: str | Path = "data/sentinel_archive.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        async with self._connect() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_backtest_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_backtest_runs_created
                    ON archive_backtest_runs(created_at);
                CREATE INDEX IF NOT EXISTS idx_archive_backtest_runs_symbol
                    ON archive_backtest_runs(symbol);
                """
            )
            await conn.commit()
        self._initialized = True

    async def save_run(self, record: BacktestRunRecord) -> BacktestRunRecord:
        await self._ensure_initialized()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO archive_backtest_runs
                (run_id, created_at, kind, asset_class, symbol, fingerprint, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.created_at,
                    record.kind,
                    record.asset_class,
                    record.symbol,
                    record.fingerprint,
                    record.model_dump_json(),
                ),
            )
            await conn.commit()
        return record

    async def list_runs(self, limit: int = 100) -> list[BacktestRunRecord]:
        records, _total = await self.list_runs_page(limit=limit, offset=0)
        return records

    async def list_runs_page(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        asset_class: str | None = None,
        symbol: str | None = None,
        kind: str | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
        safety_score_min: float | None = None,
        safety_score_max: float | None = None,
    ) -> tuple[list[BacktestRunRecord], int]:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_backtest_runs ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()

        records = [BacktestRunRecord(**json.loads(row["data"])) for row in rows]
        if asset_class:
            records = [record for record in records if record.asset_class == asset_class]
        if symbol:
            normalized_symbol = symbol.upper()
            records = [record for record in records if record.symbol.upper() == normalized_symbol]
        if kind:
            records = [record for record in records if record.kind == kind]
        if created_at_from:
            records = [record for record in records if record.created_at >= created_at_from]
        if created_at_to:
            records = [record for record in records if record.created_at <= created_at_to]
        if safety_score_min is not None:
            records = [record for record in records if record.report.metrics.safety_score >= safety_score_min]
        if safety_score_max is not None:
            records = [record for record in records if record.report.metrics.safety_score <= safety_score_max]

        total = len(records)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return records[start:end], total

    async def get_run(self, run_id: str) -> BacktestRunRecord | None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_backtest_runs WHERE run_id = ?", (run_id,)) as cur:
                row = await cur.fetchone()
        return BacktestRunRecord(**json.loads(row["data"])) if row else None

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn


def record_to_dict(record: BacktestRunRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")
