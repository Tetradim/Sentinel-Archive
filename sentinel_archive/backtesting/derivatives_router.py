from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sentinel_archive.backtesting.audit_store import AuditStore
from sentinel_archive.backtesting.contracts import contract_catalog
from sentinel_archive.backtesting.derivatives import run_derivatives_backtest
from sentinel_archive.backtesting.differential import run_differential_audit
from sentinel_archive.backtesting.models import DerivativesRunRequest, DifferentialAuditRequest


def create_derivatives_router(store: AuditStore) -> APIRouter:
    router = APIRouter(prefix="/archive/derivatives", tags=["archive-derivatives"])

    @router.get("/contracts")
    async def list_contracts():
        return {
            "contracts": contract_catalog(),
            "warning": "Research defaults only; verify venue and broker specifications before every audit.",
        }

    @router.post("/run")
    async def create_run(request: DerivativesRunRequest):
        try:
            report = run_derivatives_backtest(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = report.model_dump(mode="json")
        await store.save(
            run_id=report.run_id,
            kind="derivatives",
            bot_id=report.bot_id,
            symbol=report.symbol,
            fingerprint=report.fingerprint,
            payload=payload,
        )
        return payload

    @router.post("/compare")
    async def create_comparison(request: DifferentialAuditRequest):
        try:
            report = run_differential_audit(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = report.model_dump(mode="json")
        await store.save(
            run_id=report.audit_id,
            kind="differential",
            bot_id="multi-layer",
            symbol=request.base_request.symbol,
            fingerprint=report.fingerprint,
            payload=payload,
        )
        return payload

    @router.get("/runs")
    async def list_runs(limit: int = 100, kind: str | None = None, bot_id: str | None = None, symbol: str | None = None):
        return {"runs": await store.list(limit=limit, kind=kind, bot_id=bot_id, symbol=symbol)}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        payload = await store.get(run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"Derivatives run '{run_id}' not found")
        return payload

    return router
