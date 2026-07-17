from __future__ import annotations

import importlib
import importlib.util
import hashlib
import math
import os
import subprocess
import sys
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from sentinel_archive.backtesting.models import BacktestOrderIntent, DerivativesRunRequest, MarketPriceBar
from sentinel_archive.profitability.models import (
    ProfitabilityStrategyConfig,
    RecordedStrategySignal,
    StrategyAdapterEvidence,
)


class StrategyAdapterUnavailable(ValueError):
    pass


@dataclass
class StrategyRuntime:
    config: ProfitabilityStrategyConfig
    base_request: DerivativesRunRequest
    signals: list[RecordedStrategySignal]
    evidence: StrategyAdapterEvidence
    native_module: ModuleType | None = None
    native_modules: dict[str, ModuleType] = field(default_factory=dict)
    source_runtime: "StrategyRuntime | None" = None

    def generate_orders(
        self,
        bars: list[MarketPriceBar],
        *,
        trade_start: int,
        trade_end: int,
    ) -> list[BacktestOrderIntent]:
        if self.config.profile.startswith("iron_"):
            return _iron_orders(self, bars, trade_start=trade_start, trade_end=trade_end)
        if self.config.profile == "chain_signal_replay":
            return _chain_orders(self, bars, trade_start=trade_start, trade_end=trade_end)
        if self.config.profile == "chain_auto_structure":
            return _chain_auto_orders(self, bars, trade_start=trade_start, trade_end=trade_end)
        if self.config.profile == "combination_routed" and self.source_runtime is not None:
            return _combination_orders(self, bars, trade_start=trade_start, trade_end=trade_end)
        raise StrategyAdapterUnavailable(f"unsupported strategy profile: {self.config.profile}")


def build_strategy_runtime(
    config: ProfitabilityStrategyConfig,
    base_request: DerivativesRunRequest,
    signals: list[RecordedStrategySignal],
) -> StrategyRuntime:
    _validate_bot_identity(config.profile, base_request.bot_id)
    _validate_domain(config.profile, base_request)
    if config.profile.startswith("iron_"):
        return _build_iron_runtime(config, base_request, signals)
    if config.profile == "chain_signal_replay":
        return _build_chain_runtime(config, base_request, signals)
    if config.profile == "chain_auto_structure":
        return _build_chain_auto_runtime(config, base_request, signals)
    if config.profile == "combination_routed":
        return _build_combination_runtime(config, base_request, signals)
    raise StrategyAdapterUnavailable(f"unsupported strategy profile: {config.profile}")


def _build_iron_runtime(
    config: ProfitabilityStrategyConfig,
    base_request: DerivativesRunRequest,
    signals: list[RecordedStrategySignal],
) -> StrategyRuntime:
    repo = _find_repository("iron", config.repository_path)
    module = None
    native_modules: dict[str, ModuleType] = {}
    warnings: list[str] = []
    dates = [_timestamp(bar.timestamp).date() for bar in base_request.bars]
    if len(set(dates)) != len(dates):
        warnings.append("iron_daily_strategy_uses_last_completed_bar_per_utc_date")
    strategy_files: list[Path] = []
    if repo is not None:
        strategy_file = repo / "src/sentinel_iron/strategies/trend_following.py"
        module = _load_module(strategy_file, "archive_native_iron_trend")
        native_modules["trend"] = module
        strategy_files.append(strategy_file)
        if config.profile in {"iron_carry", "iron_composite"}:
            carry_file = repo / "src/sentinel_iron/strategies/carry.py"
            native_modules["carry"] = _load_module(carry_file, "archive_native_iron_carry")
            strategy_files.append(carry_file)
        if config.profile == "iron_composite":
            composite_file = repo / "src/sentinel_iron/strategies/composite.py"
            native_modules["composite"] = _load_module(composite_file, "archive_native_iron_composite")
            strategy_files.append(composite_file)
    else:
        strategy_file = None
    if repo is None:
        if config.require_native:
            raise StrategyAdapterUnavailable("Sentinel-Iron repository was not found in an approved bot root")
        warnings.append("native_iron_unavailable_builtin_parity_implementation_used")
    repository_commit = _git_commit(repo)
    repository_clean = _git_clean(repo)
    strategy_sha256 = _sha256_files(strategy_files)
    native = module is not None
    origins = {
        "iron_trend": "Sentinel-Iron trend_following.calculate_trend_signal",
        "iron_volatility_trend": "Sentinel-Iron trend_following.calculate_volatility_adjusted_trend_signal",
        "iron_carry": "Sentinel-Iron carry.calculate_carry_signal",
        "iron_composite": "Sentinel-Iron composite.combine_weighted_signals",
    }
    return StrategyRuntime(
        config=config,
        base_request=base_request,
        signals=signals,
        evidence=StrategyAdapterEvidence(
            adapter_id=f"iron.{config.profile.removeprefix('iron_').replace('_', '-')}.v1",
            strategy_origin=origins[config.profile],
            native=native,
            repository_path=str(repo) if repo else None,
            repository_commit=repository_commit,
            repository_clean=repository_clean,
            strategy_sha256=strategy_sha256,
            reproducible=bool(native and repository_commit and repository_clean and strategy_sha256),
            dependencies={path.name: _sha256_file(path) or "unavailable" for path in strategy_files},
            warnings=warnings,
        ),
        native_module=module,
        native_modules=native_modules,
    )


