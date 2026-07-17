from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sentinel_archive.backtesting.models import (
    AccountSnapshot,
    BacktestOrderIntent,
    DerivativesMetrics,
    DerivativesReport,
    DerivativesRunRequest,
    ExecutionEvent,
    MarketPriceBar,
)


@dataclass
class _State:
    wallet: float
    position: float = 0.0
    entry_price: float = 0.0
    entry_timestamp: str = ""
    initial_margin: float = 0.0
    realized_gross: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    slippage: float = 0.0
    commissions: float = 0.0
    exchange_fees: float = 0.0
    liquidation_fees: float = 0.0
    high_water: float = 0.0
    low_water: float = 0.0
    debt: float = 0.0


def run_derivatives_backtest(request: DerivativesRunRequest) -> DerivativesReport:
    _validate_request(request)
    fingerprint = _fingerprint(request.model_dump(mode="json"))
    run_id = f"drv-{fingerprint[:20]}"
    if not request.bars:
        return _empty_report(request, run_id, fingerprint, ["thin_data"])

    bars = sorted(request.bars, key=lambda item: (item.timestamp, item.symbol))
    orders = _normalized_orders(request, bars)
    state = _State(wallet=request.starting_equity)
    events: list[ExecutionEvent] = []
    curve: list[AccountSnapshot] = []
    warnings: set[str] = set()
    pending = list(orders)
    funding_events = sorted(request.funding_events, key=lambda item: item.timestamp)
    funding_index = 0

    if request.contract.inverse:
        warnings.add("inverse_contract_uses_linear_pnl_approximation")
    if request.leverage > request.contract.maximum_leverage:
        warnings.add("leverage_above_contract_limit")

    for bar_index, bar in enumerate(bars):
        due, pending = _due_orders(pending, bar, bar_index, request.execution_model.latency_bars, bars)
        for order in due:
            retry = _process_order(order, bar, request, state, events, warnings)
            if retry is not None:
                pending.append(retry)

        while funding_index < len(funding_events) and funding_events[funding_index].timestamp <= bar.timestamp:
            funding = funding_events[funding_index]
            _apply_funding(
                funding.rate,
                funding.mark_price or _mark(bar, request),
                funding.timestamp,
                request,
                state,
                events,
            )
            funding_index += 1

        if state.position:
            _evaluate_position_bar(bar, request, state, events, warnings)

        curve.append(_snapshot(bar.timestamp, _mark(bar, request), request, state))

    for order in pending:
        _event(
            events,
            bars[-1].timestamp,
            "unfilled",
            order=order,
            remaining=order.quantity,
            reason="end_of_dataset",
        )

    if state.position and request.close_final_position:
        _close_position(
            bars[-1],
            bars[-1].close,
            "final_close",
            request,
            state,
            events,
            order_id="archive-final-close",
        )
        curve.append(_snapshot(bars[-1].timestamp, bars[-1].close, request, state))

    if state.position:
        warnings.add("open_position_at_end")
    if state.wallet < 0 or state.debt > 0:
        warnings.add("potential_debt")

    metrics = _metrics(request, state, curve, events, warnings)
    return DerivativesReport(
        run_id=run_id,
        fingerprint=fingerprint,
        bot_id=request.bot_id,
        symbol=request.symbol.upper(),
        contract=request.contract,
        metrics=metrics,
        executions=events,
        account_curve=curve,
        warnings=sorted(warnings),
        assumptions=request.model_dump(mode="json", exclude={"bars", "funding_events", "orders"}),
    )


def _validate_request(request: DerivativesRunRequest) -> None:
    if request.leverage > request.contract.maximum_leverage:
        raise ValueError(
            f"requested leverage {request.leverage:g} exceeds contract maximum {request.contract.maximum_leverage:g}"
        )
    if request.contract.maintenance_margin_rate >= request.contract.initial_margin_rate:
        raise ValueError("maintenance margin must be lower than initial margin")
    if request.contract.symbol.upper() != request.symbol.upper():
        raise ValueError("request symbol and contract symbol must match")


