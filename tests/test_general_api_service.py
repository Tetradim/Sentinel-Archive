from decimal import Decimal

from sentinel_archive.general_api.models import (
    BotObservationRequest,
    CreateRunRequest,
    DatasetImportRequest,
    InstrumentSpec,
    PublishDirectiveRequest,
    RegisterParticipantRequest,
    SubmitOrderRequest,
)
from sentinel_archive.general_api.service import GeneralBrokerService


RECORDED_MULTI_BOT_CSV = """timestamp,symbol,open,high,low,close,volume
2026-05-01T14:00:00Z,ES,5000,5005,4995,5001,20000
2026-05-01T14:00:00Z,SPY,100,101,99,100,1000000
2026-05-01T14:15:00Z,ES,5002,5012,4999,5010,25000
2026-05-01T14:15:00Z,SPY,101,103,100,102,1200000
2026-05-01T14:30:00Z,ES,4988,4992,4970,4975,40000
2026-05-01T14:30:00Z,SPY,103,105,102,104,1400000
"""


def build_service() -> tuple[GeneralBrokerService, str]:
    service = GeneralBrokerService()
    dataset = service.import_dataset(
        DatasetImportRequest(
            name="Recorded May market",
            data_kind="recorded",
            source_name="licensed historical export",
            retrieved_at="2026-07-16T00:00:00Z",
            csv_text=RECORDED_MULTI_BOT_CSV,
            instruments=[
                InstrumentSpec(
                    symbol="ES",
                    asset_class="future",
                    multiplier=Decimal("50"),
                    tick_size=Decimal("0.25"),
                    initial_margin=Decimal("12000"),
                ),
                InstrumentSpec(symbol="SPY", asset_class="stock"),
            ],
        )
    )
    run = service.create_run(CreateRunRequest(dataset_id=dataset.dataset_id, name="May shared replay"))
    return service, run.run_id


def test_replaying_market_without_bot_orders_cannot_create_pnl():
    service, run_id = build_service()
    service.register_participant(
        run_id,
        RegisterParticipantRequest(participant_id="pulse", bot_id="sentinel-pulse", subscribed_symbols=["SPY"]),
    )

    service.step_run(run_id)
    service.step_run(run_id)
    report = service.report(run_id)

    assert report["strategy_logic_in_archive"] is False
    assert report["archive_generated_order_count"] == 0
    assert report["bot_generated_order_count"] == 0
    assert report["broker_fill_count"] == 0
    assert report["participants"][0]["account"]["total_pnl"] == "0"


def test_pulse_iron_and_edge_share_one_replay_without_sharing_accounts_or_orders():
    service, run_id = build_service()
    pulse = service.register_participant(
        run_id,
        RegisterParticipantRequest(
            participant_id="pulse",
            bot_id="sentinel-pulse",
            subscribed_symbols=["SPY"],
            commission_per_order=Decimal("1"),
        ),
    )
    iron = service.register_participant(
        run_id,
        RegisterParticipantRequest(
            participant_id="iron",
            bot_id="sentinel-iron",
            subscribed_symbols=["ES"],
            commission_per_order=Decimal("2.50"),
        ),
    )
    edge = service.register_participant(
        run_id,
        RegisterParticipantRequest(
            participant_id="edge",
            bot_id="sentinel-edge",
            roles=["observer", "risk_controller"],
            subscribed_symbols=["ES", "SPY"],
        ),
    )

    assert pulse.api_token != iron.api_token != edge.api_token
    service.step_run(run_id)

    service.submit_order(
        run_id,
        "pulse",
        SubmitOrderRequest(client_order_id="pulse-buy-1", symbol="SPY", side="buy", quantity=10),
    )
    service.submit_order(
        run_id,
        "iron",
        SubmitOrderRequest(client_order_id="iron-buy-1", symbol="ES", side="buy", quantity=1),
    )
    service.step_run(run_id)

    observation = service.publish_observation(
        run_id,
        "edge",
        BotObservationRequest(
            event_type="market_shift_detected",
            symbol="ES",
            decision="halt_futures_entries",
            reason="bearish market structure",
            confidence=Decimal("0.87"),
        ),
    )
    assert observation.payload["reported_by_bot"] is True
    directive = service.publish_directive(
        run_id,
        "edge",
        PublishDirectiveRequest(
            directive_type="halt_new_orders",
            target_participant_ids=["iron"],
            symbol="ES",
            reason="market shift threatens the open futures strategy",
            severity="critical",
        ),
    )
    service.acknowledge_directive(run_id, "iron", directive.directive_id)

    rejected = service.submit_order(
        run_id,
        "iron",
        SubmitOrderRequest(client_order_id="iron-add-after-halt", symbol="ES", side="buy", quantity=1),
    )
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "new_orders_halted_after_acknowledged_directive"

    iron_exit = service.submit_order(
        run_id,
        "iron",
        SubmitOrderRequest(
            client_order_id="iron-risk-exit",
            symbol="ES",
            side="sell",
            quantity=1,
            reduce_only=True,
        ),
    )
    pulse_exit = service.submit_order(
        run_id,
        "pulse",
        SubmitOrderRequest(
            client_order_id="pulse-sell-1",
            symbol="SPY",
            side="sell",
            quantity=10,
            reduce_only=True,
        ),
    )
    assert iron_exit.status == pulse_exit.status == "accepted"
    service.step_run(run_id)

    pulse_account = service.account(run_id, "pulse")
    iron_account = service.account(run_id, "iron")
    edge_account = service.account(run_id, "edge")
    assert pulse_account.total_pnl == Decimal("18")
    assert iron_account.total_pnl == Decimal("-705")
    assert edge_account.total_pnl == Decimal("0")
    assert edge_account.order_count == 0
    assert pulse_account.positions == []
    assert iron_account.positions == []

    report = service.report(run_id)
    assert report["archive_generated_order_count"] == 0
    assert report["bot_generated_order_count"] == 5
    assert report["broker_fill_count"] == 4
    assert report["directives"][0]["acknowledged_by"] == ["iron"]
    assert all(item["pnl_exists_only_from_bot_orders"] for item in report["participants"])

    pulse_events = service.events(run_id, participant_id="pulse")
    assert not any(event.bot_id == "sentinel-iron" and event.event_type.startswith("broker.") for event in pulse_events)
    edge_events = service.events(run_id, participant_id="edge")
    assert any(event.event_type == "control.directive_acknowledged" for event in edge_events)


