from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sentinel_archive.csv_import import parse_ohlcv_csv
from sentinel_archive.models import MarketBar

from .models import (
    AccountSnapshot,
    BotObservationRequest,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    ControlDirective,
    CreateRunRequest,
    DatasetImportRequest,
    DatasetSummary,
    GeneralEvent,
    InstrumentSpec,
    Participant,
    ParticipantRegistration,
    PublishDirectiveRequest,
    RegisterParticipantRequest,
    ReplayRun,
    SubmitOrderRequest,
)


ZERO = Decimal("0")


class GeneralApiError(ValueError):
    pass


@dataclass
class _Dataset:
    summary: DatasetSummary
    bars: list[MarketBar]
    instruments: dict[str, InstrumentSpec]


@dataclass
class _Position:
    symbol: str
    quantity: Decimal = ZERO
    average_entry_price: Decimal = ZERO
    realized_pnl: Decimal = ZERO


@dataclass
class _Account:
    participant: Participant
    cash: Decimal
    realized_pnl: Decimal = ZERO
    commission_paid: Decimal = ZERO
    positions: dict[str, _Position] = field(default_factory=dict)
    orders: dict[str, BrokerOrder] = field(default_factory=dict)
    client_order_ids: dict[str, str] = field(default_factory=dict)
    fills: list[BrokerFill] = field(default_factory=list)


@dataclass
class _Run:
    public: ReplayRun
    events: list[GeneralEvent] = field(default_factory=list)
    participants: dict[str, Participant] = field(default_factory=dict)
    token_hashes: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, _Account] = field(default_factory=dict)
    orders: dict[str, BrokerOrder] = field(default_factory=dict)
    directives: dict[str, ControlDirective] = field(default_factory=dict)
    latest_bars: dict[str, MarketBar] = field(default_factory=dict)
    next_due: float = 0.0