def _normalized_orders(request: DerivativesRunRequest, bars: list[MarketPriceBar]) -> list[BacktestOrderIntent]:
    if request.orders:
        return sorted(request.orders, key=lambda item: (item.timestamp or bars[0].timestamp, item.order_id))
    return [
        BacktestOrderIntent(
            order_id="archive-entry",
            timestamp=bars[0].timestamp,
            action="open",
            side=request.side,
            order_type="market",
            quantity=request.quantity,
            time_in_force=request.execution_model.market_order_time_in_force,
        )
    ]


def _due_orders(
    orders: list[BacktestOrderIntent],
    bar: MarketPriceBar,
    bar_index: int,
    latency_bars: int,
    bars: list[MarketPriceBar],
) -> tuple[list[BacktestOrderIntent], list[BacktestOrderIntent]]:
    due: list[BacktestOrderIntent] = []
    pending: list[BacktestOrderIntent] = []
    for order in orders:
        target = order.timestamp or bars[0].timestamp
        target_index = next((index for index, item in enumerate(bars) if item.timestamp >= target), len(bars))
        if bar_index >= target_index + latency_bars:
            due.append(order)
        else:
            pending.append(order)
    return due, pending


def _process_order(
    order: BacktestOrderIntent,
    bar: MarketPriceBar,
    request: DerivativesRunRequest,
    state: _State,
    events: list[ExecutionEvent],
    warnings: set[str],
) -> BacktestOrderIntent | None:
    if order.action == "cancel":
        _event(events, bar.timestamp, "cancel_acknowledged", order=order, reason="simulation_cancel")
        return None
    if order.action == "amend":
        _event(events, bar.timestamp, "amend_acknowledged", order=order, reason="simulation_amend")
        return None

    if order.order_type in {"limit", "stop_limit"} and order.limit_price is None:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="missing_limit_price")
        return None
    if order.order_type in {"stop", "stop_limit"} and order.stop_price is None:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="missing_stop_price")
        return None
    if order.order_type == "trailing_stop" and order.trailing_percent is None:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="missing_trailing_percent")
        return None
    if order.action == "close" and not state.position:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="position_not_found")
        return None

    trigger_price = _order_trigger_price(order, bar, state)
    if trigger_price is None:
        if order.time_in_force == "GTC":
            return order
        _event(events, bar.timestamp, "unfilled", order=order, remaining=order.quantity, reason="price_not_reached")
        return None

    if order.action == "close":
        _close_position(bar, trigger_price, "bot_close", request, state, events, order_id=order.order_id)
        return None

    if state.position:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="position_already_open")
        return None
    if order.reduce_only:
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="reduce_only_without_position")
        return None

    quantity, remaining, liquidity_reason = _executable_quantity(order, bar, request)
    if quantity <= 0:
        if order.time_in_force == "GTC" and liquidity_reason == "volume_unavailable":
            return order
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason=liquidity_reason)
        return None
    if remaining and (order.time_in_force == "FOK" or not request.execution_model.allow_partial_fills):
        _event(events, bar.timestamp, "rejected", order=order, remaining=order.quantity, reason="insufficient_liquidity")
        return None

    is_buy = order.side == "long"
    fill_price, slippage = _execution_price(trigger_price, bar, is_buy, request, quantity)
    notional = _notional(fill_price, quantity, request)
    margin_rate = max(request.contract.initial_margin_rate, 1 / request.leverage)
    initial_margin = notional * margin_rate
    entry_costs = _costs(fill_price, quantity, request, is_maker=order.order_type == "limit")
    if initial_margin + entry_costs[0] > state.wallet:
        _event(
            events,
            bar.timestamp,
            "rejected",
            order=order,
            remaining=order.quantity,
            reason="insufficient_initial_margin",
            metadata={"required_margin": initial_margin, "available_equity": state.wallet},
        )
        return None

    state.position = quantity if order.side == "long" else -quantity
    state.entry_price = fill_price
    state.entry_timestamp = bar.timestamp
    state.initial_margin = initial_margin
    state.high_water = fill_price
    state.low_water = fill_price
    state.wallet -= entry_costs[0]
    _record_costs(state, entry_costs, slippage)
    event_type = "partial_fill" if remaining else "filled"
    _event(
        events,
        bar.timestamp,
        event_type,
        order=order,
        filled=quantity,
        remaining=remaining,
        price=fill_price,
        fee=entry_costs[0],
        reason=liquidity_reason if remaining else None,
        metadata={"initial_margin": initial_margin, "notional": notional, "slippage": slippage},
    )
    if remaining:
        warnings.add("partial_fill")
        if order.time_in_force == "GTC":
            warnings.add("gtc_remainder_cancelled_single_position_model")
            _event(events, bar.timestamp, "unfilled", order=order, remaining=remaining, reason="gtc_remainder_cancelled_single_position_model")
            return None
        _event(events, bar.timestamp, "unfilled", order=order, remaining=remaining, reason="ioc_remainder_cancelled")
    return None