def test_duplicate_client_order_id_is_idempotent():
    service, run_id = build_service()
    service.register_participant(
        run_id,
        RegisterParticipantRequest(participant_id="pulse", bot_id="sentinel-pulse", subscribed_symbols=["SPY"]),
    )
    request = SubmitOrderRequest(client_order_id="stable-id", symbol="SPY", side="buy", quantity=1)

    first = service.submit_order(run_id, "pulse", request)
    second = service.submit_order(run_id, "pulse", request)

    assert first.order_id == second.order_id
    assert len(service.orders(run_id, "pulse")) == 1


def test_same_bar_oco_ambiguity_uses_stop_first_and_cancels_target():
    service = GeneralBrokerService()
    dataset = service.import_dataset(
        DatasetImportRequest(
            name="Recorded ambiguous bracket",
            data_kind="recorded",
            source_name="historical provider export",
            csv_text=(
                "timestamp,symbol,open,high,low,close,volume\n"
                "2026-05-01T14:00:00Z,SPY,100,101,99,100,1000\n"
                "2026-05-01T14:15:00Z,SPY,101,103,100,102,1000\n"
                "2026-05-01T14:30:00Z,SPY,102,106,99,104,1000\n"
            ),
        )
    )
    run = service.create_run(CreateRunRequest(dataset_id=dataset.dataset_id))
    service.register_participant(
        run.run_id,
        RegisterParticipantRequest(participant_id="pulse", bot_id="sentinel-pulse"),
    )
    service.step_run(run.run_id)
    service.submit_order(
        run.run_id,
        "pulse",
        SubmitOrderRequest(client_order_id="entry", symbol="SPY", side="buy", quantity=1),
    )
    service.step_run(run.run_id)
    stop = service.submit_order(
        run.run_id,
        "pulse",
        SubmitOrderRequest(
            client_order_id="stop",
            symbol="SPY",
            side="sell",
            quantity=1,
            order_type="stop",
            stop_price=100,
            reduce_only=True,
            oco_group="exit-1",
        ),
    )
    target = service.submit_order(
        run.run_id,
        "pulse",
        SubmitOrderRequest(
            client_order_id="target",
            symbol="SPY",
            side="sell",
            quantity=1,
            order_type="limit",
            limit_price=105,
            reduce_only=True,
            oco_group="exit-1",
        ),
    )

    service.step_run(run.run_id)
    orders = {order.order_id: order for order in service.orders(run.run_id, "pulse")}

    assert orders[stop.order_id].status == "filled"
    assert orders[target.order_id].status == "canceled"
    assert service.account(run.run_id, "pulse").total_pnl == Decimal("-1.00")


def test_volume_participation_creates_attributable_partial_fills():
    service = GeneralBrokerService()
    dataset = service.import_dataset(
        DatasetImportRequest(
            name="Recorded thin market",
            data_kind="recorded",
            source_name="historical provider export",
            csv_text=(
                "timestamp,symbol,open,high,low,close,volume\n"
                "2026-05-01T14:00:00Z,XYZ,10,10,10,10,10\n"
                "2026-05-01T14:15:00Z,XYZ,10,10,10,10,10\n"
                "2026-05-01T14:30:00Z,XYZ,10,10,10,10,10\n"
            ),
            instruments=[InstrumentSpec(symbol="XYZ", max_volume_participation_pct=Decimal("10"))],
        )
    )
    run = service.create_run(CreateRunRequest(dataset_id=dataset.dataset_id))
    service.register_participant(
        run.run_id,
        RegisterParticipantRequest(participant_id="pulse", bot_id="sentinel-pulse"),
    )
    service.step_run(run.run_id)
    order = service.submit_order(
        run.run_id,
        "pulse",
        SubmitOrderRequest(client_order_id="thin-entry", symbol="XYZ", side="buy", quantity=2),
    )

    service.step_run(run.run_id)
    assert service.orders(run.run_id, "pulse")[0].status == "partially_filled"
    service.step_run(run.run_id)
    final_order = service.orders(run.run_id, "pulse")[0]

    assert final_order.order_id == order.order_id
    assert final_order.status == "filled"
    assert final_order.filled_quantity == Decimal("2")
    assert service.account(run.run_id, "pulse").fill_count == 2
