from __future__ import annotations

from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def _request() -> dict:
    return {
        "bot_id": "iron",
        "symbol": "MES",
        "quantity": 1,
        "starting_equity": 5000,
        "leverage": 10,
        "contract": {
            "symbol": "MES",
            "venue": "CME",
            "instrument_type": "listed_future",
            "contract_multiplier": 5,
            "tick_size": 0.25,
            "quantity_step": 1,
            "minimum_quantity": 1,
            "initial_margin_rate": 0.1,
            "maintenance_margin_rate": 0.08,
            "maximum_leverage": 20,
        },
        "bars": [
            {"timestamp": "2026-07-01T13:30:00Z", "symbol": "MES", "open": 5000, "high": 5002, "low": 4998, "close": 5001, "volume": 1000},
            {"timestamp": "2026-07-01T13:31:00Z", "symbol": "MES", "open": 5001, "high": 5005, "low": 4999, "close": 5004, "volume": 1000},
        ],
    }


def test_derivatives_run_is_persisted_and_contract_catalog_is_available(tmp_path):
    with TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3")) as client:
        response = client.post("/api/archive/derivatives/run", json=_request())
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        assert client.get(f"/api/archive/derivatives/runs/{run_id}").status_code == 200
        assert client.get("/api/archive/derivatives/runs?bot_id=iron").json()["runs"][0]["run_id"] == run_id
        contracts = client.get("/api/archive/derivatives/contracts").json()["contracts"]
        assert contracts["CME:MES"]["contract_multiplier"] == 5


def test_derivatives_compare_persists_combined_layer(tmp_path):
    with TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3")) as client:
        base = _request()
        base["orders"] = []
        order = {"order_id": "entry", "side": "long", "order_type": "market", "quantity": 1}
        response = client.post(
            "/api/archive/derivatives/compare",
            json={
                "name": "Iron and Combination",
                "base_request": base,
                "layers": [
                    {"layer_id": "iron", "label": "Iron", "bot_id": "iron", "orders": [order]},
                    {"layer_id": "combination", "label": "Combination", "bot_id": "combination", "orders": [order]},
                ],
            },
        )

        assert response.status_code == 200
        assert response.json()["combined_assessment"]["verdict"] == "parity_observed"
