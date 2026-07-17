from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from sentinel_archive.archive_datasets import (
    ArchiveDatasetCreateRequest,
    ArchiveDatasetStore,
    create_dataset_record,
)
from sentinel_archive.market_data.models import MarketDataFetchRequest
from sentinel_archive.market_data.service import MarketDataService


def create_market_data_router(service: MarketDataService, dataset_store: ArchiveDatasetStore) -> APIRouter:
    router = APIRouter(prefix="/archive/market-data", tags=["archive-market-data"])

    @router.get("/providers")
    async def list_providers():
        return {"providers": [provider.model_dump(mode="json") for provider in service.providers()]}

    @router.post("/fetch")
    async def fetch_market_data(request: MarketDataFetchRequest):
        try:
            result = await asyncio.to_thread(service.fetch, request)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"market data provider failed: {exc}") from exc

        if request.save_dataset:
            dataset = create_dataset_record(
                ArchiveDatasetCreateRequest(
                    name=request.dataset_name or f"{result.provider} {result.symbol} {result.interval}",
                    asset_class=result.asset_class,
                    symbol=result.symbol,
                    bars=result.bars,
                    funding_events=result.funding_events,
                    metadata={
                        **result.metadata,
                        "provider": result.provider,
                        "interval": result.interval,
                        "provider_warnings": result.warnings,
                        "source_fingerprint": result.fingerprint,
                    },
                )
            )
            await dataset_store.save_dataset(dataset)
            result.dataset_id = dataset.dataset_id
        return result.model_dump(mode="json")

    return router