def _build_chain_runtime(
    config: ProfitabilityStrategyConfig,
    base_request: DerivativesRunRequest,
    signals: list[RecordedStrategySignal],
) -> StrategyRuntime:
    if not signals:
        raise StrategyAdapterUnavailable(
            "Sentinel-Chain does not generate entries; provide timestamped recorded Chain signals"
        )
    repo = _find_repository("chain", config.repository_path)
    module = None
    native = False
    warnings = ["chain_profitability_is_conditional_on_the_supplied_signal_stream"]
    if config.parameters.get("signal_stream_complete") is not True:
        warnings.append("recorded_chain_signal_stream_not_attested_complete")
    if repo is not None:
        strategy_file = repo / "src/sentinel_chain/signals.py"
        module = _load_module(strategy_file, "archive_native_chain_signals")
        native = True
    else:
        strategy_file = None
    if repo is None:
        if config.require_native:
            raise StrategyAdapterUnavailable("Sentinel-Chain repository was not found in an approved bot root")
        warnings.append("native_chain_normalizer_unavailable_archive_parser_used")
    repository_commit = _git_commit(repo)
    repository_clean = _git_clean(repo)
    strategy_sha256 = _sha256_file(strategy_file)
    return StrategyRuntime(
        config=config,
        base_request=base_request,
        signals=signals,
        evidence=StrategyAdapterEvidence(
            adapter_id="chain.recorded-signals.v1",
            strategy_origin="Sentinel-Chain recorded signal stream",
            native=native,
            repository_path=str(repo) if repo else None,
            repository_commit=repository_commit,
            repository_clean=repository_clean,
            strategy_sha256=strategy_sha256,
            reproducible=bool(native and repository_commit and repository_clean and strategy_sha256),
            signal_count=len(signals),
            warnings=warnings,
        ),
        native_module=module,
    )


def _build_chain_auto_runtime(
    config: ProfitabilityStrategyConfig,
    base_request: DerivativesRunRequest,
    signals: list[RecordedStrategySignal],
) -> StrategyRuntime:
    repo = _find_repository("chain", config.repository_path)
    module = None
    strategy_file = None
    warnings = ["chain_auto_entries_execute_on_the_next_bar_to_avoid_close_lookahead"]
    if repo is not None:
        strategy_file = repo / "src/sentinel_chain/charting/automap.py"
        module = _load_module(strategy_file, "archive_native_chain_automap")
    elif config.require_native:
        raise StrategyAdapterUnavailable("Sentinel-Chain repository was not found in an approved bot root")
    else:
        warnings.append("native_chain_automap_unavailable_archive_indicator_parity_used")
    repository_commit = _git_commit(repo)
    repository_clean = _git_clean(repo)
    strategy_sha256 = _sha256_file(strategy_file)
    return StrategyRuntime(
        config=config,
        base_request=base_request,
        signals=signals,
        evidence=StrategyAdapterEvidence(
            adapter_id="chain.auto-structure.v1",
            strategy_origin="Sentinel-Chain charting.automap EMA/RSI/ATR auto strategy",
            native=module is not None,
            repository_path=str(repo) if repo else None,
            repository_commit=repository_commit,
            repository_clean=repository_clean,
            strategy_sha256=strategy_sha256,
            reproducible=bool(module and repository_commit and repository_clean and strategy_sha256),
            warnings=warnings,
        ),
        native_module=module,
    )


