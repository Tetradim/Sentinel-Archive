from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from sentinel_archive.bot_suite.models import SuitePlan, SuiteRun


class BotSuiteStore:
    def __init__(self, db_path: str | Path = "data/sentinel_archive.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        async with self._connect() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_suite_plans (
                    plan_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_suite_plans_created
                    ON archive_suite_plans(created_at);

                CREATE TABLE IF NOT EXISTS archive_suite_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_suite_runs_created
                    ON archive_suite_runs(created_at);
                """
            )
            await conn.commit()
        self._initialized = True

    async def save_plan(self, plan: SuitePlan) -> SuitePlan:
        await self._ensure_initialized()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO archive_suite_plans
                (plan_id, created_at, fingerprint, data)
                VALUES (?, ?, ?, ?)
                """,
                (plan.plan_id, plan.created_at, plan.fingerprint, plan.model_dump_json()),
            )
            await conn.commit()
        return plan

    async def get_plan(self, plan_id: str) -> SuitePlan | None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_suite_plans WHERE plan_id = ?", (plan_id,)) as cur:
                row = await cur.fetchone()
        return SuitePlan(**json.loads(row["data"])) if row else None

    async def list_plans(self, limit: int = 100) -> list[SuitePlan]:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT data FROM archive_suite_plans ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ) as cur:
                rows = await cur.fetchall()
        return [SuitePlan(**json.loads(row["data"])) for row in rows]

    async def save_run(self, run: SuiteRun) -> SuiteRun:
        await self._ensure_initialized()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO archive_suite_runs
                (run_id, plan_id, created_at, fingerprint, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run.run_id, run.plan_id, run.created_at, run.fingerprint, run.model_dump_json()),
            )
            await conn.commit()
        return run

    async def get_run(self, run_id: str) -> SuiteRun | None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_suite_runs WHERE run_id = ?", (run_id,)) as cur:
                row = await cur.fetchone()
        return SuiteRun(**json.loads(row["data"])) if row else None

    async def list_runs(self, limit: int = 100) -> list[SuiteRun]:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT data FROM archive_suite_runs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ) as cur:
                rows = await cur.fetchall()
        return [SuiteRun(**json.loads(row["data"])) for row in rows]

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn
