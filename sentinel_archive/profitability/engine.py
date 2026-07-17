from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sentinel_archive.backtesting.derivatives import run_derivatives_backtest
from sentinel_archive.backtesting.models import (
    BacktestCostModel,
    BacktestOrderIntent,
    DerivativesReport,
    DerivativesRunRequest,
    MarketPriceBar,
)
from sentinel_archive.profitability.adapters import (
    StrategyAdapterUnavailable,
    StrategyRuntime,
    build_strategy_runtime,
)
from sentinel_archive.profitability.models import (
    DataQualityEvidence,
    ProfitabilityComparisonReport,
    ProfitabilityComparisonRequest,
    ProfitabilityFoldResult,
    ProfitabilityMetrics,
    ProfitabilityRanking,
    ProfitabilityScenarioResult,
    ProfitabilityStudyReport,
    ProfitabilityStudyRequest,
)


@dataclass
class _FoldExecution:
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    report: DerivativesReport
    benchmark: DerivativesReport
    period_returns: list[float]
    benchmark_returns: list[float]
    generated_order_count: int


def run_profitability_study(request: ProfitabilityStudyRequest) -> ProfitabilityStudyReport:
    fingerprint = _fingerprint(request.model_dump(mode="json"))
    study_id = f"profit-{fingerprint[:20]}"
    bars = request.base_request.bars
    data_quality = inspect_data_quality(request)
    asset_class = _asset_class(request.base_request)
    base_report = _base_report(request, study_id, fingerprint, data_quality, asset_class)
    if not data_quality.passed:
        base_report.verdict = "insufficient_data"
        base_report.verdict_reasons = list(data_quality.failures)
        return base_report

    try:
        runtime = build_strategy_runtime(request.strategy, request.base_request, request.signals)
    except (StrategyAdapterUnavailable, ValueError) as exc:
        base_report.verdict = "insufficient_strategy"
        base_report.verdict_reasons = [str(exc)]
        return base_report

    folds = _fold_boundaries(len(bars), request)
    if not folds:
        base_report.verdict = "insufficient_data"
        base_report.verdict_reasons = ["not enough bars for the configured anchored walk-forward folds"]
        base_report.adapter = runtime.evidence
        return base_report

    try:
        base_executions = _execute_folds(request, runtime, folds, request.base_request.cost_model)
        runtime.evidence.order_count = sum(item.generated_order_count for item in base_executions)
        scenario_results: list[ProfitabilityScenarioResult] = []
        for scenario in request.cost_stresses:
            costs = _stressed_costs(request.base_request.cost_model, scenario)
            executions = base_executions if _is_base_stress(scenario) else _execute_folds(request, runtime, folds, costs)
            scenario_results.append(_scenario_result(scenario.name, executions))
    except (StrategyAdapterUnavailable, ValueError) as exc:
        base_report.verdict = "insufficient_strategy"
        base_report.verdict_reasons = [f"strategy replay failed: {exc}"]
        base_report.adapter = runtime.evidence
        return base_report

    fold_results = [_fold_result(item, bars) for item in base_executions]
    period_returns = [value for item in base_executions for value in item.period_returns]
    benchmark_returns = [value for item in base_executions for value in item.benchmark_returns]
    periods_per_year = request.validation.periods_per_year or _infer_periods_per_year(bars, asset_class)
    metrics = _aggregate_metrics(
        request,
        base_executions,
        scenario_results,
        period_returns,
        benchmark_returns,
        periods_per_year,
    )
    verdict, reasons = _verdict(request, runtime, metrics)
    warnings = sorted(
        {
            *data_quality.warnings,
            *runtime.evidence.warnings,
            *(warning for item in base_executions for warning in item.report.warnings),
        }
    )
    return ProfitabilityStudyReport(
        study_id=study_id,
        fingerprint=fingerprint,
        name=request.name,
        bot_id=request.base_request.bot_id,
        symbol=request.base_request.symbol.upper(),
        asset_class=asset_class,
        verdict=verdict,
        verdict_reasons=reasons,
        data_quality=data_quality,
        adapter=runtime.evidence,
        metrics=metrics,
        folds=fold_results,
        scenarios=scenario_results,
        warnings=warnings,
        assumptions={
            "strategy": request.strategy.model_dump(mode="json"),
            "validation": request.validation.model_dump(mode="json"),
            "cost_stresses": [item.model_dump(mode="json") for item in request.cost_stresses],
            "periods_per_year": periods_per_year,
            "walk_forward": "anchored expanding history; non-overlapping forward test folds",
            "bootstrap": "deterministic circular block bootstrap of out-of-sample period returns",
            "benchmark": "always-long target using identical contract and base execution costs",
        },
    )