def _build_combination_runtime(
    config: ProfitabilityStrategyConfig,
    base_request: DerivativesRunRequest,
    signals: list[RecordedStrategySignal],
) -> StrategyRuntime:
    source_profile = str(config.parameters.get("source_profile") or "").strip()
    allowed_sources = {
        "iron_trend",
        "iron_volatility_trend",
        "iron_carry",
        "iron_composite",
        "chain_signal_replay",
        "chain_auto_structure",
    }
    if source_profile not in allowed_sources:
        raise StrategyAdapterUnavailable(
            "Combination has no independent strategy generator; parameters.source_profile must name an Iron or Chain strategy adapter"
        )
    source_parameters = config.parameters.get("source_parameters") or {}
    if not isinstance(source_parameters, dict):
        raise StrategyAdapterUnavailable("Combination source_parameters must be an object")
    source_config = ProfitabilityStrategyConfig(
        profile=source_profile,  # type: ignore[arg-type]
        parameters=source_parameters,
        repository_path=str(config.parameters.get("source_repository_path") or "") or None,
        require_native=config.require_native,
    )
    source_bot_id = "iron" if source_profile.startswith("iron_") else "chain"
    source = build_strategy_runtime(
        source_config,
        base_request.model_copy(update={"bot_id": source_bot_id}),
        signals,
    )
    repo = _find_repository("combination", config.repository_path)
    if config.require_native and repo is None:
        raise StrategyAdapterUnavailable("Sentinel-Combination repository was not found in an approved bot root")
    warnings = [
        "combination_has_no_independent_strategy",
        f"profitability_is_inherited_from_{source_profile}",
        *source.evidence.warnings,
    ]
    combination_clean = _git_clean(repo)
    combination_commit = _git_commit(repo)
    native_modules: dict[str, ModuleType] = {}
    combination_files: list[Path] = []
    if repo is not None:
        combination_files = [
            repo / "src/sentinel_combination/application/risk.py",
            repo / "src/sentinel_combination/domain/instruments.py",
            repo / "src/sentinel_combination/domain/orders.py",
            repo / "src/sentinel_combination/domain/enums.py",
            repo / "src/sentinel_combination/domain/brackets.py",
        ]
        native_modules["enums"] = _load_package_module(repo, "sentinel_combination.domain.enums")
        native_modules["instruments"] = _load_package_module(repo, "sentinel_combination.domain.instruments")
        native_modules["orders"] = _load_package_module(repo, "sentinel_combination.domain.orders")
        native_modules["risk"] = _load_package_module(repo, "sentinel_combination.application.risk")
    combination_sha256 = _sha256_files(combination_files)
    return StrategyRuntime(
        config=config,
        base_request=base_request,
        signals=signals,
        evidence=StrategyAdapterEvidence(
            adapter_id=f"combination.routed.{source_profile}.v1",
            strategy_origin=f"Sentinel-Combination routed {source.evidence.strategy_origin}",
            native=repo is not None and source.evidence.native,
            repository_path=str(repo) if repo else None,
            repository_commit=combination_commit,
            repository_clean=combination_clean,
            strategy_sha256=combination_sha256,
            reproducible=bool(repo and combination_commit and combination_clean and combination_sha256 and source.evidence.reproducible),
            dependencies={
                "source_adapter": source.evidence.adapter_id,
                "source_repository_commit": source.evidence.repository_commit or "unavailable",
                "source_strategy_sha256": source.evidence.strategy_sha256 or "unavailable",
                **{f"combination:{path.name}": _sha256_file(path) or "unavailable" for path in combination_files},
            },
            independent_strategy=False,
            signal_count=source.evidence.signal_count,
            warnings=warnings,
        ),
        source_runtime=source,
        native_modules=native_modules,
    )


def _iron_orders(
    runtime: StrategyRuntime,
    bars: list[MarketPriceBar],
    *,
    trade_start: int,
    trade_end: int,
) -> list[BacktestOrderIntent]:
    raw_lookbacks = runtime.config.parameters.get("lookbacks", [20, 60, 120])
    if not isinstance(raw_lookbacks, list) or not raw_lookbacks:
        raise StrategyAdapterUnavailable("Iron lookbacks must be a non-empty list")
    lookbacks = tuple(int(value) for value in raw_lookbacks)
    if any(value <= 0 for value in lookbacks):
        raise StrategyAdapterUnavailable("Iron lookbacks must be positive")
    threshold = Decimal(str(runtime.config.parameters.get("threshold", 0)))
    orders: list[BacktestOrderIntent] = []
    for index in range(trade_start, trade_end):
        current_day = _timestamp(bars[index].timestamp).date()
        if index > 0 and _timestamp(bars[index - 1].timestamp).date() == current_day:
            continue
        history = _daily_history(bars[:index])
        score, components = _iron_score(runtime, history, bars[index].timestamp, lookbacks)
        side = "long" if score > threshold else "short" if score < -threshold else "long"
        quantity = _iron_quantity(runtime, history, score)
        target_quantity = quantity if abs(score) > threshold else 0.0
        orders.append(
            BacktestOrderIntent(
                order_id=f"iron-target-{index:08d}",
                timestamp=bars[index].timestamp,
                action="target",
                side=side,
                order_type="market",
                quantity=target_quantity,
                time_in_force="IOC",
                metadata={
                    "score": str(score),
                    "profile": runtime.config.profile,
                    "components": components,
                    "history_days": len(history),
                },
            )
        )
    return orders


