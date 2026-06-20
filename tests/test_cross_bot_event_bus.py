import os

from fastapi.testclient import TestClient

from simulation_engine.api import create_app
from simulation_engine.bot_event_bus import BotEvent, EventBusStore


def test_event_bus_store_publishes_and_reads_recent_events(tmp_path):
    store = EventBusStore(tmp_path / "events")
    event = store.publish(
        BotEvent(
            event_type="edge.action",
            source_bot="sentinel-edge",
            target_bots=["simulation-engine"],
            payload={"contract_version": "edge.action.v1", "action": "stop_buying"},
        )
    )

    recent = store.recent(event_type="edge.action")

    assert recent[0]["event_id"] == event.event_id
    assert recent[0]["payload"]["action"] == "stop_buying"


def test_bus_routes_accept_and_return_events(tmp_path):
    old_event_dir = os.environ.get("BOT_EVENT_BUS_DIR")
    os.environ["BOT_EVENT_BUS_DIR"] = str(tmp_path / "events")
    try:
        app = create_app(recorder_db_path=tmp_path / "recorder.sqlite3")
        with TestClient(app) as client:
            response = client.post(
                "/api/bus/events",
                json={
                    "event_type": "edge.action",
                    "source_bot": "sentinel-edge",
                    "target_bots": ["simulation-engine"],
                    "payload": {"contract_version": "edge.action.v1", "action": "stop_buying"},
                },
            )
            events = client.get("/api/bus/events?event_type=edge.action").json()["events"]

        assert response.status_code == 200
        assert events[0]["payload"]["action"] == "stop_buying"
    finally:
        if old_event_dir is None:
            os.environ.pop("BOT_EVENT_BUS_DIR", None)
        else:
            os.environ["BOT_EVENT_BUS_DIR"] = old_event_dir


def test_recorder_ingest_publishes_discord_message_event(tmp_path):
    old_event_dir = os.environ.get("BOT_EVENT_BUS_DIR")
    os.environ["BOT_EVENT_BUS_DIR"] = str(tmp_path / "events")
    try:
        app = create_app(recorder_db_path=tmp_path / "recorder.sqlite3")
        with TestClient(app) as client:
            client.put(
                "/api/recorder/discord/settings",
                json={
                    "discord_token": "",
                    "discord_channel_ids": ["123"],
                    "drift_amount_threshold": 0.05,
                    "drift_percent_threshold": 10,
                    "yfinance_enabled": False,
                    "record_all_channels": False,
                },
            )
            ingest = client.post(
                "/api/recorder/dev/ingest-message",
                json={
                    "message_id": "bus-m1",
                    "channel_id": "123",
                    "channel_name": "alerts",
                    "author_id": "a1",
                    "author_name": "Analyst",
                    "discord_timestamp": "2026-06-19T14:30:00+00:00",
                    "content": "BTO SPY 500C 6/21 @ 1.25",
                },
            )
            events = client.get(
                "/api/bus/events?event_type=simulation.recording.discord_message"
            ).json()["events"]

        assert ingest.status_code == 200
        assert ingest.json()["status"] == "recorded"
        assert events[0]["payload"]["message_id"] == "bus-m1"
    finally:
        if old_event_dir is None:
            os.environ.pop("BOT_EVENT_BUS_DIR", None)
        else:
            os.environ["BOT_EVENT_BUS_DIR"] = old_event_dir
