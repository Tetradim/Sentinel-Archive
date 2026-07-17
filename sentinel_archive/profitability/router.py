from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sentinel_archive.backtesting.audit_store import AuditStore
from sentinel_archive.profitability.engine import (
    run_profitability_comparison,
    run_profitability_study,
)
from sentinel_archive.profitability.models import (
    ProfitabilityComparisonRequest,
    ProfitabilityStudyRequest,
)


def create_profitability_router(store: AuditStore) -> APIRouter:
    router = APIRouter(prefix="/archive/profitability", tags=["archive-profitability"])

    @router.get("/adapters")
    async def list_adapters():
        return {
            "adapters": [
                {
                    "profile": "iron_trend",
                    "bot_id": "iron",
                    "entry_source": "native Sentinel-Iron trend strategy",
                    "profitability_scope": "independent strategy evidence",
                },
                {
                    "profile": "iron_volatility_trend",
                    "bot_id": "iron",
                    "entry_source": "native Sentinel-Iron volatility-adjusted trend strategy",
                    "profitability_scope": "independent strategy evidence",
                },
                {
                    "profile": "iron_carry",
                    "bot_id": "iron",
                    "entry_source": "native Sentinel-Iron futures-curve carry strategy",
                    "profitability_scope": "requires timestamped curve_snapshots",
                },
                {
                    "profile": "iron_composite",
                    "bot_id": "iron",
                    "entry_source": "native Sentinel-Iron weighted trend and carry strategy",
                    "profitability_scope": "requires timestamped curve_snapshots",
                },
                {
                    "profile": "chain_signal_replay",
                    "bot_id": "chain",
                    "entry_source": "timestamped recorded Chain signals",
                    "profitability_scope": "conditional on supplied signal stream",
                },
                {
                    "profile": "chain_auto_structure",
                    "bot_id": "chain",
                    "entry_source": "native Sentinel-Chain EMA/RSI/ATR auto strategy",
                    "profitability_scope": "independent next-bar strategy evidence",
                },
                {
                    "profile": "combination_routed",
                    "bot_id": "combination",
                    "entry_source": "Iron or Chain source selected by source_profile",
                    "profitability_scope": "inherited evidence; never an independent edge verdict",
                },
            ],
            "verdict_policy": "Profitable is emitted only after every configured data, native-strategy, out-of-sample, risk, bootstrap, benchmark, and cost-stress gate passes.",
        }

    @router.post("/study")
    async def create_study(request: ProfitabilityStudyRequest):
        try:
            report = run_profitability_study(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = report.model_dump(mode="json")
        await store.save(
            run_id=report.study_id,
            kind="profitability",
            bot_id=report.bot_id,
            symbol=report.symbol,
            fingerprint=report.fingerprint,
            payload=payload,
        )
        return payload

    @router.post("/compare")
    async def create_comparison(request: ProfitabilityComparisonRequest):
        try:
            report = run_profitability_comparison(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = report.model_dump(mode="json")
        symbol = report.studies[0].symbol if report.studies else "MULTI"
        await store.save(
            run_id=report.comparison_id,
            kind="profitability_comparison",
            bot_id="multi-layer",
            symbol=symbol,
            fingerprint=report.fingerprint,
            payload=payload,
        )
        return payload

    @router.get("/runs")
    async def list_runs(limit: int = 100, bot_id: str | None = None, symbol: str | None = None):
        studies = await store.list(limit=limit, kind="profitability", bot_id=bot_id, symbol=symbol)
        comparisons = [] if bot_id else await store.list(
            limit=limit,
            kind="profitability_comparison",
            symbol=symbol,
        )
        return {"runs": [*studies, *comparisons][:limit]}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        payload = await store.get(run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"Profitability run '{run_id}' not found")
        return payload

    return router