def _order_trigger_price(order: BacktestOrderIntent, bar: MarketPriceBar, state: _State) -> float | None:
    if order.order_type == "market":
        return bar.open
    if order.order_type == "limit":
        if order.limit_price is None:
            return None
        if order.side == "long" and bar.low <= order.limit_price:
            return min(bar.open, order.limit_price)
        if order.side == "short" and bar.high >= order.limit_price:
            return max(bar.open, order.limit_price)
        return None
    if order.order_type == "stop":
        if order.stop_price is None:
            return None
        if order.side == "long" and bar.high >= order.stop_price:
            return max(bar.open, order.stop_price)
        if order.side == "short" and bar.low <= order.stop_price:
            return min(bar.open, order.stop_price)
        return None
    if order.order_type == "stop_limit":
        if order.stop_price is None or order.limit_price is None:
            return None
        if order.side == "long" and bar.high >= order.stop_price and bar.low <= order.limit_price:
            return min(max(bar.open, order.stop_price), order.limit_price)
        if order.side == "short" and bar.low <= order.stop_price and bar.high >= order.limit_price:
            return max(min(bar.open, order.stop_price), order.limit_price)
        return None
    if order.order_type == "trailing_stop" and state.position:
        distance = order.trailing_percent or 0
        if state.position > 0:
            trail = state.high_water * (1 - distance / 100)
            return min(bar.open, trail) if bar.low <= trail else None
        trail = state.low_water * (1 + distance / 100)
        return max(bar.open, trail) if bar.high >= trail else None
    return None


def _executable_quantity(
    order: BacktestOrderIntent, bar: MarketPriceBar, request: DerivativesRunRequest
) -> tuple[float, float, str | None]:
    step = request.contract.quantity_step
    requested = _floor_step(order.quantity, step)
    if requested < request.contract.minimum_quantity:
        return 0.0, order.quantity, "below_minimum_quantity"
    if request.contract.maximum_quantity is not None and requested > request.contract.maximum_quantity:
        return 0.0, order.quantity, "above_maximum_quantity"
    if bar.volume <= 0:
        if request.execution_model.reject_when_volume_missing:
            return 0.0, requested, "volume_unavailable"
        return requested, max(0.0, order.quantity - requested), None
    available = _floor_step(bar.volume * request.execution_model.maximum_volume_participation, step)
    filled = min(requested, available)
    remaining = max(0.0, requested - filled)
    return filled, remaining, "liquidity_limited" if remaining else None