def _combination_orders(
    runtime: StrategyRuntime,
    bars: list[MarketPriceBar],
    *,
    trade_start: int,
    trade_end: int,
) -> list[BacktestOrderIntent]:
    if runtime.source_runtime is None:
        raise StrategyAdapterUnavailable("Combination source runtime is unavailable")
    orders = runtime.source_runtime.generate_orders(bars, trade_start=trade_start, trade_end=trade_end)
    risk_module = runtime.native_modules.get("risk")
    instrument_module = runtime.native_modules.get("instruments")
    order_module = runtime.native_modules.get("orders")
    enum_module = runtime.native_modules.get("enums")
    if not all((risk_module, instrument_module, order_module, enum_module)):
        return [
            order.model_copy(update={"metadata": {**order.metadata, "combination_risk": "native_unavailable"}})
            for order in orders
        ]

    request = runtime.base_request
    asset_class = (
        enum_module.AssetClass.LISTED_FUTURE
        if request.contract.instrument_type == "listed_future"
        else enum_module.AssetClass.CRYPTO_PERPETUAL
    )
    instrument = instrument_module.Instrument(
        instrument_id=request.symbol,
        asset_class=asset_class,
        venue=request.contract.venue,
        symbol=request.symbol,
        price_increment=Decimal(str(request.contract.tick_size)),
        quantity_increment=Decimal(str(request.contract.quantity_step)),
        minimum_quantity=Decimal(str(request.contract.minimum_quantity)),
        minimum_notional=Decimal("0"),
        contract_multiplier=Decimal(str(request.contract.contract_multiplier)),
    )
    raw_limits = runtime.config.parameters.get("risk_limits") or {}
    if not isinstance(raw_limits, dict):
        raise StrategyAdapterUnavailable("Combination risk_limits must be an object")
    maximum_notional = Decimal(str(raw_limits.get("maximum_order_notional", request.starting_equity * request.leverage)))
    limits = risk_module.RiskLimits(
        maximum_order_notional=maximum_notional,
        maximum_position_notional=Decimal(str(raw_limits.get("maximum_position_notional", maximum_notional))),
        maximum_margin_fraction=Decimal(str(raw_limits.get("maximum_margin_fraction", 1))),
        maximum_daily_loss=Decimal(str(raw_limits.get("maximum_daily_loss", request.starting_equity))),
        maximum_spread_bps=Decimal(str(raw_limits.get("maximum_spread_bps", 10000))),
    )
    bars_by_timestamp = {bar.timestamp: bar for bar in bars[trade_start:trade_end]}
    approved: list[BacktestOrderIntent] = []
    current_target = Decimal("0")
    for order in orders:
        signed_target = Decimal(str(order.quantity)) * (Decimal("1") if order.side == "long" else Decimal("-1"))
        if order.quantity == 0:
            current_target = Decimal("0")
            approved.append(order.model_copy(update={"metadata": {**order.metadata, "combination_risk": "reduce_to_flat"}}))
            continue
        if signed_target == current_target:
            approved.append(order.model_copy(update={"metadata": {**order.metadata, "combination_risk": "target_unchanged"}}))
            continue
        bar = bars_by_timestamp.get(order.timestamp or "")
        if bar is None:
            approved.append(order)
            continue
        reference = instrument.quantize_price(Decimal(str(bar.open)))
        quantity = instrument.quantize_quantity_down(Decimal(str(order.quantity)))
        side = enum_module.Side.BUY if order.side == "long" else enum_module.Side.SELL
        notional = instrument.notional(price=reference, quantity=quantity)
        margin_rate = max(request.contract.initial_margin_rate, 1 / request.leverage)
        try:
            intent = order_module.OrderIntent(
                client_order_id=order.order_id,
                account_id="sentinel-archive",
                instrument_id=request.symbol,
                side=side,
                quantity=quantity,
                order_type=enum_module.OrderType.MARKET,
                strategy_id=runtime.evidence.adapter_id,
                created_at=_timestamp(order.timestamp or bar.timestamp),
                time_in_force=order.time_in_force,
            )
            decision = risk_module.evaluate_order_risk(
                intent=intent,
                instrument=instrument,
                context=risk_module.RiskContext(
                    reference_price=reference,
                    current_position_quantity=Decimal("0"),
                    account_equity=Decimal(str(request.starting_equity)),
                    available_buying_power=Decimal(str(request.starting_equity)),
                    initial_margin_required=notional * Decimal(str(margin_rate)),
                    realized_pnl_today=Decimal("0"),
                    spread_bps=Decimal(str(request.cost_model.spread_bps)),
                ),
                limits=limits,
            )
            reasons = list(decision.reasons)
        except ValueError as exc:
            reasons = [str(exc)]
        risk_metadata = {
            "approved": not reasons,
            "reasons": reasons,
            "reference_price": str(reference),
            "order_notional": str(notional),
        }
        approved.append(
            order.model_copy(
                update={
                    "metadata": {**order.metadata, "combination_risk": risk_metadata},
                    "preflight_rejection_reason": None if not reasons else f"combination_risk:{'; '.join(reasons)}",
                }
            )
        )
        if not reasons:
            current_target = signed_target
    return approved


def _iron_score(
    runtime: StrategyRuntime,
    history: list[MarketPriceBar],
    decision_timestamp: str,
    lookbacks: tuple[int, ...],
) -> tuple[Decimal, dict[str, str]]:
    trend_module = runtime.native_modules.get("trend")
    if trend_module is not None:
        points = tuple(
            trend_module.PricePoint(day=_timestamp(bar.timestamp).date(), close=Decimal(str(bar.close)))
            for bar in history
        )
        trend_signal = trend_module.calculate_trend_signal(
            runtime.base_request.symbol,
            points,
            trend_module.TrendSignalConfig(lookbacks=lookbacks),
        )
        trend_score = Decimal(trend_signal.score)
    else:
        trend_score = _builtin_iron_score(history, lookbacks)

    if runtime.config.profile == "iron_trend":
        return trend_score, {"trend": str(trend_score)}
    if runtime.config.profile == "iron_volatility_trend":
        annualized_volatility = _rolling_annualized_volatility(
            history,
            int(runtime.config.parameters.get("volatility_lookback", 60)),
        )
        if annualized_volatility is None:
            return Decimal("0"), {"volatility_adjusted_trend": "0", "annualized_volatility": "unavailable"}
        if trend_module is not None:
            signal = trend_module.calculate_volatility_adjusted_trend_signal(
                runtime.base_request.symbol,
                points,
                trend_module.VolatilityAdjustedTrendSignalConfig(
                    lookbacks=lookbacks,
                    annualized_volatility=annualized_volatility,
                ),
            )
            score = Decimal(signal.score)
        else:
            score = trend_score
        return score, {"volatility_adjusted_trend": str(score), "annualized_volatility": str(annualized_volatility)}

    carry_score = _iron_carry_score(runtime, decision_timestamp)
    if runtime.config.profile == "iron_carry":
        return carry_score, {"carry": str(carry_score)}

    trend_weight = Decimal(str(runtime.config.parameters.get("trend_weight", 0.7)))
    carry_weight = Decimal(str(runtime.config.parameters.get("carry_weight", 0.3)))
    if trend_weight <= 0 or carry_weight <= 0:
        raise StrategyAdapterUnavailable("Iron composite weights must be positive")
    composite_module = runtime.native_modules.get("composite")
    if composite_module is not None:
        composite = composite_module.combine_weighted_signals(
            runtime.base_request.symbol,
            (
                composite_module.WeightedSignal("trend", trend_score, trend_weight),
                composite_module.WeightedSignal("carry", carry_score, carry_weight),
            ),
        )
        score = Decimal(composite.score)
    else:
        score = (trend_score * trend_weight + carry_score * carry_weight) / (trend_weight + carry_weight)
        score = max(Decimal("-1"), min(Decimal("1"), score))
    return score, {"trend": str(trend_score), "carry": str(carry_score)}