def run_profitability_comparison(request: ProfitabilityComparisonRequest) -> ProfitabilityComparisonReport:
    fingerprint = _fingerprint(request.model_dump(mode="json"))
    reports = [run_profitability_study(study) for study in request.studies]
    data_fingerprints = {report.data_quality.fingerprint for report in reports}
    asset_classes = {report.asset_class for report in reports}
    symbols = {report.symbol for report in reports}
    comparable = len(data_fingerprints) == 1 and len(asset_classes) == 1 and len(symbols) == 1
    reasons: list[str] = []
    if len(data_fingerprints) != 1:
        reasons.append("studies did not use the exact same normalized bars")
    if len(asset_classes) != 1:
        reasons.append("cross-domain profitability is not ranked as one universal winner")
    if len(symbols) != 1:
        reasons.append("studies used different instruments")

    scored = sorted(
        reports,
        key=lambda report: (
            _verdict_rank(report.verdict),
            _comparison_score(report) if report.metrics else -math.inf,
        ),
        reverse=True,
    )
    rankings = [
        ProfitabilityRanking(
            rank=index,
            study_id=report.study_id,
            bot_id=report.bot_id,
            symbol=report.symbol,
            asset_class=report.asset_class,
            verdict=report.verdict,
            score=_comparison_score(report) if report.metrics else None,
        )
        for index, report in enumerate(scored, start=1)
    ]
    winner = scored[0] if comparable and scored and scored[0].verdict == "profitable" else None
    if comparable and winner is None:
        reasons.append("no study passed every profitability gate")
    return ProfitabilityComparisonReport(
        comparison_id=f"profit-compare-{fingerprint[:16]}",
        fingerprint=fingerprint,
        name=request.name,
        studies=reports,
        rankings=rankings,
        winner_study_id=winner.study_id if winner else None,
        winner_bot_id=winner.bot_id if winner else None,
        comparable=comparable,
        comparison_reasons=reasons,
    )


