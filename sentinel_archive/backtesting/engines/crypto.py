from __future__ import annotations

from sentinel_archive.backtesting.metrics import summarize_trades
from sentinel_archive.backtesting.models import BacktestReport, BacktestRunRequest, BacktestTrade, MarketPriceBar


def run_crypto_backtest(request: BacktestRunRequest) -> BacktestReport:
    if not request.bars:
        return _empty_report(request, ["thin_data"])

    entry_bar = request.bars[0]
    entry_price = entry_bar.open
    entry_fill = _apply_slippage(entry_price, request.cost_model.slippage_bps, request.side, is_entry=True)
    stop_price = _stop_price(entry_fill, request)
    target_price = _target_price(entry_fill, request)
    warnings = _liquidation_warnings(entry_fill, stop_price, request)
    funding = 0.0
    slippage_cost = abs(entry_fill - entry_price) * request.quantity
    mae = 0.0
    mfe = 0.0
    exit_bar = request.bars[-1]
    exit_price = exit_bar.close
    exit_reason = "final_close"
    did_exit = False
    equity_curve = [request.starting_equity]

    for bar in request.bars:
        mae = min(mae, _adverse_excursion(entry_fill, bar, request))
        mfe = max(mfe, _favorable_excursion(entry_fill, bar, request))
        funding += abs(entry_fill * request.quantity * request.leverage) * request.cost_model.funding_bps_per_step / 10000
        current_unrealized = _gross_pnl(entry_fill, bar.close, request.side, request.quantity) - funding
        equity_curve.append(request.starting_equity + current_unrealized)

        exit_candidate = _adverse_first_exit(bar, stop_price, target_price, request)
        if exit_candidate:
            exit_price, exit_reason = exit_candidate
            exit_bar = bar
            did_exit = True
            break

    if not did_exit and not request.close_final_position:
        return _empty_report(request, warnings)

    exit_fill = _apply_slippage(exit_price, request.cost_model.slippage_bps, request.side, is_entry=False)
    slippage_cost += abs(exit_fill - exit_price) * request.quantity
    fees = _fees(entry_fill, exit_fill, request)
    pnl = _gross_pnl(entry_fill, exit_fill, request.side, request.quantity) - fees - funding
    trade = BacktestTrade(
        symbol=request.symbol.upper(),
        side=request.side,
        quantity=request.quantity,
        entry_time=entry_bar.timestamp,
        entry_price=entry_fill,
        exit_time=exit_bar.timestamp,
        exit_price=exit_fill,
        pnl=pnl,
        fees=fees,
        mae=mae,
        mfe=mfe,
        exit_reason=exit_reason,
    )
    ending_equity = request.starting_equity + pnl
    equity_curve.append(ending_equity)
    metrics = summarize_trades(
        trades=[trade],
        starting_equity=request.starting_equity,
        ending_equity=ending_equity,
        equity_curve=equity_curve,
        warnings=warnings,
        slippage=slippage_cost,
        funding=funding,
    )
    return BacktestReport(
        asset_class="crypto",
        symbol=request.symbol.upper(),
        metrics=metrics,
        trades=[trade],
        warnings=warnings,
        assumptions=request.model_dump(mode="json", exclude={"bars", "option_alerts", "option_quotes"}),
    )


def _empty_report(request: BacktestRunRequest, warnings: list[str]) -> BacktestReport:
    metrics = summarize_trades(
        trades=[],
        starting_equity=request.starting_equity,
        ending_equity=request.starting_equity,
        equity_curve=[request.starting_equity],
        warnings=warnings,
    )
    return BacktestReport(asset_class="crypto", symbol=request.symbol.upper(), metrics=metrics, warnings=warnings, assumptions={})


def _apply_slippage(price: float, bps: float, side: str, *, is_entry: bool) -> float:
    adjustment = price * bps / 10000
    if side == "long":
        return price + adjustment if is_entry else price - adjustment
    return price - adjustment if is_entry else price + adjustment


def _stop_price(entry_price: float, request: BacktestRunRequest) -> float | None:
    if request.stop_loss_pct is None:
        return None
    amount = entry_price * request.stop_loss_pct / 100
    return entry_price - amount if request.side == "long" else entry_price + amount


def _target_price(entry_price: float, request: BacktestRunRequest) -> float | None:
    if request.take_profit_pct is None:
        return None
    amount = entry_price * request.take_profit_pct / 100
    return entry_price + amount if request.side == "long" else entry_price - amount


def _liquidation_warnings(entry_price: float, stop_price: float | None, request: BacktestRunRequest) -> list[str]:
    if request.leverage <= 1 or stop_price is None:
        return []
    if request.side == "long":
        liquidation_price = entry_price * (1 - 1 / request.leverage)
        return ["liquidation_before_stop"] if liquidation_price >= stop_price else []
    liquidation_price = entry_price * (1 + 1 / request.leverage)
    return ["liquidation_before_stop"] if liquidation_price <= stop_price else []


def _adverse_first_exit(
    bar: MarketPriceBar,
    stop_price: float | None,
    target_price: float | None,
    request: BacktestRunRequest,
) -> tuple[float, str] | None:
    if request.side == "long":
        if stop_price is not None and bar.low <= stop_price:
            return stop_price, "stop_loss"
        if target_price is not None and bar.high >= target_price:
            return target_price, "take_profit"
        return None
    if stop_price is not None and bar.high >= stop_price:
        return stop_price, "stop_loss"
    if target_price is not None and bar.low <= target_price:
        return target_price, "take_profit"
    return None


def _gross_pnl(entry_price: float, exit_price: float, side: str, quantity: float) -> float:
    return (exit_price - entry_price) * quantity if side == "long" else (entry_price - exit_price) * quantity


def _adverse_excursion(entry_price: float, bar: MarketPriceBar, request: BacktestRunRequest) -> float:
    price = bar.low if request.side == "long" else bar.high
    return _gross_pnl(entry_price, price, request.side, request.quantity)


def _favorable_excursion(entry_price: float, bar: MarketPriceBar, request: BacktestRunRequest) -> float:
    price = bar.high if request.side == "long" else bar.low
    return _gross_pnl(entry_price, price, request.side, request.quantity)


def _fees(entry_fill: float, exit_fill: float, request: BacktestRunRequest) -> float:
    notional = abs(entry_fill * request.quantity) + abs(exit_fill * request.quantity)
    return notional * request.cost_model.fee_bps / 10000 + request.cost_model.commission_per_trade * 2