def _iron_carry_score(runtime: StrategyRuntime, decision_timestamp: str) -> Decimal:
    raw = runtime.config.parameters.get("curve_snapshots")
    if not isinstance(raw, list) or not raw:
        raise StrategyAdapterUnavailable("Iron carry strategies require parameters.curve_snapshots")
    decision_time = _timestamp(decision_timestamp)
    eligible = [item for item in raw if isinstance(item, dict) and _timestamp(str(item.get("timestamp"))) < decision_time]
    if not eligible:
        return Decimal("0")
    snapshot = max(eligible, key=lambda item: _timestamp(str(item["timestamp"])))
    front_price = Decimal(str(snapshot["front_price"]))
    deferred_price = Decimal(str(snapshot["deferred_price"]))
    front_expiration = date.fromisoformat(str(snapshot["front_expiration"]))
    deferred_expiration = date.fromisoformat(str(snapshot["deferred_expiration"]))
    carry_module = runtime.native_modules.get("carry")
    if carry_module is not None:
        signal = carry_module.calculate_carry_signal(
            runtime.base_request.symbol,
            carry_module.CurveContract("front", front_expiration, front_price),
            carry_module.CurveContract("deferred", deferred_expiration, deferred_price),
        )
        return Decimal(signal.score)
    days = (deferred_expiration - front_expiration).days
    if days <= 0:
        raise StrategyAdapterUnavailable("deferred carry expiration must be after front expiration")
    annualized = (front_price - deferred_price) / front_price * (Decimal("365") / Decimal(days))
    return Decimal("1") if annualized > 0 else Decimal("-1") if annualized < 0 else Decimal("0")


def _iron_quantity(runtime: StrategyRuntime, history: list[MarketPriceBar], score: Decimal) -> float:
    fixed = float(runtime.config.parameters.get("quantity", runtime.base_request.quantity))
    if runtime.config.parameters.get("sizing_mode", "fixed") != "volatility_target" or score == 0:
        return fixed
    lookback = int(runtime.config.parameters.get("dollar_volatility_lookback", 20))
    if len(history) < lookback + 1 or lookback < 2:
        return 0.0
    closes = [Decimal(str(bar.close)) for bar in history[-(lookback + 1) :]]
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    mean_change = sum(changes, Decimal("0")) / Decimal(len(changes))
    variance = sum((value - mean_change) ** 2 for value in changes) / Decimal(len(changes) - 1)
    dollar_volatility = variance.sqrt() * Decimal(str(runtime.base_request.contract.contract_multiplier))
    if dollar_volatility <= 0:
        return 0.0
    risk_fraction = Decimal(str(runtime.config.parameters.get("target_risk_fraction", 0.01)))
    max_contracts = int(runtime.config.parameters.get("max_contracts", 100))
    raw = Decimal(str(runtime.base_request.starting_equity)) * risk_fraction * abs(score) / dollar_volatility
    return float(min(Decimal(max_contracts), Decimal(math.floor(raw))))


def _daily_history(bars: list[MarketPriceBar]) -> list[MarketPriceBar]:
    by_day: dict[date, MarketPriceBar] = {}
    for bar in bars:
        by_day[_timestamp(bar.timestamp).date()] = bar
    return [by_day[key] for key in sorted(by_day)]


def _rolling_annualized_volatility(history: list[MarketPriceBar], lookback: int) -> Decimal | None:
    if lookback < 2 or len(history) < lookback + 1:
        return None
    closes = [bar.close for bar in history[-(lookback + 1) :]]
    returns = [current / previous - 1 for previous, current in zip(closes, closes[1:]) if previous > 0]
    if len(returns) < 2:
        return None
    value = statistics.stdev(returns) * math.sqrt(252)
    return Decimal(str(value)) if value > 0 else None