def inspect_data_quality(request: ProfitabilityStudyRequest) -> DataQualityEvidence:
    bars = request.base_request.bars
    payload = [bar.model_dump(mode="json") for bar in bars]
    fingerprint = _fingerprint(payload)
    timestamps = [bar.timestamp for bar in bars]
    unique = len(set(timestamps))
    duplicates = len(timestamps) - unique
    invalid = sum(1 for bar in bars if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or min(bar.open, bar.high, bar.low, bar.close) <= 0)
    mismatches = sum(1 for bar in bars if bar.symbol.upper() != request.base_request.symbol.upper())
    warnings: list[str] = []
    failures: list[str] = []
    required = request.validation.minimum_train_bars + request.validation.folds * request.validation.test_bars_per_fold
    if len(bars) < required:
        failures.append(f"requires at least {required} bars for configured walk-forward evaluation; received {len(bars)}")
    if duplicates:
        failures.append("duplicate timestamps are not allowed in a single-instrument profitability study")
    if invalid:
        failures.append("dataset contains invalid or non-positive OHLC rows")
    if mismatches:
        failures.append("dataset contains bars for a different symbol")
    parsed: list[datetime] = []
    try:
        parsed = [_timestamp(value) for value in timestamps]
    except ValueError as exc:
        failures.append(str(exc))
    if parsed and parsed != sorted(parsed):
        failures.append("bars must be chronologically ordered")
    interval = _median_interval(parsed)
    if interval is None:
        failures.append("dataset needs at least two distinct timestamps")
    volume_coverage = sum(1 for bar in bars if bar.volume > 0) / len(bars) * 100 if bars else 0.0
    if volume_coverage < 80:
        warnings.append("less_than_80_percent_volume_coverage")
    if not request.base_request.metadata.get("dataset_id") and not request.base_request.metadata.get("source_fingerprint"):
        message = "dataset provenance must include metadata.dataset_id or metadata.source_fingerprint"
        if request.validation.require_data_provenance:
            failures.append(message)
        else:
            warnings.append("dataset_provenance_not_linked_in_request_metadata")
    if len({bar.close for bar in bars}) < 3:
        failures.append("dataset has fewer than three distinct closing prices")
    contract_series_type = str(request.base_request.metadata.get("contract_series_type") or "").strip() or None
    if request.base_request.contract.instrument_type == "listed_future":
        if contract_series_type not in {"specific_contract", "continuous_with_explicit_roll"}:
            warnings.append("listed_futures_contract_series_or_roll_policy_is_unverified")
        elif contract_series_type == "continuous_with_explicit_roll" and not request.base_request.metadata.get("roll_policy"):
            warnings.append("continuous_futures_roll_policy_is_missing")
    if request.base_request.contract.instrument_type == "crypto_perpetual":
        fold_ranges = _fold_boundaries(len(bars), request)
        funding_times: list[datetime] = []
        try:
            funding_times = [_timestamp(event.timestamp) for event in request.base_request.funding_events]
        except ValueError as exc:
            failures.append(f"invalid funding timestamp: {exc}")
        uncovered = 0
        for start_index, end_index in fold_ranges:
            fold_start = _timestamp(bars[start_index].timestamp)
            fold_end = _timestamp(bars[end_index - 1].timestamp)
            if not any(fold_start <= item <= fold_end for item in funding_times):
                uncovered += 1
        if not funding_times:
            warnings.append("crypto_perpetual_funding_events_are_missing")
        elif uncovered:
            warnings.append(f"recorded_funding_missing_from_{uncovered}_out_of_sample_folds")
    return DataQualityEvidence(
        passed=not failures,
        fingerprint=fingerprint,
        bar_count=len(bars),
        unique_timestamp_count=unique,
        duplicate_timestamp_count=duplicates,
        invalid_ohlc_count=invalid,
        symbol_mismatch_count=mismatches,
        volume_coverage_pct=volume_coverage,
        funding_event_count=len(request.base_request.funding_events),
        contract_series_type=contract_series_type,
        first_timestamp=timestamps[0] if timestamps else None,
        last_timestamp=timestamps[-1] if timestamps else None,
        median_interval_seconds=interval,
        warnings=warnings,
        failures=failures,
    )


def _execute_folds(
    request: ProfitabilityStudyRequest,
    runtime: StrategyRuntime,
    folds: list[tuple[int, int]],
    costs: BacktestCostModel,
) -> list[_FoldExecution]:
    bars = request.base_request.bars
    results: list[_FoldExecution] = []
    for fold_number, (test_start, test_end) in enumerate(folds, start=1):
        orders = runtime.generate_orders(bars, trade_start=test_start, trade_end=test_end)
        fold_bars = bars[test_start:test_end]
        funding = [
            event
            for event in request.base_request.funding_events
            if fold_bars[0].timestamp <= event.timestamp <= fold_bars[-1].timestamp
        ]
        candidate = request.base_request.model_copy(
            update={
                "bars": fold_bars,
                "funding_events": funding,
                "orders": orders,
                "cost_model": costs,
                "metadata": {
                    **request.base_request.metadata,
                    "profitability_fold": fold_number,
                    "test_start_index": test_start,
                    "test_end_index": test_end,
                },
            }
        )
        report = run_derivatives_backtest(candidate)
        benchmark_request = candidate.model_copy(
            update={
                "bot_id": "reference",
                "orders": _benchmark_orders(fold_bars, candidate.quantity),
                "stop_loss_pct": None,
                "take_profit_pct": None,
                "trailing_stop_pct": None,
            }
        )
        benchmark = run_derivatives_backtest(benchmark_request)
        results.append(
            _FoldExecution(
                fold=fold_number,
                train_start=0,
                train_end=test_start,
                test_start=test_start,
                test_end=test_end,
                report=report,
                benchmark=benchmark,
                period_returns=_period_returns(report),
                benchmark_returns=_period_returns(benchmark),
                generated_order_count=len(orders),
            )
        )
    return results


def _fold_boundaries(total_bars: int, request: ProfitabilityStudyRequest) -> list[tuple[int, int]]:
    validation = request.validation
    required_tests = validation.folds * validation.test_bars_per_fold
    first_test = total_bars - required_tests
    if first_test < validation.minimum_train_bars:
        return []
    return [
        (
            first_test + index * validation.test_bars_per_fold,
            first_test + (index + 1) * validation.test_bars_per_fold,
        )
        for index in range(validation.folds)
    ]