class GeneralBrokerService:
    """Replay market plus broker-shaped accounting, with no strategy logic.

    The only way an order enters this service is through ``submit_order`` with an
    identified participant. Market replay never creates an order or directive.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, _Dataset] = {}
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()

    def api_spec(self) -> dict[str, Any]:
        return {
            "name": "Sentinel Archive General API",
            "contract_version": "archive.general.v1",
            "purpose": "recorded market replay, virtual brokerage, and attributable cross-bot event recording",
            "strategy_logic": "none",
            "order_origin_rule": "every broker order must be submitted by a registered bot participant",
            "replay_visibility_rule": "participants can read released events only; future dataset rows are never returned by participant routes",
            "interfaces": {
                "datasets": "/api/general/datasets",
                "runs": "/api/general/runs",
                "participants": "/api/general/runs/{run_id}/participants",
                "events": "/api/general/runs/{run_id}/events",
                "stream": "/api/general/runs/{run_id}/stream/{participant_id}",
                "orders": "/api/general/runs/{run_id}/participants/{participant_id}/orders",
                "account": "/api/general/runs/{run_id}/participants/{participant_id}/account",
                "instruments": "/api/general/runs/{run_id}/participants/{participant_id}/instruments",
                "observations": "/api/general/runs/{run_id}/participants/{participant_id}/observations",
                "directives": "/api/general/runs/{run_id}/participants/{participant_id}/directives",
                "report": "/api/general/runs/{run_id}/report",
            },
        }

    def import_dataset(self, request: DatasetImportRequest) -> DatasetSummary:
        bars = parse_ohlcv_csv(request.csv_text)
        normalized = request.csv_text.strip().replace("\r\n", "\n")
        checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        dataset_id = f"dataset-{checksum[:16]}"
        symbols = sorted({bar.symbol for bar in bars})
        supplied = {spec.symbol: spec for spec in request.instruments}
        instruments = {
            symbol: supplied.get(symbol, InstrumentSpec(symbol=symbol))
            for symbol in symbols
        }
        unknown_specs = sorted(set(supplied) - set(symbols))
        if unknown_specs:
            raise GeneralApiError(
                f"instrument specifications reference symbols absent from the CSV: {', '.join(unknown_specs)}"
            )
        summary = DatasetSummary(
            dataset_id=dataset_id,
            name=request.name,
            data_kind=request.data_kind,
            source_name=request.source_name,
            source_url=request.source_url,
            retrieved_at=request.retrieved_at,
            notes=request.notes,
            checksum_sha256=checksum,
            symbols=symbols,
            bar_count=len(bars),
            first_timestamp=bars[0].timestamp,
            last_timestamp=bars[-1].timestamp,
            instruments=list(instruments.values()),
        )
        with self._lock:
            self._datasets[dataset_id] = _Dataset(summary=summary, bars=bars, instruments=instruments)
        return summary

    def datasets(self) -> list[DatasetSummary]:
        with self._lock:
            return [dataset.summary.model_copy(deep=True) for dataset in self._datasets.values()]

    def dataset(self, dataset_id: str) -> DatasetSummary:
        with self._lock:
            return self._dataset(dataset_id).summary.model_copy(deep=True)

    def create_run(self, request: CreateRunRequest) -> ReplayRun:
        with self._lock:
            self._dataset(request.dataset_id)
            run_id = f"replay-{uuid.uuid4().hex[:16]}"
            run = _Run(
                public=ReplayRun(
                    run_id=run_id,
                    dataset_id=request.dataset_id,
                    name=request.name,
                    speed=request.speed,
                    loop=request.loop,
                )
            )
            self._runs[run_id] = run
            self._emit(run, "replay.created", payload={"dataset_id": request.dataset_id})
            return run.public.model_copy(deep=True)

    def runs(self) -> list[ReplayRun]:
        with self._lock:
            return [run.public.model_copy(deep=True) for run in self._runs.values()]

    def run(self, run_id: str) -> ReplayRun:
        with self._lock:
            return self._run(run_id).public.model_copy(deep=True)

    def start_run(self, run_id: str, *, reset: bool = False) -> ReplayRun:
        with self._lock:
            run = self._run(run_id)
            if reset:
                if run.orders or any(account.fills for account in run.accounts.values()):
                    raise GeneralApiError("a replay with broker activity cannot be reset; create a new run")
                run.public.index = 0
                run.public.current_timestamp = None
                run.latest_bars.clear()
            if run.public.state == "completed" and not reset:
                raise GeneralApiError("completed replay cannot be restarted; create a new run")
            run.public.state = "running"
            run.next_due = time.monotonic()
            self._emit(run, "replay.started", payload={"speed": run.public.speed})
            return run.public.model_copy(deep=True)

    def stop_run(self, run_id: str) -> ReplayRun:
        with self._lock:
            run = self._run(run_id)
            run.public.state = "stopped"
            self._emit(run, "replay.stopped")
            return run.public.model_copy(deep=True)

    def step_run(self, run_id: str) -> ReplayRun:
        with self._lock:
            run = self._run(run_id)
            self._step(run)
            return run.public.model_copy(deep=True)

    def advance_due_runs(self) -> int:
        advanced = 0
        now = time.monotonic()
        with self._lock:
            for run in self._runs.values():
                if run.public.state != "running" or now < run.next_due:
                    continue
                self._step(run)
                run.next_due = now + (1.0 / run.public.speed)
                advanced += 1
        return advanced

    def register_participant(self, run_id: str, request: RegisterParticipantRequest) -> ParticipantRegistration:
        with self._lock:
            run = self._run(run_id)
            participant_id = request.participant_id or f"participant-{uuid.uuid4().hex[:12]}"
            if participant_id in run.participants:
                raise GeneralApiError(f"participant '{participant_id}' already exists")
            dataset = self._dataset(run.public.dataset_id)
            subscriptions = request.subscribed_symbols or list(dataset.summary.symbols)
            unknown = sorted(set(subscriptions) - set(dataset.summary.symbols))
            if unknown:
                raise GeneralApiError(f"subscriptions are absent from the replay dataset: {', '.join(unknown)}")
            participant = Participant(
                participant_id=participant_id,
                bot_id=request.bot_id,
                display_name=request.display_name or request.bot_id,
                roles=request.roles,
                subscribed_symbols=subscriptions,
                starting_cash=request.starting_cash,
                commission_per_order=request.commission_per_order,
                slippage_bps=request.slippage_bps,
            )
            run.participants[participant_id] = participant
            api_token = secrets.token_urlsafe(32)
            run.token_hashes[participant_id] = hashlib.sha256(api_token.encode("utf-8")).hexdigest()
            run.accounts[participant_id] = _Account(participant=participant, cash=request.starting_cash)
            run.public.participant_ids.append(participant_id)
            self._emit(
                run,
                "participant.registered",
                participant_id=participant_id,
                bot_id=participant.bot_id,
                payload={
                    "roles": participant.roles,
                    "subscribed_symbols": participant.subscribed_symbols,
                },
            )
            return ParticipantRegistration(participant=participant.model_copy(deep=True), api_token=api_token)

    def authorize_participant(self, run_id: str, participant_id: str, api_token: str | None) -> None:
        with self._lock:
            run = self._run(run_id)
            self._participant(run, participant_id)
            expected = run.token_hashes.get(participant_id, "")
            provided = hashlib.sha256((api_token or "").encode("utf-8")).hexdigest()
            if not expected or not secrets.compare_digest(expected, provided):
                raise PermissionError("invalid Archive bot token")

    def participants(self, run_id: str) -> list[Participant]:
        with self._lock:
            run = self._run(run_id)
            return [participant.model_copy(deep=True) for participant in run.participants.values()]

    def latest_market(self, run_id: str, participant_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id)
            bars = {
                symbol: bar.model_dump(mode="json")
                for symbol, bar in run.latest_bars.items()
                if symbol in participant.subscribed_symbols
            }
            return {
                "run_id": run_id,
                "participant_id": participant_id,
                "virtual_timestamp": run.public.current_timestamp,
                "bars": bars,
            }

    def instruments(self, run_id: str, participant_id: str) -> list[InstrumentSpec]:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id)
            dataset = self._dataset(run.public.dataset_id)
            return [
                dataset.instruments[symbol].model_copy(deep=True)
                for symbol in participant.subscribed_symbols
            ]

    def submit_order(self, run_id: str, participant_id: str, request: SubmitOrderRequest) -> BrokerOrder:
        with self._lock:
            run = self._run(run_id)
            account = self._account(run, participant_id)
            participant = account.participant
            existing_id = account.client_order_ids.get(request.client_order_id)
            if existing_id:
                return account.orders[existing_id].model_copy(deep=True)

            order = BrokerOrder(
                order_id=f"order-{uuid.uuid4().hex[:16]}",
                run_id=run_id,
                participant_id=participant_id,
                bot_id=participant.bot_id,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                remaining_quantity=request.quantity,
                order_type=request.order_type,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                reduce_only=request.reduce_only,
                oco_group=request.oco_group,
                strategy_id=request.strategy_id,
                submitted_at=run.public.current_timestamp,
                submitted_sequence=run.public.latest_sequence,
                updated_at=run.public.current_timestamp,
                metadata=request.metadata,
                submitted_payload=request.model_dump(mode="json"),
            )
            account.client_order_ids[request.client_order_id] = order.order_id
            account.orders[order.order_id] = order
            run.orders[order.order_id] = order

            rejection = self._order_rejection(run, account, order)
            if rejection:
                order.status = "rejected"
                order.rejection_reason = rejection
                event_type = "broker.order_rejected"
            else:
                event_type = "broker.order_accepted"
            self._emit(
                run,
                event_type,
                participant_id=participant_id,
                bot_id=participant.bot_id,
                symbol=order.symbol,
                payload={
                    "order": order.model_dump(mode="json"),
                    "submitted_by_bot": True,
                },
            )
            return order.model_copy(deep=True)

    def orders(self, run_id: str, participant_id: str) -> list[BrokerOrder]:
        with self._lock:
            account = self._account(self._run(run_id), participant_id)
            return [order.model_copy(deep=True) for order in account.orders.values()]

    def order(self, run_id: str, participant_id: str, order_id: str) -> BrokerOrder:
        with self._lock:
            account = self._account(self._run(run_id), participant_id)
            order = account.orders.get(order_id)
            if order is None:
                raise GeneralApiError(f"order '{order_id}' was not found")
            return order.model_copy(deep=True)

    def fills(self, run_id: str, participant_id: str) -> list[BrokerFill]:
        with self._lock:
            account = self._account(self._run(run_id), participant_id)
            return [fill.model_copy(deep=True) for fill in account.fills]

    def cancel_order(self, run_id: str, participant_id: str, order_id: str) -> BrokerOrder:
        with self._lock:
            run = self._run(run_id)
            account = self._account(run, participant_id)
            order = account.orders.get(order_id)
            if order is None:
                raise GeneralApiError(f"order '{order_id}' was not found")
            if order.status not in {"accepted", "partially_filled"}:
                raise GeneralApiError(f"order in status '{order.status}' cannot be canceled")
            order.status = "canceled"
            order.updated_at = run.public.current_timestamp
            self._emit(
                run,
                "broker.order_canceled",
                participant_id=participant_id,
                bot_id=account.participant.bot_id,
                symbol=order.symbol,
                payload={"order_id": order_id, "canceled_by_bot": True},
            )
            return order.model_copy(deep=True)

    def account(self, run_id: str, participant_id: str) -> AccountSnapshot:
        with self._lock:
            run = self._run(run_id)
            return self._account_snapshot(run, self._account(run, participant_id))

    def publish_observation(
        self,
        run_id: str,
        participant_id: str,
        request: BotObservationRequest,
    ) -> GeneralEvent:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id)
            return self._emit(
                run,
                f"bot.{request.event_type}",
                participant_id=participant_id,
                bot_id=participant.bot_id,
                symbol=request.symbol,
                payload={
                    "decision": request.decision,
                    "reason": request.reason,
                    "confidence": str(request.confidence) if request.confidence is not None else None,
                    "metadata": request.metadata,
                    "reported_by_bot": True,
                },
            ).model_copy(deep=True)

    def publish_directive(
        self,
        run_id: str,
        participant_id: str,
        request: PublishDirectiveRequest,
    ) -> ControlDirective:
        with self._lock:
            run = self._run(run_id)
            source = self._participant(run, participant_id)
            if "risk_controller" not in source.roles:
                raise GeneralApiError("participant is not registered as a risk controller")
            for target_id in request.target_participant_ids:
                self._participant(run, target_id)
            known_bot_ids = {participant.bot_id for participant in run.participants.values()}
            unknown_bot_ids = sorted(set(request.target_bot_ids) - known_bot_ids)
            if unknown_bot_ids:
                raise GeneralApiError(f"directive targets unknown bot IDs: {', '.join(unknown_bot_ids)}")
            directive = ControlDirective(
                directive_id=f"directive-{uuid.uuid4().hex[:16]}",
                run_id=run_id,
                source_participant_id=participant_id,
                source_bot_id=source.bot_id,
                directive_type=request.directive_type,
                target_participant_ids=request.target_participant_ids,
                target_bot_ids=request.target_bot_ids,
                symbol=request.symbol,
                reason=request.reason,
                severity=request.severity,
                created_at=run.public.current_timestamp,
                expires_at=request.expires_at,
                metadata=request.metadata,
            )
            if not directive.target_participant_ids and not directive.target_bot_ids:
                raise GeneralApiError("a directive needs at least one participant or bot target")
            run.directives[directive.directive_id] = directive
            self._emit(
                run,
                "control.directive_published",
                participant_id=participant_id,
                bot_id=source.bot_id,
                symbol=directive.symbol,
                payload={"directive": directive.model_dump(mode="json"), "reported_by_bot": True},
            )
            return directive.model_copy(deep=True)

    def directives(self, run_id: str, participant_id: str) -> list[ControlDirective]:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id)
            return [
                directive.model_copy(deep=True)
                for directive in run.directives.values()
                if self._directive_targets(directive, participant)
                or directive.source_participant_id == participant_id
            ]

    def acknowledge_directive(
        self,
        run_id: str,
        participant_id: str,
        directive_id: str,
    ) -> ControlDirective:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id)
            directive = run.directives.get(directive_id)
            if directive is None:
                raise GeneralApiError(f"directive '{directive_id}' was not found")
            if not self._directive_targets(directive, participant):
                raise GeneralApiError("directive does not target this participant")
            if participant_id not in directive.acknowledged_by:
                directive.acknowledged_by.append(participant_id)
            if directive_id not in participant.acknowledged_directive_ids:
                participant.acknowledged_directive_ids.append(directive_id)
            if directive.directive_type == "halt_new_orders":
                participant.new_orders_halted = True
            elif directive.directive_type == "resume_new_orders":
                participant.new_orders_halted = False
            self._emit(
                run,
                "control.directive_acknowledged",
                participant_id=participant_id,
                bot_id=participant.bot_id,
                symbol=directive.symbol,
                payload={
                    "directive_id": directive_id,
                    "directive_type": directive.directive_type,
                    "broker_new_orders_halted": participant.new_orders_halted,
                },
            )
            return directive.model_copy(deep=True)

    def events(
        self,
        run_id: str,
        *,
        participant_id: str | None = None,
        after: int = 0,
        limit: int = 1000,
    ) -> list[GeneralEvent]:
        with self._lock:
            run = self._run(run_id)
            participant = self._participant(run, participant_id) if participant_id else None
            result = [event for event in run.events if event.sequence > after]
            if participant:
                result = [event for event in result if self._event_visible(run, event, participant)]
            return [event.model_copy(deep=True) for event in result[: max(1, min(limit, 5000))]]

    def report(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._run(run_id)
            dataset = self._dataset(run.public.dataset_id)
            participants: list[dict[str, Any]] = []
            total_orders = 0
            total_fills = 0
            for participant_id, account in run.accounts.items():
                snapshot = self._account_snapshot(run, account)
                orders = list(account.orders.values())
                fills = list(account.fills)
                total_orders += len(orders)
                total_fills += len(fills)
                participants.append(
                    {
                        "participant": account.participant.model_dump(mode="json"),
                        "account": snapshot.model_dump(mode="json"),
                        "bot_generated_order_count": len(orders),
                        "broker_fill_count": len(fills),
                        "orders": [order.model_dump(mode="json") for order in orders],
                        "fills": [fill.model_dump(mode="json") for fill in fills],
                        "pnl_exists_only_from_bot_orders": all(
                            fill.order_id in account.orders
                            and account.orders[fill.order_id].participant_id == participant_id
                            for fill in fills
                        )
                        and (snapshot.total_pnl == ZERO or bool(fills)),
                    }
                )
            return {
                "contract_version": "archive.general.report.v1",
                "run": run.public.model_dump(mode="json"),
                "dataset": dataset.summary.model_dump(mode="json"),
                "strategy_logic_in_archive": False,
                "archive_generated_order_count": 0,
                "bot_generated_order_count": total_orders,
                "broker_fill_count": total_fills,
                "participants": participants,
                "directives": [directive.model_dump(mode="json") for directive in run.directives.values()],
                "event_count": len(run.events),
                "latest_sequence": run.public.latest_sequence,
            }

    def _step(self, run: _Run) -> None:
        dataset = self._dataset(run.public.dataset_id)
        rows = dataset.bars
        if run.public.index >= len(rows):
            if run.public.loop:
                run.public.index = 0
            else:
                if run.public.state != "completed":
                    run.public.state = "completed"
                    self._emit(run, "replay.completed")
                return

        timestamp = rows[run.public.index].timestamp
        batch: list[MarketBar] = []
        while run.public.index < len(rows) and rows[run.public.index].timestamp == timestamp:
            batch.append(rows[run.public.index])
            run.public.index += 1
        run.public.current_timestamp = timestamp

        for bar in batch:
            self._match_orders(run, bar, dataset.instruments[bar.symbol])
            run.latest_bars[bar.symbol] = bar
            self._emit(
                run,
                "market.bar",
                symbol=bar.symbol,
                payload={"bar": bar.model_dump(mode="json"), "data_kind": dataset.summary.data_kind},
            )
        self._emit(run, "market.clock", payload={"timestamp": timestamp, "bar_count": len(batch)})

        if run.public.index >= len(rows) and not run.public.loop:
            run.public.state = "completed"
            self._emit(run, "replay.completed")

    def _match_orders(self, run: _Run, bar: MarketBar, spec: InstrumentSpec) -> None:
        eligible = [
            order
            for order in run.orders.values()
            if order.symbol == bar.symbol
            and order.status in {"accepted", "partially_filled"}
            and order.submitted_sequence < run.public.latest_sequence + 1
        ]
        # When one OHLC bar touches both sides of an OCO bracket, the actual
        # intrabar sequence is unknowable. Processing stops before limits makes
        # the ambiguity deterministic and adverse rather than profit-biased.
        eligible.sort(key=lambda order: {"stop": 0, "market": 1, "limit": 2}[order.order_type])
        for order in eligible:
            if order.status not in {"accepted", "partially_filled"}:
                continue
            price = self._match_price(order, bar, spec)
            if price is None:
                if order.time_in_force == "ioc":
                    order.status = "canceled"
                    order.updated_at = bar.timestamp
                    self._emit(
                        run,
                        "broker.order_canceled",
                        participant_id=order.participant_id,
                        bot_id=order.bot_id,
                        symbol=order.symbol,
                        payload={"order_id": order.order_id, "reason": "ioc_not_filled"},
                    )
                continue
            max_quantity = order.remaining_quantity
            if bar.volume > 0:
                max_quantity = min(
                    max_quantity,
                    Decimal(str(bar.volume)) * spec.max_volume_participation_pct / Decimal("100"),
                )
            if max_quantity <= ZERO:
                continue
            account = run.accounts[order.participant_id]
            rejection = self._fill_rejection(run, account, order, max_quantity, price, spec)
            if rejection:
                order.status = "rejected"
                order.rejection_reason = rejection
                order.updated_at = bar.timestamp
                self._emit(
                    run,
                    "broker.order_rejected",
                    participant_id=order.participant_id,
                    bot_id=order.bot_id,
                    symbol=order.symbol,
                    payload={"order": order.model_dump(mode="json"), "reason": rejection},
                )
                continue
            self._apply_fill(run, account, order, max_quantity, price, spec, bar.timestamp)
            if order.time_in_force == "ioc" and order.status == "partially_filled":
                order.status = "canceled"
                order.updated_at = bar.timestamp
                self._emit(
                    run,
                    "broker.order_canceled",
                    participant_id=order.participant_id,
                    bot_id=order.bot_id,
                    symbol=order.symbol,
                    payload={"order_id": order.order_id, "reason": "ioc_remainder_canceled"},
                )

    def _apply_fill(
        self,
        run: _Run,
        account: _Account,
        order: BrokerOrder,
        quantity: Decimal,
        price: Decimal,
        spec: InstrumentSpec,
        timestamp: str,
    ) -> None:
        commission = account.participant.commission_per_order if order.filled_quantity == ZERO else ZERO
        position = account.positions.setdefault(order.symbol, _Position(symbol=order.symbol))
        delta = quantity if order.side == "buy" else -quantity
        realized = self._update_position(position, delta, price, spec.multiplier)
        account.commission_paid += commission
        account.realized_pnl += realized - commission
        if spec.asset_class == "future":
            account.cash += realized - commission
        else:
            account.cash -= delta * price * spec.multiplier + commission

        order.filled_quantity += quantity
        order.remaining_quantity = max(ZERO, order.quantity - order.filled_quantity)
        order.status = "filled" if order.remaining_quantity == ZERO else "partially_filled"
        order.updated_at = timestamp
        fill_sequence = run.public.latest_sequence + 1
        fill = BrokerFill(
            fill_id=f"fill-{uuid.uuid4().hex[:16]}",
            order_id=order.order_id,
            run_id=run.public.run_id,
            participant_id=order.participant_id,
            bot_id=order.bot_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
            commission=commission,
            multiplier=spec.multiplier,
            virtual_timestamp=timestamp,
            sequence=fill_sequence,
        )
        account.fills.append(fill)
        self._emit(
            run,
            "broker.order_filled" if order.status == "filled" else "broker.order_partially_filled",
            participant_id=order.participant_id,
            bot_id=order.bot_id,
            symbol=order.symbol,
            payload={
                "order": order.model_dump(mode="json"),
                "fill": fill.model_dump(mode="json"),
                "originating_bot_order_id": order.order_id,
            },
        )
        if order.status == "filled" and order.oco_group:
            self._cancel_oco_siblings(run, order)

    def _cancel_oco_siblings(self, run: _Run, filled_order: BrokerOrder) -> None:
        for sibling in run.orders.values():
            if (
                sibling.order_id != filled_order.order_id
                and sibling.participant_id == filled_order.participant_id
                and sibling.oco_group == filled_order.oco_group
                and sibling.status in {"accepted", "partially_filled"}
            ):
                sibling.status = "canceled"
                sibling.updated_at = run.public.current_timestamp
                self._emit(
                    run,
                    "broker.order_canceled",
                    participant_id=sibling.participant_id,
                    bot_id=sibling.bot_id,
                    symbol=sibling.symbol,
                    payload={"order_id": sibling.order_id, "reason": "oco_sibling_filled"},
                )

    def _order_rejection(self, run: _Run, account: _Account, order: BrokerOrder) -> str | None:
        dataset = self._dataset(run.public.dataset_id)
        participant = account.participant
        if "trader" not in participant.roles:
            return "participant_is_not_a_trader"
        if order.symbol not in dataset.instruments:
            return "symbol_not_in_replay_dataset"
        position = account.positions.get(order.symbol)
        current_quantity = position.quantity if position else ZERO
        delta = order.quantity if order.side == "buy" else -order.quantity
        reduces = current_quantity != ZERO and (
            (current_quantity > ZERO and delta < ZERO) or (current_quantity < ZERO and delta > ZERO)
        )
        reduces_without_reversal = reduces and abs(delta) <= abs(current_quantity)
        if participant.new_orders_halted and not reduces_without_reversal:
            return "new_orders_halted_after_acknowledged_directive"
        if order.reduce_only and (not reduces or abs(delta) > abs(current_quantity)):
            return "reduce_only_order_would_increase_or_reverse_position"
        spec = dataset.instruments[order.symbol]
        if not spec.shortable and current_quantity + delta < ZERO:
            return "instrument_not_shortable"
        return None

    def _fill_rejection(
        self,
        run: _Run,
        account: _Account,
        order: BrokerOrder,
        quantity: Decimal,
        price: Decimal,
        spec: InstrumentSpec,
    ) -> str | None:
        snapshot = self._account_snapshot(run, account)
        if order.side == "buy" and spec.asset_class != "future":
            cost = quantity * price * spec.multiplier
            if cost + account.participant.commission_per_order > snapshot.buying_power:
                return "insufficient_buying_power"
        if spec.asset_class == "future":
            position = account.positions.get(order.symbol)
            current = position.quantity if position else ZERO
            delta = quantity if order.side == "buy" else -quantity
            projected_margin = abs(current + delta) * spec.initial_margin
            current_symbol_margin = abs(current) * spec.initial_margin
            if snapshot.margin_used - current_symbol_margin + projected_margin > snapshot.equity:
                return "insufficient_futures_margin"
        return None

    def _match_price(self, order: BrokerOrder, bar: MarketBar, spec: InstrumentSpec) -> Decimal | None:
        open_price = Decimal(str(bar.open))
        high = Decimal(str(bar.high))
        low = Decimal(str(bar.low))
        if order.order_type == "market":
            price = self._slipped(open_price, order.side, self._account(self._run(order.run_id), order.participant_id).participant.slippage_bps)
            return self._round_tick(price, spec.tick_size)
        if order.order_type == "limit":
            assert order.limit_price is not None
            if order.side == "buy":
                if open_price <= order.limit_price:
                    return self._round_tick(open_price, spec.tick_size)
                if low <= order.limit_price:
                    return self._round_tick(order.limit_price, spec.tick_size)
            else:
                if open_price >= order.limit_price:
                    return self._round_tick(open_price, spec.tick_size)
                if high >= order.limit_price:
                    return self._round_tick(order.limit_price, spec.tick_size)
            return None
        assert order.stop_price is not None
        if order.side == "buy" and (open_price >= order.stop_price or high >= order.stop_price):
            base = max(open_price, order.stop_price)
        elif order.side == "sell" and (open_price <= order.stop_price or low <= order.stop_price):
            base = min(open_price, order.stop_price)
        else:
            return None
        slippage = self._account(self._run(order.run_id), order.participant_id).participant.slippage_bps
        return self._round_tick(self._slipped(base, order.side, slippage), spec.tick_size)

    def _account_snapshot(self, run: _Run, account: _Account) -> AccountSnapshot:
        dataset = self._dataset(run.public.dataset_id)
        positions: list[BrokerPosition] = []
        unrealized = ZERO
        stock_market_value = ZERO
        margin_used = ZERO
        for symbol, position in account.positions.items():
            if position.quantity == ZERO:
                continue
            spec = dataset.instruments[symbol]
            bar = run.latest_bars.get(symbol)
            market_price = Decimal(str(bar.close)) if bar else position.average_entry_price
            position_unrealized = (
                (market_price - position.average_entry_price) * position.quantity * spec.multiplier
            )
            unrealized += position_unrealized
            if spec.asset_class == "future":
                margin_used += abs(position.quantity) * spec.initial_margin
            else:
                stock_market_value += position.quantity * market_price * spec.multiplier
            positions.append(
                BrokerPosition(
                    symbol=symbol,
                    asset_class=spec.asset_class,
                    quantity=position.quantity,
                    average_entry_price=position.average_entry_price,
                    market_price=market_price,
                    multiplier=spec.multiplier,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position_unrealized,
                )
            )
        equity = account.cash + stock_market_value + unrealized
        buying_power = max(ZERO, account.cash - margin_used)
        total_pnl = equity - account.participant.starting_cash
        return_pct = (
            total_pnl / account.participant.starting_cash * Decimal("100")
            if account.participant.starting_cash
            else ZERO
        )
        return AccountSnapshot(
            participant_id=account.participant.participant_id,
            bot_id=account.participant.bot_id,
            starting_cash=account.participant.starting_cash,
            cash=account.cash,
            equity=equity,
            buying_power=buying_power,
            margin_used=margin_used,
            realized_pnl=account.realized_pnl,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            return_pct=return_pct,
            commission_paid=account.commission_paid,
            positions=positions,
            order_count=len(account.orders),
            fill_count=len(account.fills),
            new_orders_halted=account.participant.new_orders_halted,
        )

    @staticmethod
    def _update_position(
        position: _Position,
        delta: Decimal,
        price: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        old = position.quantity
        realized = ZERO
        if old == ZERO or (old > ZERO and delta > ZERO) or (old < ZERO and delta < ZERO):
            combined = abs(old) + abs(delta)
            position.average_entry_price = (
                (position.average_entry_price * abs(old) + price * abs(delta)) / combined
            )
            position.quantity = old + delta
            return realized

        closing = min(abs(old), abs(delta))
        if old > ZERO:
            realized = (price - position.average_entry_price) * closing * multiplier
        else:
            realized = (position.average_entry_price - price) * closing * multiplier
        new_quantity = old + delta
        if new_quantity == ZERO:
            position.average_entry_price = ZERO
        elif (new_quantity > ZERO) != (old > ZERO):
            position.average_entry_price = price
        position.quantity = new_quantity
        position.realized_pnl += realized
        return realized

    def _emit(
        self,
        run: _Run,
        event_type: str,
        *,
        participant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GeneralEvent:
        run.public.latest_sequence += 1
        event = GeneralEvent(
            sequence=run.public.latest_sequence,
            run_id=run.public.run_id,
            event_type=event_type,
            virtual_timestamp=run.public.current_timestamp,
            participant_id=participant_id,
            bot_id=bot_id,
            symbol=symbol,
            payload=payload or {},
        )
        run.events.append(event)
        return event

    def _event_visible(self, run: _Run, event: GeneralEvent, participant: Participant) -> bool:
        if event.event_type == "market.bar":
            return event.symbol in participant.subscribed_symbols
        if event.event_type == "control.directive_published":
            raw = event.payload.get("directive", {})
            directive_id = raw.get("directive_id")
            directive = run.directives.get(str(directive_id))
            return bool(
                directive
                and (
                    directive.source_participant_id == participant.participant_id
                    or self._directive_targets(directive, participant)
                )
            )
        if event.event_type == "control.directive_acknowledged":
            directive = run.directives.get(str(event.payload.get("directive_id", "")))
            return bool(
                event.participant_id == participant.participant_id
                or (directive and directive.source_participant_id == participant.participant_id)
            )
        if event.participant_id is not None:
            return event.participant_id == participant.participant_id
        return True

    @staticmethod
    def _directive_targets(directive: ControlDirective, participant: Participant) -> bool:
        return (
            participant.participant_id in directive.target_participant_ids
            or participant.bot_id in directive.target_bot_ids
        )

    @staticmethod
    def _slipped(price: Decimal, side: str, slippage_bps: Decimal) -> Decimal:
        adjustment = slippage_bps / Decimal("10000")
        return price * (Decimal("1") + adjustment if side == "buy" else Decimal("1") - adjustment)

    @staticmethod
    def _round_tick(price: Decimal, tick_size: Decimal) -> Decimal:
        ticks = (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return ticks * tick_size

    def _dataset(self, dataset_id: str) -> _Dataset:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise GeneralApiError(f"dataset '{dataset_id}' was not found")
        return dataset

    def _run(self, run_id: str) -> _Run:
        run = self._runs.get(run_id)
        if run is None:
            raise GeneralApiError(f"replay run '{run_id}' was not found")
        return run

    @staticmethod
    def _participant(run: _Run, participant_id: str | None) -> Participant:
        if participant_id is None or participant_id not in run.participants:
            raise GeneralApiError(f"participant '{participant_id}' was not found")
        return run.participants[participant_id]

    @staticmethod
    def _account(run: _Run, participant_id: str) -> _Account:
        account = run.accounts.get(participant_id)
        if account is None:
            raise GeneralApiError(f"participant '{participant_id}' was not found")
        return account