def _evaluate_position_bar(
    bar: MarketPriceBar,
    request: DerivativesRunRequest,
    state: _State,
    events: list[ExecutionEvent],
    warnings: set[str],
) -> None:
    side = "long" if state.position > 0 else "short"
    liquidation = _liquidation_price(request, state)
    stop = _stop_price(request, state)
    target = _target_price(request, state)
    prior_trail = _trailing_price(request, state)

    if _gap_crossed(bar.open, liquidation, side, adverse=True):
        warnings.add("liquidated")
        _close_position(bar, bar.open, "liquidation_gap", request, state, events, order_id="liquidation", liquidated=True)
        return
    if stop is not None and _gap_crossed(bar.open, stop, side, adverse=True):
        price = bar.open if request.execution_model.gap_stop_fill == "open" else stop
        warnings.add("gap_through_stop")
        _close_position(bar, price, "stop_gap", request, state, events, order_id="auto-stop")
        _cancel_oco(bar.timestamp, events, "auto-bracket", "auto-stop")
        return

    state.high_water = max(state.high_water, bar.high)
    state.low_water = min(state.low_water, bar.low)
    updated_trail = _trailing_price(request, state)
    trail = prior_trail if request.execution_model.same_bar_policy == "adverse_first" else updated_trail

    candidates: list[tuple[str, float, str]] = []
    if _bar_crossed(bar, liquidation, side, adverse=True):
        candidates.append(("liquidation", liquidation, "adverse"))
    if stop is not None and _bar_crossed(bar, stop, side, adverse=True):
        candidates.append(("stop_loss", stop, "adverse"))
    if trail is not None and _bar_crossed(bar, trail, side, adverse=True):
        candidates.append(("trailing_stop", trail, "adverse"))
    if target is not None and _bar_crossed(bar, target, side, adverse=False):
        candidates.append(("take_profit", target, "favorable"))
    if not candidates:
        return

    if len(candidates) > 1:
        warnings.add("same_bar_ambiguity")
        _event(
            events,
            bar.timestamp,
            "same_bar_ambiguity",
            reason=request.execution_model.same_bar_policy,
            metadata={"candidates": [{"reason": reason, "price": price} for reason, price, _ in candidates]},
        )
        if request.execution_model.same_bar_policy == "reject_ambiguous":
            warnings.add("ambiguous_execution_deferred")
            return
    chosen = _choose_candidate(candidates, side, request.execution_model.same_bar_policy)
    reason, price, _ = chosen
    liquidated = reason == "liquidation"
    if liquidated:
        warnings.add("liquidated")
    _close_position(bar, price, reason, request, state, events, order_id=f"auto-{reason}", liquidated=liquidated)
    _cancel_oco(bar.timestamp, events, "auto-bracket", f"auto-{reason}")


def _choose_candidate(candidates: list[tuple[str, float, str]], side: str, policy: str) -> tuple[str, float, str]:
    adverse = [item for item in candidates if item[2] == "adverse"]
    favorable = [item for item in candidates if item[2] == "favorable"]
    if policy in {"adverse_first", "reject_ambiguous"}:
        return _nearest_adverse(adverse, side) if adverse else favorable[0]
    if policy == "favorable_first":
        return favorable[0] if favorable else _nearest_adverse(adverse, side)
    if policy == "open_high_low_close":
        if side == "long":
            return favorable[0] if favorable else _nearest_adverse(adverse, side)
        return _nearest_adverse(adverse, side) if adverse else favorable[0]
    if side == "long":
        return _nearest_adverse(adverse, side) if adverse else favorable[0]
    return favorable[0] if favorable else _nearest_adverse(adverse, side)


def _nearest_adverse(candidates: list[tuple[str, float, str]], side: str) -> tuple[str, float, str]:
    if side == "long":
        return max(candidates, key=lambda item: item[1])
    return min(candidates, key=lambda item: item[1])


def _close_position(
    bar: MarketPriceBar,
    raw_price: float,
    reason: str,
    request: DerivativesRunRequest,
    state: _State,
    events: list[ExecutionEvent],
    *,
    order_id: str,
    liquidated: bool = False,
) -> None:
    if not state.position:
        return
    side = "long" if state.position > 0 else "short"
    quantity = abs(state.position)
    is_buy = side == "short"
    fill_price, slippage = _execution_price(raw_price, bar, is_buy, request, quantity)
    gross = (fill_price - state.entry_price) * state.position * request.contract.contract_multiplier
    costs = _costs(fill_price, quantity, request, is_maker=False)
    liquidation_fee = 0.0
    if liquidated:
        liquidation_fee = _notional(fill_price, quantity, request) * request.cost_model.liquidation_fee_bps / 10000
    total_exit_cost = costs[0] + liquidation_fee
    state.wallet += gross - total_exit_cost
    state.realized_gross += gross
    state.liquidation_fees += liquidation_fee
    _record_costs(state, costs, slippage)
    state.debt = max(state.debt, max(0.0, -state.wallet))
    _event(
        events,
        bar.timestamp,
        "liquidated" if liquidated else "position_closed",
        order=BacktestOrderIntent(
            order_id=order_id,
            timestamp=bar.timestamp,
            action="close",
            side=side,
            order_type="market",
            quantity=quantity,
            reduce_only=True,
            oco_group="auto-bracket" if reason not in {"bot_close", "final_close"} else None,
        ),
        filled=quantity,
        price=fill_price,
        fee=total_exit_cost,
        reason=reason,
        metadata={"gross_pnl": gross, "slippage": slippage, "liquidation_fee": liquidation_fee},
    )
    state.position = 0.0
    state.entry_price = 0.0
    state.entry_timestamp = ""
    state.initial_margin = 0.0
    state.high_water = 0.0
    state.low_water = 0.0