def _benchmark_orders(bars: list[MarketPriceBar], quantity: float) -> list[BacktestOrderIntent]:
    return [
        BacktestOrderIntent(
            order_id=f"benchmark-target-{index:08d}",
            timestamp=bar.timestamp,
            action="target",
            side="long",
            order_type="market",
            quantity=quantity,
        )
        for index, bar in enumerate(bars)
    ]


def _fold_result(item: _FoldExecution, bars: list[MarketPriceBar]) -> ProfitabilityFoldResult:
    return_pct = item.report.metrics.net_pnl / item.report.metrics.starting_equity * 100
    benchmark_pct = item.benchmark.metrics.net_pnl / item.benchmark.metrics.starting_equity * 100
    return ProfitabilityFoldResult(
        fold=item.fold,
        train_start=bars[item.train_start].timestamp,
        train_end=bars[item.train_end - 1].timestamp,
        test_start=item.report.account_curve[0].timestamp if item.report.account_curve else "",
        test_end=item.report.account_curve[-1].timestamp if item.report.account_curve else "",
        test_bar_count=item.test_end - item.test_start,
        run_id=item.report.run_id,
        fingerprint=item.report.fingerprint,
        return_pct=return_pct,
        benchmark_return_pct=benchmark_pct,
        excess_return_pct=return_pct - benchmark_pct,
        closed_trades=_closed_trades(item.report),
        metrics=item.report.metrics,
    )


def _scenario_result(name: str, executions: list[_FoldExecution]) -> ProfitabilityScenarioResult:
    return ProfitabilityScenarioResult(
        name=name,
        compounded_return_pct=_compound_fold_returns(executions),
        maximum_drawdown_pct=_stitched_drawdown(executions),
        closed_trades=sum(_closed_trades(item.report) for item in executions),
        liquidation_count=sum(item.report.metrics.liquidation_count for item in executions),
        potential_debt=max((item.report.metrics.potential_debt for item in executions), default=0.0),
    )


def _aggregate_metrics(
    request: ProfitabilityStudyRequest,
    executions: list[_FoldExecution],
    scenarios: list[ProfitabilityScenarioResult],
    returns: list[float],
    benchmark_returns: list[float],
    periods_per_year: float,
) -> ProfitabilityMetrics:
    bootstrap = _bootstrap_returns(
        returns,
        samples=request.validation.bootstrap_samples,
        block_size=request.validation.bootstrap_block_size,
        confidence=request.validation.confidence_level,
        seed=request.validation.deterministic_seed,
    )
    compounded = _compound_fold_returns(executions)
    benchmark = _compound_returns(benchmark_returns) * 100
    positives = [value for value in returns if value > 0]
    negatives = [value for value in returns if value < 0]
    profit_factor = sum(positives) / abs(sum(negatives)) if negatives else None
    return ProfitabilityMetrics(
        out_of_sample_bars=sum(item.test_end - item.test_start for item in executions),
        closed_trades=sum(_closed_trades(item.report) for item in executions),
        compounded_return_pct=compounded,
        annualized_sharpe_ratio=_sharpe(returns, periods_per_year),
        annualized_sortino_ratio=_sortino(returns, periods_per_year),
        maximum_drawdown_pct=_stitched_drawdown(executions),
        period_win_rate_pct=len(positives) / len(returns) * 100 if returns else 0.0,
        profit_factor=profit_factor,
        benchmark_return_pct=benchmark,
        excess_return_pct=compounded - benchmark,
        bootstrap_return_lower_pct=bootstrap[0] * 100,
        bootstrap_return_median_pct=bootstrap[1] * 100,
        bootstrap_return_upper_pct=bootstrap[2] * 100,
        probability_of_profit=bootstrap[3],
        liquidation_count=sum(item.report.metrics.liquidation_count for item in executions),
        rejection_count=sum(item.report.metrics.rejection_count for item in executions),
        potential_debt=max((item.report.metrics.potential_debt for item in executions), default=0.0),
        worst_cost_stress_return_pct=min((item.compounded_return_pct for item in scenarios), default=compounded),
    )


