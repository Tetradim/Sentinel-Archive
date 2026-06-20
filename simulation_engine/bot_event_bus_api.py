from __future__ import annotations

from fastapi import APIRouter

from .bot_event_bus import BotEvent, event_bus


def create_bot_event_bus_router() -> APIRouter:
    router = APIRouter(tags=["Cross Bot Event Bus"])

    @router.post("/bus/events")
    async def publish_bus_event(event: BotEvent):
        accepted = event_bus.publish(event)
        return {"status": "accepted", "event": accepted.model_dump(mode="json")}

    @router.get("/bus/events")
    async def recent_bus_events(limit: int = 100, event_type: str | None = None):
        return {"events": event_bus.recent(limit=limit, event_type=event_type)}

    return router
