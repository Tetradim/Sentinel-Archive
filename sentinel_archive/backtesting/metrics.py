from __future__ import annotations

from .models import BacktestMetrics, BacktestTrade


def summarize_trades(
    *,
    trades: list[BacktestTrade],
    starting_equity: float,
    ending_equity: float,
    equity_curve: list[float],
    warnings: list[str] | None = None,
    slippage: float = 0.0,
    funding: float = 0.0,
) -> BacktestMetrics:
    safety_flags = sorted(set(warnings or []))
    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl < 0]
    realized_pnl = sum(trade.pnl for trade in trades)
    total_fees = sum(trade.fees for trade in trades)
    total_pnl = ending_equity - starting_equity
    total_return_pct = (total_pnl / starting_equity * 100) if starting_equity else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss else 0.0

    return BacktestMetrics(
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        realized_pnl=realized_pnl,
        total_pnl=total_pnl,
        total_return_pct=total_return_pct,
        win_rate=(len(wins) / len(trades)) if trades else 0.0,
        trade_count=len(trades),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=_max_drawdown_pct(equity_curve),
        mae=min((trade.mae for trade in trades), default=0.0),
        mfe=max((trade.mfe for trade in trades), default=0.0),
        average_win=(sum(wins) / len(wins)) if wins else 0.0,
        average_loss=(sum(losses) / len(losses)) if losses else 0.0,
        total_fees=total_fees,
        slippage=slippage,
        funding=funding,
        safety_score=_safety_score(safety_flags, len(trades), profit_factor),
        safety_flags=safety_flags,
    )


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    return max_drawdown


def _safety_score(flags: list[str], trade_count: int, profit_factor: float) -> float:
    score = 100.0
    penalties = {
        "liquidation_before_stop": 60.0,
        "missing_quote_coverage": 35.0,
        "budget_limited": 20.0,
        "thin_data": 20.0,
    }
    for flag in flags:
        score -= penalties.get(flag, 10.0)
    if trade_count == 0:
        score -= 15.0
    if trade_count and profit_factor < 1:
        score -= 15.0
    return max(0.0, min(100.0, score))
