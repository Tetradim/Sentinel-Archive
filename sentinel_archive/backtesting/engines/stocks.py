from __future__ import annotations

from sentinel_archive.backtesting.engines.crypto import _apply_slippage, _fees, _gross_pnl
from sentinel_archive.backtesting.metrics import summarize_trades
from sentinel_archive.backtesting.models import BacktestReport, BacktestRunRequest, BacktestTrade


def run_stock_backtest(request: BacktestRunRequest) -> BacktestReport:
    if not request.bars:
        return _empty_report(request, ["thin_data"])

    normalized = request.model_copy(update={"side": "long", "leverage": 1.0})
    entry_bar = normalized.bars[0]
    entry_price = entry_bar.open
    entry_fill = _apply_slippage(entry_price, normalized.cost_model.slippage_bps, "long", is_entry=True)
    stop_price = entry_fill * (1 - normalized.stop_loss_pct / 100) if normalized.stop_loss_pct else None
    target_price = entry_fill * (1 + normalized.take_profit_pct / 100) if normalized.take_profit_pct else None
    exit_bar = normalized.bars[-1]
    exit_price = exit_bar.close
    exit_reason = "final_close"
    mae = 0.0
    mfe = 0.0
    equity_curve = [normalized.starting_equity]

    for bar in normalized.bars:
        mae = min(mae, _gross_pnl(entry_fill, bar.low, "long", normalized.quantity))
        mfe = max(mfe, _gross_pnl(entry_fill, bar.high, "long", normalized.quantity))
        equity_curve.append(normalized.starting_equity + _gross_pnl(entry_fill, bar.close, "long", normalized.quantity))
        if stop_price is not None and bar.low <= stop_price:
            exit_price = stop_price
            exit_bar = bar
            exit_reason = "stop_loss"
            break
        if target_price is not None and bar.high >= target_price:
            exit_price = target_price
            exit_bar = bar
            exit_reason = "take_profit"
            break

    exit_fill = _apply_slippage(exit_price, normalized.cost_model.slippage_bps, "long", is_entry=False)
    slippage_cost = abs(entry_fill - entry_price) * normalized.quantity + abs(exit_fill - exit_price) * normalized.quantity
    fees = _fees(entry_fill, exit_fill, normalized)
    pnl = _gross_pnl(entry_fill, exit_fill, "long", normalized.quantity) - fees
    trade = BacktestTrade(
        symbol=normalized.symbol.upper(),
        side="long",
        quantity=normalized.quantity,
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
    ending_equity = normalized.starting_equity + pnl
    equity_curve.append(ending_equity)
    metrics = summarize_trades(
        trades=[trade],
        starting_equity=normalized.starting_equity,
        ending_equity=ending_equity,
        equity_curve=equity_curve,
        slippage=slippage_cost,
    )
    return BacktestReport(
        asset_class="stock",
        symbol=normalized.symbol.upper(),
        metrics=metrics,
        trades=[trade],
        assumptions=normalized.model_dump(mode="json", exclude={"bars", "option_alerts", "option_quotes"}),
    )


def _empty_report(request: BacktestRunRequest, warnings: list[str]) -> BacktestReport:
    metrics = summarize_trades(
        trades=[],
        starting_equity=request.starting_equity,
        ending_equity=request.starting_equity,
        equity_curve=[request.starting_equity],
        warnings=warnings,
    )
    return BacktestReport(asset_class="stock", symbol=request.symbol.upper(), metrics=metrics, warnings=warnings, assumptions={})