def _verdict(
    request: ProfitabilityStudyRequest,
    runtime: StrategyRuntime,
    metrics: ProfitabilityMetrics,
) -> tuple[str, list[str]]:
    if metrics.liquidation_count or metrics.potential_debt > 0:
        reasons = []
        if metrics.liquidation_count:
            reasons.append("one or more out-of-sample folds liquidated")
        if metrics.potential_debt > 0:
            reasons.append("simulation produced potential debt")
        return "unsafe", reasons

    negative_reasons: list[str] = []
    if metrics.compounded_return_pct <= 0:
        negative_reasons.append("out-of-sample return was not positive")
    if request.validation.require_positive_cost_stress and metrics.worst_cost_stress_return_pct <= 0:
        negative_reasons.append("at least one required cost stress was not profitable")
    if metrics.bootstrap_return_upper_pct <= 0:
        negative_reasons.append("even the upper bootstrap confidence bound was not positive")
    if negative_reasons:
        return "not_profitable", negative_reasons

    inconclusive: list[str] = []
    if not runtime.evidence.native:
        inconclusive.append("native strategy implementation was not verified")
    elif not runtime.evidence.reproducible:
        inconclusive.append("native strategy repository was dirty or could not be pinned to a source hash and commit")
    if not runtime.evidence.independent_strategy:
        inconclusive.append("Combination result inherits another bot's strategy and is not an independent edge")
    if request.validation.require_positive_cost_stress and not any(
        max(item.fee_multiplier, item.slippage_multiplier, item.spread_multiplier, item.commission_multiplier) > 1
        for item in request.cost_stresses
    ):
        inconclusive.append("no adverse cost scenario was supplied")
    if metrics.out_of_sample_bars < request.validation.minimum_out_of_sample_bars:
        inconclusive.append("too few out-of-sample bars")
    if metrics.closed_trades < request.validation.minimum_closed_trades:
        inconclusive.append("too few closed trades")
    if metrics.bootstrap_return_lower_pct <= 0:
        inconclusive.append("bootstrap lower confidence bound was not positive")
    if metrics.probability_of_profit < request.validation.minimum_probability_of_profit:
        inconclusive.append("probability of profit did not meet the configured threshold")
    if metrics.annualized_sharpe_ratio < request.validation.minimum_sharpe_ratio:
        inconclusive.append("Sharpe ratio did not meet the configured threshold")
    if metrics.maximum_drawdown_pct > request.validation.maximum_drawdown_pct:
        inconclusive.append("maximum drawdown exceeded the configured limit")
    if request.validation.require_benchmark_outperformance and metrics.excess_return_pct <= 0:
        inconclusive.append("strategy did not outperform the identical-cost always-long benchmark")
    if inconclusive:
        return "inconclusive", inconclusive
    return "profitable", ["all configured out-of-sample profitability, risk, confidence, benchmark, and cost-stress gates passed"]


def _base_report(
    request: ProfitabilityStudyRequest,
    study_id: str,
    fingerprint: str,
    data_quality: DataQualityEvidence,
    asset_class: str,
) -> ProfitabilityStudyReport:
    return ProfitabilityStudyReport(
        study_id=study_id,
        fingerprint=fingerprint,
        name=request.name,
        bot_id=request.base_request.bot_id,
        symbol=request.base_request.symbol.upper(),
        asset_class=asset_class,
        verdict="inconclusive",
        data_quality=data_quality,
    )


def _stressed_costs(base: BacktestCostModel, scenario) -> BacktestCostModel:
    return base.model_copy(
        update={
            "fee_bps": base.fee_bps * scenario.fee_multiplier,
            "maker_fee_bps": base.maker_fee_bps * scenario.fee_multiplier if base.maker_fee_bps is not None else None,
            "taker_fee_bps": base.taker_fee_bps * scenario.fee_multiplier if base.taker_fee_bps is not None else None,
            "slippage_bps": base.slippage_bps * scenario.slippage_multiplier,
            "spread_bps": base.spread_bps * scenario.spread_multiplier,
            "commission_per_trade": base.commission_per_trade * scenario.commission_multiplier,
            "commission_per_contract": base.commission_per_contract * scenario.commission_multiplier,
            "exchange_fee_per_contract": base.exchange_fee_per_contract * scenario.commission_multiplier,
        }
    )


