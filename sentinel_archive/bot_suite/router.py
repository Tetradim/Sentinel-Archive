from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sentinel_archive.bot_suite.models import SuitePlanRequest
from sentinel_archive.bot_suite.planner import build_suite_plan, build_suite_run
from sentinel_archive.bot_suite.store import BotSuiteStore


def create_bot_suite_router(store: BotSuiteStore) -> APIRouter:
    router = APIRouter(prefix="/archive/bot-suite", tags=["archive-bot-suite"])

    @router.post("/plans")
    async def create_plan(request: SuitePlanRequest):
        try:
            plan = build_suite_plan(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await store.save_plan(plan)
        return plan.model_dump(mode="json")

    @router.get("/plans")
    async def list_plans(limit: int = 100):
        plans = await store.list_plans(limit=limit)
        return {"plans": [plan.model_dump(mode="json") for plan in plans]}

    @router.get("/plans/{plan_id}")
    async def get_plan(plan_id: str):
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail=f"Suite plan '{plan_id}' not found")
        return plan.model_dump(mode="json")

    @router.post("/plans/{plan_id}/run")
    async def run_plan(plan_id: str):
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail=f"Suite plan '{plan_id}' not found")
        run = build_suite_run(plan)
        await store.save_run(run)
        return run.model_dump(mode="json")

    @router.get("/runs")
    async def list_runs(limit: int = 100):
        runs = await store.list_runs(limit=limit)
        return {"runs": [run.model_dump(mode="json") for run in runs]}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = await store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Suite run '{run_id}' not found")
        return run.model_dump(mode="json")

    @router.get("/runs/{run_id}/export.json")
    async def export_run(run_id: str):
        run = await store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Suite run '{run_id}' not found")
        return run.model_dump(mode="json")

    return router
