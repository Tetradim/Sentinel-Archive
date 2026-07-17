from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .models import (
    BotObservationRequest,
    CreateRunRequest,
    DatasetImportRequest,
    PublishDirectiveRequest,
    RegisterParticipantRequest,
    SubmitOrderRequest,
)
from .service import GeneralApiError, GeneralBrokerService


class StartRunRequest(BaseModel):
    reset: bool = False


def create_general_api_router(service: GeneralBrokerService) -> APIRouter:
    router = APIRouter(prefix="/general", tags=["General Replay and Brokerage API"])

    def bot_auth(
        run_id: str,
        participant_id: str,
        token: str | None,
    ) -> None:
        try:
            service.authorize_participant(run_id, participant_id, token)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except GeneralApiError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/spec")
    async def api_spec():
        return service.api_spec()

    @router.post("/datasets/import/csv", status_code=201)
    async def import_dataset(request: DatasetImportRequest):
        return _call(service.import_dataset, request)

    @router.get("/datasets")
    async def list_datasets():
        return {"datasets": service.datasets()}

    @router.get("/datasets/{dataset_id}")
    async def get_dataset(dataset_id: str):
        return _call(service.dataset, dataset_id, not_found=True)

    @router.post("/runs", status_code=201)
    async def create_run(request: CreateRunRequest):
        return _call(service.create_run, request)

    @router.get("/runs")
    async def list_runs():
        return {"runs": service.runs()}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        return _call(service.run, run_id, not_found=True)

    @router.post("/runs/{run_id}/start")
    async def start_run(run_id: str, request: StartRunRequest | None = None):
        return _call(service.start_run, run_id, reset=(request or StartRunRequest()).reset, not_found=True)

    @router.post("/runs/{run_id}/stop")
    async def stop_run(run_id: str):
        return _call(service.stop_run, run_id, not_found=True)

    @router.post("/runs/{run_id}/step")
    async def step_run(run_id: str):
        return _call(service.step_run, run_id, not_found=True)

    @router.post("/runs/{run_id}/participants", status_code=201)
    async def register_participant(run_id: str, request: RegisterParticipantRequest):
        return _call(service.register_participant, run_id, request, not_found=True)

    @router.get("/runs/{run_id}/participants")
    async def list_participants(run_id: str):
        return {"participants": _call(service.participants, run_id, not_found=True)}

    @router.get("/runs/{run_id}/participants/{participant_id}/market/latest")
    async def latest_market(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.latest_market, run_id, participant_id, not_found=True)

    @router.get("/runs/{run_id}/participants/{participant_id}/instruments")
    async def instruments(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return {"instruments": _call(service.instruments, run_id, participant_id, not_found=True)}

    @router.get("/runs/{run_id}/events")
    async def events(
        run_id: str,
        participant_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=1000, ge=1, le=5000),
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        result = _call(
            service.events,
            run_id,
            participant_id=participant_id,
            after=after,
            limit=limit,
            not_found=True,
        )
        latest = result[-1].sequence if result else after
        return {"events": result, "next_after": latest}

    @router.websocket("/runs/{run_id}/stream/{participant_id}")
    async def event_stream(websocket: WebSocket, run_id: str, participant_id: str):
        token = websocket.headers.get("X-Archive-Bot-Token") or websocket.query_params.get("token")
        try:
            service.authorize_participant(run_id, participant_id, token)
        except (PermissionError, GeneralApiError):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        after = int(websocket.query_params.get("after", "0") or 0)
        try:
            while True:
                events = service.events(run_id, participant_id=participant_id, after=after, limit=1000)
                for event in events:
                    await websocket.send_json(event.model_dump(mode="json"))
                    after = event.sequence
                await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            return

    @router.post("/runs/{run_id}/participants/{participant_id}/orders", status_code=202)
    async def submit_order(
        run_id: str,
        participant_id: str,
        request: SubmitOrderRequest,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.submit_order, run_id, participant_id, request, not_found=True)

    @router.get("/runs/{run_id}/participants/{participant_id}/orders")
    async def list_orders(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return {"orders": _call(service.orders, run_id, participant_id, not_found=True)}

    @router.get("/runs/{run_id}/participants/{participant_id}/orders/{order_id}")
    async def get_order(
        run_id: str,
        participant_id: str,
        order_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.order, run_id, participant_id, order_id, not_found=True)

    @router.get("/runs/{run_id}/participants/{participant_id}/fills")
    async def list_fills(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return {"fills": _call(service.fills, run_id, participant_id, not_found=True)}

    @router.delete("/runs/{run_id}/participants/{participant_id}/orders/{order_id}")
    async def cancel_order(
        run_id: str,
        participant_id: str,
        order_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.cancel_order, run_id, participant_id, order_id, not_found=True)

    @router.get("/runs/{run_id}/participants/{participant_id}/account")
    async def account(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.account, run_id, participant_id, not_found=True)

    @router.post("/runs/{run_id}/participants/{participant_id}/observations", status_code=202)
    async def observation(
        run_id: str,
        participant_id: str,
        request: BotObservationRequest,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.publish_observation, run_id, participant_id, request, not_found=True)

    @router.post("/runs/{run_id}/participants/{participant_id}/directives", status_code=202)
    async def publish_directive(
        run_id: str,
        participant_id: str,
        request: PublishDirectiveRequest,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(service.publish_directive, run_id, participant_id, request, not_found=True)

    @router.get("/runs/{run_id}/participants/{participant_id}/directives")
    async def list_directives(
        run_id: str,
        participant_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return {"directives": _call(service.directives, run_id, participant_id, not_found=True)}

    @router.post("/runs/{run_id}/participants/{participant_id}/directives/{directive_id}/ack")
    async def acknowledge_directive(
        run_id: str,
        participant_id: str,
        directive_id: str,
        x_archive_bot_token: str | None = Header(default=None, alias="X-Archive-Bot-Token"),
    ):
        bot_auth(run_id, participant_id, x_archive_bot_token)
        return _call(
            service.acknowledge_directive,
            run_id,
            participant_id,
            directive_id,
            not_found=True,
        )

    @router.get("/runs/{run_id}/report")
    async def report(run_id: str):
        return _call(service.report, run_id, not_found=True)

    return router


def _call(function: Any, *args: Any, not_found: bool = False, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except GeneralApiError as exc:
        raise HTTPException(status_code=404 if not_found else 400, detail=str(exc)) from exc