def _chain_orders(
    runtime: StrategyRuntime,
    bars: list[MarketPriceBar],
    *,
    trade_start: int,
    trade_end: int,
) -> list[BacktestOrderIntent]:
    start = _timestamp(bars[trade_start].timestamp)
    end = _timestamp(bars[trade_end - 1].timestamp)
    orders: list[BacktestOrderIntent] = []
    for index, event in enumerate(sorted(runtime.signals, key=lambda item: item.timestamp)):
        event_time = _timestamp(event.timestamp)
        if event_time < start or event_time > end:
            continue
        bar = next((item for item in bars[trade_start:trade_end] if _timestamp(item.timestamp) >= event_time), None)
        if bar is None:
            continue
        normalized = _normalize_chain_signal(runtime, event.payload)
        reduce_only = bool(_value(normalized, "reduce_only", False))
        if reduce_only:
            quantity = 0.0
        else:
            quantity = _chain_quantity(normalized, bar, runtime.base_request)
        side_value = str(_value(normalized, "side", event.payload.get("side") or "buy")).lower()
        side = "long" if side_value in {"buy", "long"} else "short"
        leverage = float(_value(normalized, "leverage", runtime.base_request.leverage))
        stop_price, target_price, attached_targets, trailing_percent, trailing_activation = _chain_bracket(normalized, bar.open, side)
        orders.append(
            BacktestOrderIntent(
                order_id=f"chain-target-{index:08d}",
                timestamp=bar.timestamp,
                action="target",
                side=side,
                order_type="market",
                quantity=quantity,
                attached_stop_price=None if reduce_only else stop_price,
                attached_target_price=None if reduce_only else target_price,
                attached_targets=[] if reduce_only else attached_targets,
                attached_trailing_percent=None if reduce_only else trailing_percent,
                attached_trailing_activation_price=None if reduce_only else trailing_activation,
                max_hold_bars=None if reduce_only else _optional_int(_value(normalized, "max_hold_marks")),
                leverage=None if reduce_only else leverage,
                time_in_force="IOC",
                metadata={
                    "profile": "chain_signal_replay",
                    "strategy_id": str(_value(normalized, "strategy_id", "recorded")),
                    "source_timestamp": event.timestamp,
                    "max_hold_marks": _value(normalized, "max_hold_marks"),
                },
            )
        )
    return sorted(orders, key=lambda item: (item.timestamp or "", item.order_id))


def _chain_auto_orders(
    runtime: StrategyRuntime,
    bars: list[MarketPriceBar],
    *,
    trade_start: int,
    trade_end: int,
) -> list[BacktestOrderIntent]:
    settings = runtime.config.parameters
    fast_period = int(settings.get("fast_ema", 20))
    slow_period = int(settings.get("slow_ema", 50))
    if fast_period < 2 or slow_period <= fast_period:
        raise StrategyAdapterUnavailable("Chain auto strategy requires 2 <= fast_ema < slow_ema")
    closes = [bar.close for bar in bars]
    candles = [bar.model_dump(mode="json") for bar in bars]
    if runtime.native_module is not None:
        normalized = runtime.native_module.normalize_candles(candles)
        native_closes = [float(item.close) for item in normalized]
        fast = runtime.native_module.ema(native_closes, fast_period)
        slow = runtime.native_module.ema(native_closes, slow_period)
        rsi_values = runtime.native_module.rsi(native_closes, 14)
        atr_values = runtime.native_module.atr(normalized, 14)
    else:
        fast = _ema(closes, fast_period)
        slow = _ema(closes, slow_period)
        rsi_values = _rsi(closes, 14)
        atr_values = _atr(bars, 14)

    stop_multiple = float(settings.get("stop_atr_multiple", 1.6))
    target_multiple = float(settings.get("target_atr_multiple", 2.6))
    max_bars = int(settings.get("max_bars", 48))
    allow_short = bool(settings.get("allow_short", True))
    fixed_quantity = float(settings.get("quantity", runtime.base_request.quantity))
    risk_pct = float(settings.get("risk_pct", 0.0))
    if stop_multiple <= 0 or target_multiple <= 0 or max_bars < 1:
        raise StrategyAdapterUnavailable("Chain ATR multiples and max_bars must be positive")

    orders: list[BacktestOrderIntent] = []
    position: dict[str, Any] | None = None
    for index in range(trade_start, trade_end):
        bar = bars[index]
        if position is not None:
            side = position["side"]
            stop_hit = bar.low <= position["stop"] if side == "long" else bar.high >= position["stop"]
            target_hit = bar.high >= position["target"] if side == "long" else bar.low <= position["target"]
            if stop_hit or target_hit:
                position = None
                continue
            if index - int(position["entry_index"]) >= max_bars:
                orders.append(
                    BacktestOrderIntent(
                        order_id=f"chain-auto-time-exit-{index:08d}",
                        timestamp=bar.timestamp,
                        action="target",
                        side=side,
                        quantity=0,
                        metadata={"profile": "chain_auto_structure", "reason": "max_bars"},
                    )
                )
                position = None
                continue

        signal_index = index - 1
        previous_index = signal_index - 1
        if position is not None or previous_index < 0:
            continue
        values = (fast[signal_index], slow[signal_index], fast[previous_index], slow[previous_index], rsi_values[signal_index])
        if not all(value is not None for value in values):
            continue
        crossed_up = fast[previous_index] <= slow[previous_index] and fast[signal_index] > slow[signal_index] and rsi_values[signal_index] >= 48
        crossed_down = fast[previous_index] >= slow[previous_index] and fast[signal_index] < slow[signal_index] and rsi_values[signal_index] <= 52
        if not crossed_up and not (allow_short and crossed_down):
            continue
        side = "long" if crossed_up else "short"
        atr_value = float(atr_values[signal_index] or closes[signal_index] * 0.01)
        entry = bar.open
        stop_distance = atr_value * stop_multiple
        stop = entry - stop_distance if side == "long" else entry + stop_distance
        target = entry + atr_value * target_multiple if side == "long" else entry - atr_value * target_multiple
        quantity = fixed_quantity
        if risk_pct > 0:
            risk_budget = runtime.base_request.starting_equity * risk_pct / 100
            quantity = risk_budget / max(stop_distance * runtime.base_request.contract.contract_multiplier, 1e-12)
        quantity = _floor_quantity(quantity, runtime.base_request.contract.quantity_step)
        if quantity < runtime.base_request.contract.minimum_quantity:
            continue
        orders.append(
            BacktestOrderIntent(
                order_id=f"chain-auto-entry-{index:08d}",
                timestamp=bar.timestamp,
                action="target",
                side=side,
                quantity=quantity,
                attached_stop_price=stop,
                attached_target_price=target,
                leverage=float(settings.get("leverage", runtime.base_request.leverage)),
                metadata={
                    "profile": "chain_auto_structure",
                    "signal_bar": bars[signal_index].timestamp,
                    "atr": atr_value,
                    "rsi": rsi_values[signal_index],
                },
            )
        )
        position = {"side": side, "stop": stop, "target": target, "entry_index": index}
    return orders