def _apply_funding(
    rate: float,
    mark_price: float,
    timestamp: str,
    request: DerivativesRunRequest,
    state: _State,
    events: list[ExecutionEvent],
) -> None:
    if not state.position:
        return
    if state.entry_timestamp and timestamp < state.entry_timestamp:
        return
    notional = _notional(mark_price, abs(state.position), request)
    payment = notional * rate
    signed_payment = -payment if state.position > 0 else payment
    state.wallet += signed_payment
    state.funding -= signed_payment
    _event(
        events,
        timestamp,
        "funding",
        side="long" if state.position > 0 else "short",
        price=mark_price,
        fee=max(0.0, -signed_payment),
        reason="long_pays_positive_rate" if rate >= 0 else "short_pays_negative_rate",
        metadata={"rate": rate, "wallet_delta": signed_payment, "notional": notional},
    )


def _execution_price(
    raw_price: float,
    bar: MarketPriceBar,
    is_buy: bool,
    request: DerivativesRunRequest,
    quantity: float,
) -> tuple[float, float]:
    if is_buy and bar.ask:
        spread_price = max(raw_price, bar.ask)
    elif not is_buy and bar.bid:
        spread_price = min(raw_price, bar.bid)
    else:
        half_spread = raw_price * request.cost_model.spread_bps / 20000
        spread_price = raw_price + half_spread if is_buy else raw_price - half_spread
    participation = quantity / bar.volume if bar.volume > 0 else 0.0
    impact_multiplier = 1 + min(5.0, participation / max(request.execution_model.maximum_volume_participation, 1e-9))
    slip = spread_price * request.cost_model.slippage_bps / 10000 * impact_multiplier
    unrounded = spread_price + slip if is_buy else spread_price - slip
    price = _round_tick(unrounded, request.contract.tick_size, up=is_buy)
    return price, abs(price - raw_price) * quantity * request.contract.contract_multiplier


def _costs(price: float, quantity: float, request: DerivativesRunRequest, *, is_maker: bool) -> tuple[float, float, float]:
    rate = request.cost_model.maker_fee_bps if is_maker else request.cost_model.taker_fee_bps
    if rate is None:
        rate = request.cost_model.fee_bps
    notional_fee = _notional(price, quantity, request) * rate / 10000
    commission = request.cost_model.commission_per_trade + request.cost_model.commission_per_contract * quantity
    exchange_fee = request.cost_model.exchange_fee_per_contract * quantity
    return notional_fee + commission + exchange_fee, commission, exchange_fee


def _record_costs(state: _State, costs: tuple[float, float, float], slippage: float) -> None:
    state.fees += costs[0]
    state.commissions += costs[1]
    state.exchange_fees += costs[2]
    state.slippage += slippage


def _liquidation_price(request: DerivativesRunRequest, state: _State) -> float:
    quantity_value = abs(state.position) * request.contract.contract_multiplier
    if quantity_value <= 0:
        return math.inf
    collateral = state.initial_margin if request.margin_mode == "isolated" else max(0.0, state.wallet)
    maintenance = request.contract.maintenance_margin_rate
    if state.position > 0:
        numerator = state.entry_price * quantity_value - collateral
        return max(request.contract.tick_size, numerator / (quantity_value * max(1e-9, 1 - maintenance)))
    numerator = collateral + state.entry_price * quantity_value
    return numerator / (quantity_value * (1 + maintenance))


