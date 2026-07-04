from __future__ import annotations

from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def test_bot_suite_api_saves_plan_and_runs_selected_jobs(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    created = client.post(
        "/api/archive/bot-suite/plans",
        json={
            "name": "pulse health",
            "bots": ["pulse"],
            "test_families": ["replay_health"],
            "compute_budget": {"max_jobs": 2},
        },
    )

    assert created.status_code == 200
    plan_id = created.json()["plan_id"]
    run = client.post(f"/api/archive/bot-suite/plans/{plan_id}/run")

    assert run.status_code == 200
    assert run.json()["plan_id"] == plan_id
    assert {job["bot_id"] for job in run.json()["jobs"]} == {"pulse"}