def _normalize_chain_signal(runtime: StrategyRuntime, payload: dict[str, Any]) -> Any:
    if runtime.native_module is not None:
        return runtime.native_module.normalize_signal(payload, source="sentinel-archive-profitability")
    side = str(payload.get("side") or payload.get("action") or "").lower()
    return {
        **payload,
        "side": "buy" if side in {"buy", "long", "entry", "open_long"} else "sell",
        "reduce_only": bool(payload.get("reduce_only")) or side.startswith("close") or side in {"exit", "flatten"},
    }


def _chain_quantity(signal: Any, bar: MarketPriceBar, request: DerivativesRunRequest) -> float:
    base = _decimal_value(signal, "base_amount")
    if base is not None:
        return float(base)
    quote = _decimal_value(signal, "quote_amount")
    if quote is not None:
        return float(quote / Decimal(str(bar.open)))
    risk_amount = _decimal_value(signal, "risk_amount")
    if risk_amount is not None:
        return float(risk_amount / Decimal(str(bar.open)))
    risk_pct = _decimal_value(signal, "risk_pct")
    if risk_pct is not None:
        notional = Decimal(str(request.starting_equity)) * risk_pct / Decimal("100")
        return float(notional / Decimal(str(bar.open)))
    configured = request.quantity
    if configured <= 0:
        raise StrategyAdapterUnavailable("Chain signal could not resolve a positive target quantity")
    return configured


def _chain_bracket(
    signal: Any,
    entry: float,
    side: str,
) -> tuple[float | None, float | None, list[dict[str, float]], float | None, float | None]:
    stop = _decimal_value(signal, "stop_loss_price")
    stop_pct = _decimal_value(signal, "stop_loss_pct")
    target = _decimal_value(signal, "take_profit_price")
    target_pct = _decimal_value(signal, "take_profit_pct")
    targets = _value(signal, "take_profit_targets", ()) or ()
    trailing = _decimal_value(signal, "trailing_stop_pct")
    trailing_activation = _decimal_value(signal, "trailing_activation_price")
    trailing_activation_pct = _decimal_value(signal, "trailing_activation_pct")
    entry_value = Decimal(str(entry))
    if stop is None and stop_pct is not None:
        distance = entry_value * stop_pct / Decimal("100")
        stop = entry_value - distance if side == "long" else entry_value + distance
    if target is None and target_pct is not None:
        distance = entry_value * target_pct / Decimal("100")
        target = entry_value + distance if side == "long" else entry_value - distance
    attached_targets: list[dict[str, float]] = []
    for item in targets:
        item_price = _decimal_value(item, "trigger_price")
        item_pct = _decimal_value(item, "pct")
        if item_price is None and item_pct is not None:
            distance = entry_value * item_pct / Decimal("100")
            item_price = entry_value + distance if side == "long" else entry_value - distance
        close_pct = _decimal_value(item, "close_pct") or Decimal("100")
        if item_price is not None:
            attached_targets.append({"price": float(item_price), "close_fraction": float(close_pct / Decimal("100"))})
    if attached_targets:
        target = None
    if trailing_activation is None and trailing_activation_pct is not None:
        distance = entry_value * trailing_activation_pct / Decimal("100")
        trailing_activation = entry_value + distance if side == "long" else entry_value - distance
    return (
        float(stop) if stop is not None else None,
        float(target) if target is not None else None,
        attached_targets,
        float(trailing) if trailing is not None else None,
        float(trailing_activation) if trailing_activation is not None else None,
    )


