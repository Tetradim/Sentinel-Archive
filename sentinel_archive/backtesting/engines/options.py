from __future__ import annotations

from dataclasses import dataclass

from sentinel_archive.backtesting.metrics import summarize_trades
from sentinel_archive.backtesting.models import BacktestReport, BacktestRunRequest, BacktestTrade, OptionAlert, OptionQuote


@dataclass
class _OpenOption:
    alert: OptionAlert
    price: float


def run_options_replay(request: BacktestRunRequest) -> BacktestReport:
    warnings: list[str] = []
    quotes_by_contract = _quotes_by_contract(request.option_quotes)
    open_positions: dict[str, _OpenOption] = {}
    trades: list[BacktestTrade] = []

    for alert in sorted(request.option_alerts, key=lambda item: item.timestamp):
        fill_price = _fill_price(alert, quotes_by_contract.get(alert.contract_key), request)
        if fill_price is None:
            warnings.append("missing_quote_coverage")
            continue
        if alert.action == "buy":
            open_positions[alert.contract_key] = _OpenOption(alert=alert, price=fill_price)
            continue
        opened = open_positions.pop(alert.contract_key, None)
        if not opened:
            warnings.append("unmatched_option_exit")
            continue
        quantity = min(alert.quantity, opened.alert.quantity)
        multiplier = request.cost_model.option_multiplier
        fees = request.cost_model.commission_per_trade * 2
        pnl = (fill_price - opened.price) * quantity * multiplier - fees
        trades.append(
            BacktestTrade(
                symbol=alert.contract_key,
                side="long",
                quantity=quantity,
                entry_time=opened.alert.timestamp,
                entry_price=opened.price,
                exit_time=alert.timestamp,
                exit_price=fill_price,
                pnl=pnl,
                fees=fees,
                mae=min(0.0, pnl),
                mfe=max(0.0, pnl),
                exit_reason="option_alert_exit",
            )
        )

    ending_equity = request.starting_equity + sum(trade.pnl for trade in trades)
    metrics = summarize_trades(
        trades=trades,
        starting_equity=request.starting_equity,
        ending_equity=ending_equity,
        equity_curve=[request.starting_equity, ending_equity],
        warnings=warnings,
    )
    return BacktestReport(
        asset_class="options",
        symbol=request.symbol.upper(),
        metrics=metrics,
        trades=trades,
        warnings=warnings,
        assumptions=request.model_dump(mode="json", exclude={"bars", "option_alerts", "option_quotes"}),
    )


def _quotes_by_contract(quotes: list[OptionQuote]) -> dict[str, list[OptionQuote]]:
    grouped: dict[str, list[OptionQuote]] = {}
    for quote in quotes:
        grouped.setdefault(quote.contract_key, []).append(quote)
    for values in grouped.values():
        values.sort(key=lambda item: item.timestamp)
    return grouped


def _fill_price(alert: OptionAlert, quotes: list[OptionQuote] | None, request: BacktestRunRequest) -> float | None:
    if alert.fill_price is not None:
        return alert.fill_price
    if alert.alert_price is not None:
        return alert.alert_price
    if not quotes:
        return None
    quote = next((item for item in quotes if item.timestamp >= alert.timestamp), quotes[-1])
    preferred = getattr(quote, request.cost_model.option_fill_price)
    if preferred is not None:
        return preferred
    if quote.mid is not None:
        return quote.mid
    if quote.bid is not None and quote.ask is not None:
        return (quote.bid + quote.ask) / 2
    return quote.last