def _stop_price(request: DerivativesRunRequest, state: _State) -> float | None:
    if request.stop_loss_pct is None:
        return None
    distance = state.entry_price * request.stop_loss_pct / 100
    return state.entry_price - distance if state.position > 0 else state.entry_price + distance


def _target_price(request: DerivativesRunRequest, state: _State) -> float | None:
    if request.take_profit_pct is None:
        return None
    distance = state.entry_price * request.take_profit_pct / 100
    return state.entry_price + distance if state.position > 0 else state.entry_price - distance


def _trailing_price(request: DerivativesRunRequest, state: _State) -> float | None:
    if request.trailing_stop_pct is None:
        return None
    if state.position > 0:
        return state.high_water * (1 - request.trailing_stop_pct / 100)
    return state.low_water * (1 + request.trailing_stop_pct / 100)


def _bar_crossed(bar: MarketPriceBar, price: float | None, side: str, *, adverse: bool) -> bool:
    if price is None or not math.isfinite(price):
        return False
    if side == "long":
        return bar.low <= price if adverse else bar.high >= price
    return bar.high >= price if adverse else bar.low <= price


def _gap_crossed(open_price: float, price: float | None, side: str, *, adverse: bool) -> bool:
    if price is None or not math.isfinite(price):
        return False
    if side == "long":
        return open_price <= price if adverse else open_price >= price
    return open_price >= price if adverse else open_price <= price


def _snapshot(timestamp: str, mark: float, request: DerivativesRunRequest, state: _State) -> AccountSnapshot:
    unrealized = (mark - state.entry_price) * state.position * request.contract.contract_multiplier if state.position else 0.0
    notional = _notional(mark, abs(state.position), request) if state.position else 0.0
    maintenance = notional * request.contract.maintenance_margin_rate
    equity = state.wallet + unrealized
    used_margin = state.initial_margin if state.position else 0.0
    return AccountSnapshot(
        timestamp=timestamp,
        cash=state.wallet,
        equity=equity,
        used_margin=used_margin,
        maintenance_margin=maintenance,
        available_margin=equity - used_margin,
        position_quantity=state.position,
        mark_price=mark,
        unrealized_pnl=unrealized,
        realized_pnl=state.realized_gross - state.fees - state.funding - state.liquidation_fees,
        funding=state.funding,
        fees=state.fees + state.liquidation_fees,
        debt=max(0.0, -equity),
    )


def _metrics(
    request: DerivativesRunRequest,
    state: _State,
    curve: list[AccountSnapshot],
    events: list[ExecutionEvent],
    warnings: Iterable[str],
) -> DerivativesMetrics:
    equities = [request.starting_equity, *(point.equity for point in curve)]
    ending = equities[-1]
    safety_flags = sorted(set(warnings))
    if any(point.equity <= point.maintenance_margin and point.position_quantity for point in curve):
        safety_flags.append("maintenance_margin_breach")
    safety_flags = sorted(set(safety_flags))
    score = 100.0
    penalties = {
        "liquidated": 70,
        "potential_debt": 80,
        "maintenance_margin_breach": 50,
        "same_bar_ambiguity": 10,
        "gap_through_stop": 20,
        "partial_fill": 5,
        "open_position_at_end": 10,
        "inverse_contract_uses_linear_pnl_approximation": 25,
    }
    for flag in safety_flags:
        score -= penalties.get(flag, 5)
    event_types = [event.event_type for event in events]
    return DerivativesMetrics(
        starting_equity=request.starting_equity,
        ending_equity=ending,
        net_pnl=ending - request.starting_equity,
        realized_pnl=state.wallet - request.starting_equity,
        maximum_equity=max(equities),
        minimum_equity=min(equities),
        maximum_drawdown_pct=_max_drawdown(equities),
        total_fees=state.fees + state.liquidation_fees,
        total_funding=state.funding,
        total_slippage=state.slippage,
        total_commissions=state.commissions,
        total_exchange_fees=state.exchange_fees,
        total_liquidation_fees=state.liquidation_fees,
        order_count=sum(1 for event in events if event.order_id and event.event_type not in {"funding", "same_bar_ambiguity", "oco_cancelled"}),
        fill_count=event_types.count("filled") + event_types.count("partial_fill") + event_types.count("position_closed") + event_types.count("liquidated"),
        partial_fill_count=event_types.count("partial_fill"),
        rejection_count=event_types.count("rejected"),
        unfilled_count=event_types.count("unfilled"),
        liquidation_count=event_types.count("liquidated"),
        margin_call_count=sum(1 for point in curve if point.position_quantity and point.equity <= point.maintenance_margin),
        potential_debt=max(state.debt, max((point.debt for point in curve), default=0.0)),
        safety_score=max(0.0, min(100.0, score)),
        safety_flags=safety_flags,
    )