def _is_base_stress(scenario) -> bool:
    return all(
        value == 1
        for value in (
            scenario.fee_multiplier,
            scenario.slippage_multiplier,
            scenario.spread_multiplier,
            scenario.commission_multiplier,
        )
    )


def _period_returns(report: DerivativesReport) -> list[float]:
    by_timestamp = {}
    for point in report.account_curve:
        by_timestamp[point.timestamp] = point.equity
    equities = [report.metrics.starting_equity, *by_timestamp.values()]
    returns: list[float] = []
    for previous, current in zip(equities, equities[1:]):
        if previous <= 0:
            break
        returns.append(current / previous - 1)
    return returns


def _closed_trades(report: DerivativesReport) -> int:
    return sum(1 for event in report.executions if event.event_type in {"position_closed", "liquidated"})


def _compound_fold_returns(executions: list[_FoldExecution]) -> float:
    factors = [1 + item.report.metrics.net_pnl / item.report.metrics.starting_equity for item in executions]
    product = math.prod(factors) if factors else 1.0
    return (product - 1) * 100


def _compound_returns(returns: Iterable[float]) -> float:
    return math.prod(1 + value for value in returns) - 1


def _stitched_drawdown(executions: list[_FoldExecution]) -> float:
    equity = 1.0
    peak = 1.0
    maximum = 0.0
    for item in executions:
        for value in item.period_returns:
            equity *= 1 + value
            peak = max(peak, equity)
            if peak > 0:
                maximum = max(maximum, (peak - equity) / peak * 100)
    return maximum


def _sharpe(returns: list[float], periods: float) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = statistics.stdev(returns)
    return statistics.mean(returns) / deviation * math.sqrt(periods) if deviation else 0.0


def _sortino(returns: list[float], periods: float) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [min(0.0, value) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    return statistics.mean(returns) / downside_deviation * math.sqrt(periods) if downside_deviation else 0.0


def _bootstrap_returns(
    returns: list[float],
    *,
    samples: int,
    block_size: int | None,
    confidence: float,
    seed: int,
) -> tuple[float, float, float, float]:
    if not returns:
        return 0.0, 0.0, 0.0, 0.0
    rng = random.Random(seed)
    size = block_size or max(1, int(math.sqrt(len(returns))))
    outcomes: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < len(returns):
            start = rng.randrange(len(returns))
            sample.extend(returns[(start + offset) % len(returns)] for offset in range(size))
        outcomes.append(_compound_returns(sample[: len(returns)]))
    outcomes.sort()
    alpha = (1 - confidence) / 2
    lower = outcomes[min(len(outcomes) - 1, int(alpha * len(outcomes)))]
    median = outcomes[len(outcomes) // 2]
    upper = outcomes[min(len(outcomes) - 1, int((1 - alpha) * len(outcomes)))]
    probability = sum(1 for value in outcomes if value > 0) / len(outcomes)
    return lower, median, upper, probability


def _infer_periods_per_year(bars: list[MarketPriceBar], asset_class: str) -> float:
    parsed = [_timestamp(bar.timestamp) for bar in bars]
    interval = _median_interval(parsed) or 86400
    if interval >= 20 * 3600:
        return 365.0 if asset_class == "crypto_futures" else 252.0
    active_seconds = 365 * 24 * 3600 if asset_class == "crypto_futures" else 252 * 23 * 3600
    return active_seconds / interval


def _median_interval(parsed: list[datetime]) -> float | None:
    differences = [
        (current - previous).total_seconds()
        for previous, current in zip(parsed, parsed[1:])
        if current > previous
    ]
    return statistics.median(differences) if differences else None


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed


def _asset_class(request: DerivativesRunRequest) -> str:
    return "crypto_futures" if request.contract.instrument_type in {"crypto_perpetual", "crypto_delivery"} else "futures"


def _comparison_score(report: ProfitabilityStudyReport) -> float:
    if report.metrics is None:
        return -math.inf
    return (
        report.metrics.excess_return_pct
        + report.metrics.annualized_sharpe_ratio * 2
        - report.metrics.maximum_drawdown_pct * 0.5
    )


def _verdict_rank(verdict: str) -> int:
    return {
        "profitable": 5,
        "inconclusive": 4,
        "not_profitable": 3,
        "insufficient_strategy": 2,
        "insufficient_data": 1,
        "unsafe": 0,
    }.get(verdict, 0)


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