def _builtin_iron_score(history: list[MarketPriceBar], lookbacks: tuple[int, ...]) -> Decimal:
    if not history:
        return Decimal("0")
    current = Decimal(str(history[-1].close))
    components: list[Decimal] = []
    for lookback in lookbacks:
        if len(history) <= lookback:
            continue
        prior = Decimal(str(history[-(lookback + 1)].close))
        components.append(Decimal("1") if current > prior else Decimal("-1") if current < prior else Decimal("0"))
    return sum(components, Decimal("0")) / Decimal(len(components)) if components else Decimal("0")


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    multiplier = 2.0 / (period + 1.0)
    previous: float | None = None
    seed: list[float] = []
    for value in values:
        if previous is None:
            seed.append(value)
            if len(seed) < period:
                result.append(None)
                continue
            previous = sum(seed[-period:]) / period
        else:
            previous = ((value - previous) * multiplier) + previous
        result.append(previous)
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    if len(values) < 2:
        return [None for _ in values]
    result: list[float | None] = [None]
    gains: list[float] = []
    losses: list[float] = []
    avg_gain: float | None = None
    avg_loss: float | None = None
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
        if index < period:
            result.append(None)
            continue
        if avg_gain is None or avg_loss is None:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
        else:
            avg_gain = ((avg_gain * (period - 1)) + gains[-1]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[-1]) / period
        result.append(100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss)))
    return result


def _atr(bars: list[MarketPriceBar], period: int) -> list[float | None]:
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        ranges.append(
            bar.high - bar.low
            if previous_close is None
            else max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
        )
        previous_close = bar.close
    result: list[float | None] = []
    previous: float | None = None
    for index, value in enumerate(ranges):
        if index + 1 < period:
            result.append(None)
            continue
        previous = sum(ranges[index + 1 - period : index + 1]) / period if previous is None else ((previous * (period - 1)) + value) / period
        result.append(previous)
    return result


def _floor_quantity(quantity: float, step: float) -> float:
    return math.floor((quantity + 1e-12) / step) * step


def _validate_bot_identity(profile: str, bot_id: str) -> None:
    normalized = bot_id.strip().lower().replace("_", "-")
    expected = {
        "iron_trend": {"iron", "sentinel-iron"},
        "iron_volatility_trend": {"iron", "sentinel-iron"},
        "iron_carry": {"iron", "sentinel-iron"},
        "iron_composite": {"iron", "sentinel-iron"},
        "chain_signal_replay": {"chain", "sentinel-chain"},
        "chain_auto_structure": {"chain", "sentinel-chain"},
        "combination_routed": {"combination", "sentinel-combination"},
    }[profile]
    if normalized not in expected:
        raise StrategyAdapterUnavailable(
            f"strategy profile {profile} cannot be attributed to bot_id {bot_id!r}"
        )


def _validate_domain(profile: str, request: DerivativesRunRequest) -> None:
    instrument = request.contract.instrument_type
    if profile.startswith("iron_") and instrument != "listed_future":
        raise StrategyAdapterUnavailable("Iron profitability studies require a listed-future contract")
    if profile.startswith("chain_") and instrument not in {"crypto_perpetual", "crypto_delivery"}:
        raise StrategyAdapterUnavailable("Chain profitability studies require a crypto futures contract")


def _find_repository(bot: str, requested: str | None) -> Path | None:
    names = {
        "iron": ("Sentinel-Iron",),
        "chain": ("Sentinel-Chain",),
        "combination": ("Sentinel-Combination", "Combination"),
    }[bot]
    roots: list[Path] = []
    configured_root = os.getenv("SENTINEL_BOTS_ROOT")
    if configured_root:
        roots.append(Path(configured_root))
    roots.extend(
        [
            Path.cwd().parent,
            Path.cwd(),
            Path("C:/Users/automation/GitBots"),
        ]
    )
    candidates = [root / name for root in roots for name in names]
    if requested:
        requested_path = Path(requested).expanduser().resolve()
        allowed = {candidate.resolve() for candidate in candidates}
        if requested_path not in allowed:
            raise StrategyAdapterUnavailable("repository_path is outside approved Sentinel bot roots")
        candidates.insert(0, requested_path)
    for candidate in candidates:
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate.resolve()
    return None


def _load_module(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise StrategyAdapterUnavailable(f"native strategy file not found: {path}")
    unique_name = f"{module_name}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(unique_name, path)
    if spec is None or spec.loader is None:
        raise StrategyAdapterUnavailable(f"could not load native strategy module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def _load_package_module(repo: Path, module_name: str) -> ModuleType:
    source_root = str((repo / "src").resolve())
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    try:
        if module_name in sys.modules:
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)
    except (ImportError, ValueError) as exc:
        raise StrategyAdapterUnavailable(f"could not load native module {module_name}: {exc}") from exc


def _git_commit(repo: Path | None) -> str | None:
    if repo is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _git_clean(repo: Path | None) -> bool | None:
    if repo is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return not result.stdout.strip()


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_files(paths: list[Path]) -> str | None:
    if not paths or any(not path.is_file() for path in paths):
        return None
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise StrategyAdapterUnavailable(f"timestamp must include a timezone: {value}")
    return parsed


def _value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _decimal_value(item: Any, key: str) -> Decimal | None:
    value = _value(item, key)
    return Decimal(str(value)) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
