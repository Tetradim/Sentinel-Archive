from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sentinel_archive.backtesting.models import AssetClass, MarketPriceBar, OptionAlert, OptionQuote


class ArchiveDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    asset_class: AssetClass
    symbol: str
    bars: list[MarketPriceBar] = Field(default_factory=list)
    option_alerts: list[OptionAlert] = Field(default_factory=list)
    option_quotes: list[OptionQuote] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchiveDatasetRecord(BaseModel):
    dataset_id: str
    created_at: str
    name: str
    asset_class: AssetClass
    symbol: str
    fingerprint: str
    bars: list[MarketPriceBar] = Field(default_factory=list)
    option_alerts: list[OptionAlert] = Field(default_factory=list)
    option_quotes: list[OptionQuote] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchiveDatasetStore:
    def __init__(self, db_path: str | Path = "data/sentinel_archive.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        async with self._connect() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_datasets_created
                    ON archive_datasets(created_at);
                CREATE INDEX IF NOT EXISTS idx_archive_datasets_symbol
                    ON archive_datasets(symbol);
                """
            )
            await conn.commit()
        self._initialized = True

    async def save_dataset(self, record: ArchiveDatasetRecord) -> ArchiveDatasetRecord:
        await self._ensure_initialized()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO archive_datasets
                (dataset_id, created_at, asset_class, symbol, fingerprint, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.dataset_id,
                    record.created_at,
                    record.asset_class,
                    record.symbol,
                    record.fingerprint,
                    record.model_dump_json(),
                ),
            )
            await conn.commit()
        return record

    async def list_datasets(self, *, limit: int = 100, offset: int = 0, asset_class: str | None = None, symbol: str | None = None) -> tuple[list[ArchiveDatasetRecord], int]:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_datasets ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()
        records = [ArchiveDatasetRecord(**json.loads(row["data"])) for row in rows]
        if asset_class:
            records = [record for record in records if record.asset_class == asset_class]
        if symbol:
            normalized_symbol = symbol.upper()
            records = [record for record in records if record.symbol.upper() == normalized_symbol]
        total = len(records)
        return records[int(offset) : int(offset) + int(limit)], total

    async def get_dataset(self, dataset_id: str) -> ArchiveDatasetRecord | None:
        await self._ensure_initialized()
        async with self._connect() as conn:
            async with conn.execute("SELECT data FROM archive_datasets WHERE dataset_id = ?", (dataset_id,)) as cur:
                row = await cur.fetchone()
        return ArchiveDatasetRecord(**json.loads(row["data"])) if row else None

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn


def create_dataset_record(request: ArchiveDatasetCreateRequest) -> ArchiveDatasetRecord:
    payload = request.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ArchiveDatasetRecord(
        dataset_id=f"dataset-{fingerprint[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
        name=request.name,
        asset_class=request.asset_class,
        symbol=request.symbol.upper(),
        fingerprint=fingerprint,
        bars=request.bars,
        option_alerts=request.option_alerts,
        option_quotes=request.option_quotes,
        metadata=request.metadata,
    )


def create_archive_datasets_router(store: ArchiveDatasetStore) -> APIRouter:
    router = APIRouter(prefix="/archive/datasets", tags=["archive-datasets"])

    @router.post("")
    async def create_dataset(request: ArchiveDatasetCreateRequest):
        record = create_dataset_record(request)
        await store.save_dataset(record)
        return record.model_dump(mode="json")

    @router.get("")
    async def list_datasets(limit: int = 100, offset: int = 0, asset_class: str | None = None, symbol: str | None = None):
        records, total = await store.list_datasets(limit=limit, offset=offset, asset_class=asset_class, symbol=symbol)
        return {
            "datasets": [record.model_dump(mode="json") for record in records],
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(records) < total,
        }

    @router.get("/{dataset_id}")
    async def get_dataset(dataset_id: str):
        record = await store.get_dataset(dataset_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
        return record.model_dump(mode="json")

    return router
