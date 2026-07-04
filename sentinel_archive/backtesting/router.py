from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from sentinel_archive.backtesting.exports import report_to_csv, report_to_json
from sentinel_archive.backtesting.models import (
    BacktestRunRequest,
    BacktestStressRequest,
    BacktestSweepRequest,
    BacktestWalkForwardRequest,
)
from sentinel_archive.backtesting.service import create_run_record, run_backtest, run_stress, run_sweep, run_walk_forward
from sentinel_archive.backtesting.store import BacktestStore


def create_backtest_router(store: BacktestStore) -> APIRouter:
    router = APIRouter(prefix="/archive/backtest", tags=["archive-backtest"])

    @router.post("/run")
    @router.post("/runs")
    async def create_run(request: BacktestRunRequest):
        try:
            report = run_backtest(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record = create_run_record(request, report, kind="run")
        await store.save_run(record)
        return record.model_dump(mode="json")

    @router.post("/sweep")
    @router.post("/sweeps")
    async def create_sweep(request: BacktestSweepRequest):
        result = run_sweep(request)
        return result.model_dump(mode="json")

    @router.post("/walk-forward")
    async def create_walk_forward(request: BacktestWalkForwardRequest):
        result = run_walk_forward(request)
        return result.model_dump(mode="json")

    @router.post("/stress")
    async def create_stress(request: BacktestStressRequest):
        result = run_stress(request)
        return result.model_dump(mode="json")

    @router.get("/runs")
    async def list_runs(limit: int = 100):
        records = await store.list_runs(limit=limit)
        return {"runs": [record.model_dump(mode="json") for record in records]}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        record = await store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Backtest run '{run_id}' not found")
        return record.model_dump(mode="json")

    @router.get("/runs/{run_id}/export.json")
    async def export_json(run_id: str):
        record = await store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Backtest run '{run_id}' not found")
        return report_to_json(record.report)

    @router.get("/runs/{run_id}/export.csv", response_class=PlainTextResponse)
    async def export_csv(run_id: str):
        record = await store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Backtest run '{run_id}' not found")
        return report_to_csv(record.report)

    return router
