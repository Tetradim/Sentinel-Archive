from __future__ import annotations

from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def test_archive_presets_are_served_from_backend(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    catalog = client.get("/api/archive/presets").json()

    assert "strategies" in catalog
    assert "brackets" in catalog
    assert "cost_models" in catalog
    assert any(item["id"] == "options-alert-replay-mid" for item in catalog["strategies"])


def test_archive_datasets_save_list_and_fetch(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    created = client.post(
        "/api/archive/datasets",
        json={
            "name": "SPY sample",
            "asset_class": "stock",
            "symbol": "SPY",
            "bars": [
                {"timestamp": "2026-07-01T13:30:00Z", "symbol": "SPY", "open": 100, "high": 101, "low": 99, "close": 100.5}
            ],
        },
    )

    assert created.status_code == 200
    dataset_id = created.json()["dataset_id"]
    listed = client.get("/api/archive/datasets?asset_class=stock&symbol=SPY").json()
    assert listed["total"] == 1
    assert listed["datasets"][0]["dataset_id"] == dataset_id
    assert client.get(f"/api/archive/datasets/{dataset_id}").json()["name"] == "SPY sample"


def test_archive_backtest_run_history_filters_and_paginates(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))
    for symbol in ["SPY", "QQQ"]:
        response = client.post(
            "/api/archive/backtest/run",
            json={
                "asset_class": "stock",
                "symbol": symbol,
                "quantity": 1,
                "bars": [
                    {"timestamp": "2026-07-01T13:30:00Z", "symbol": symbol, "open": 100, "high": 101, "low": 99, "close": 100.5}
                ],
            },
        )
        assert response.status_code == 200

    filtered = client.get("/api/archive/backtest/runs?symbol=SPY&asset_class=stock&limit=1&offset=0").json()

    assert filtered["total"] == 1
    assert filtered["runs"][0]["symbol"] == "SPY"
    assert filtered["limit"] == 1
