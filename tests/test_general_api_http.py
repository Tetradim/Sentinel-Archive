from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def test_general_api_requires_bot_token_and_never_returns_future_bars(tmp_path):
    with TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3")) as client:
        imported = client.post(
            "/api/general/datasets/import/csv",
            json={
                "name": "Recorded SPY day",
                "data_kind": "recorded",
                "source_name": "historical provider export",
                "csv_text": (
                    "timestamp,symbol,open,high,low,close,volume\n"
                    "2026-05-01T14:00:00Z,SPY,100,101,99,100,1000\n"
                    "2026-05-01T14:15:00Z,SPY,101,103,100,102,1200\n"
                ),
            },
        )
        assert imported.status_code == 201
        dataset = imported.json()
        run = client.post(
            "/api/general/runs",
            json={"dataset_id": dataset["dataset_id"], "name": "HTTP replay"},
        ).json()
        registration = client.post(
            f"/api/general/runs/{run['run_id']}/participants",
            json={"participant_id": "pulse", "bot_id": "sentinel-pulse", "subscribed_symbols": ["SPY"]},
        ).json()
        token = registration["api_token"]
        participant_url = f"/api/general/runs/{run['run_id']}/participants/pulse"

        assert client.get(f"/api/general/runs/{run['run_id']}/events", params={"participant_id": "pulse"}).status_code == 401
        client.post(f"/api/general/runs/{run['run_id']}/step")
        latest = client.get(
            f"{participant_url}/market/latest",
            headers={"X-Archive-Bot-Token": token},
        ).json()
        assert latest["virtual_timestamp"] == "2026-05-01T14:00:00Z"
        assert latest["bars"]["SPY"]["close"] == 100.0
        assert "2026-05-01T14:15:00Z" not in str(latest)

        order = client.post(
            f"{participant_url}/orders",
            headers={"X-Archive-Bot-Token": token},
            json={
                "client_order_id": "pulse-http-buy",
                "symbol": "SPY",
                "side": "buy",
                "quantity": 2,
                "order_type": "market",
            },
        )
        assert order.status_code == 202
        assert order.json()["status"] == "accepted"
        client.post(f"/api/general/runs/{run['run_id']}/step")

        account = client.get(
            f"{participant_url}/account",
            headers={"X-Archive-Bot-Token": token},
        ).json()
        assert account["fill_count"] == 1
        assert account["positions"][0]["average_entry_price"] == "101.00"
        report = client.get(f"/api/general/runs/{run['run_id']}/report").json()
        assert report["archive_generated_order_count"] == 0
        assert report["bot_generated_order_count"] == 1
        assert report["broker_fill_count"] == 1


def test_general_api_spec_states_the_non_strategy_boundary(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    spec = client.get("/api/general/spec").json()

    assert spec["contract_version"] == "archive.general.v1"
    assert spec["strategy_logic"] == "none"
    assert "submitted by a registered bot" in spec["order_origin_rule"]