def _empty_report(
    request: DerivativesRunRequest, run_id: str, fingerprint: str, warnings: list[str]
) -> DerivativesReport:
    return DerivativesReport(
        run_id=run_id,
        fingerprint=fingerprint,
        bot_id=request.bot_id,
        symbol=request.symbol.upper(),
        contract=request.contract,
        metrics=DerivativesMetrics(
            starting_equity=request.starting_equity,
            ending_equity=request.starting_equity,
            net_pnl=0,
            realized_pnl=0,
            maximum_equity=request.starting_equity,
            minimum_equity=request.starting_equity,
            maximum_drawdown_pct=0,
            total_fees=0,
            total_funding=0,
            total_slippage=0,
            total_commissions=0,
            total_exchange_fees=0,
            total_liquidation_fees=0,
            order_count=0,
            fill_count=0,
            partial_fill_count=0,
            rejection_count=0,
            unfilled_count=0,
            liquidation_count=0,
            margin_call_count=0,
            potential_debt=0,
            safety_score=60,
            safety_flags=warnings,
        ),
        warnings=warnings,
    )


def _cancel_oco(timestamp: str, events: list[ExecutionEvent], group: str, winner: str) -> None:
    _event(
        events,
        timestamp,
        "oco_cancelled",
        reason="sibling_filled",
        oco_group=group,
        metadata={"winning_order_id": winner},
    )


def _event(
    events: list[ExecutionEvent],
    timestamp: str,
    event_type: str,
    *,
    order: BacktestOrderIntent | None = None,
    side: str | None = None,
    filled: float = 0.0,
    remaining: float = 0.0,
    price: float | None = None,
    fee: float = 0.0,
    reason: str | None = None,
    oco_group: str | None = None,
    metadata: dict | None = None,
) -> None:
    events.append(
        ExecutionEvent(
            sequence=len(events) + 1,
            timestamp=timestamp,
            event_type=event_type,
            order_id=order.order_id if order else None,
            side=(order.side if order else side),  # type: ignore[arg-type]
            requested_quantity=order.quantity if order else 0.0,
            filled_quantity=filled,
            remaining_quantity=remaining,
            price=price,
            fee=fee,
            reason=reason,
            oco_group=order.oco_group if order else oco_group,
            metadata=metadata or {},
        )
    )


def _mark(bar: MarketPriceBar, request: DerivativesRunRequest) -> float:
    if request.execution_model.price_reference == "mark" and bar.mark_price:
        return bar.mark_price
    if request.execution_model.price_reference == "index" and bar.index_price:
        return bar.index_price
    return bar.close


def _notional(price: float, quantity: float, request: DerivativesRunRequest) -> float:
    return abs(price * quantity * request.contract.contract_multiplier)


def _round_tick(value: float, tick: float, *, up: bool) -> float:
    units = value / tick
    rounded = math.ceil(units - 1e-12) if up else math.floor(units + 1e-12)
    return rounded * tick


def _floor_step(value: float, step: float) -> float:
    return math.floor(value / step + 1e-12) * step


def _max_drawdown(equities: list[float]) -> float:
    peak = equities[0] if equities else 0.0
    maximum = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100)
    return maximum


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
