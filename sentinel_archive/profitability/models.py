from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from sentinel_archive.backtesting.models import DerivativesMetrics, DerivativesRunRequest


StrategyProfile = Literal[
    "iron_trend",
    "iron_volatility_trend",
    "iron_carry",
    "iron_composite",
    "chain_signal_replay",
    "chain_auto_structure",
    "combination_routed",
]
ProfitabilityVerdict = Literal[
    "profitable",
    "not_profitable",
    "inconclusive",
    "unsafe",
    "insufficient_data",
    "insufficient_strategy",
]


class RecordedStrategySignal(BaseModel):
    timestamp: str
    payload: dict[str, Any]


class ProfitabilityStrategyConfig(BaseModel):
    profile: StrategyProfile
    parameters: dict[str, Any] = Field(default_factory=dict)
    repository_path: str | None = None
    require_native: bool = True


class ProfitabilityValidationConfig(BaseModel):
    minimum_train_bars: int = Field(default=120, ge=2)
    test_bars_per_fold: int = Field(default=60, ge=2)
    folds: int = Field(default=3, ge=1, le=20)
    minimum_out_of_sample_bars: int = Field(default=120, ge=2)
    minimum_closed_trades: int = Field(default=20, ge=1)
    bootstrap_samples: int = Field(default=1000, ge=100, le=20000)
    bootstrap_block_size: int | None = Field(default=None, ge=1)
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1)
    minimum_probability_of_profit: float = Field(default=0.95, gt=0.5, le=1)
    minimum_sharpe_ratio: float = 0.5
    maximum_drawdown_pct: float = Field(default=25.0, gt=0, le=100)
    periods_per_year: float | None = Field(default=None, gt=0)
    require_positive_cost_stress: bool = True
    require_benchmark_outperformance: bool = True
    require_data_provenance: bool = False
    deterministic_seed: int = 1729


class ProfitabilityCostStress(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    fee_multiplier: float = Field(default=1.0, ge=0)
    slippage_multiplier: float = Field(default=1.0, ge=0)
    spread_multiplier: float = Field(default=1.0, ge=0)
    commission_multiplier: float = Field(default=1.0, ge=0)


def default_cost_stresses() -> list[ProfitabilityCostStress]:
    return [
        ProfitabilityCostStress(name="base"),
        ProfitabilityCostStress(name="double_fees", fee_multiplier=2, commission_multiplier=2),
        ProfitabilityCostStress(name="triple_slippage", slippage_multiplier=3),
        ProfitabilityCostStress(name="wide_spread", spread_multiplier=3),
    ]


class ProfitabilityStudyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_request: DerivativesRunRequest
    strategy: ProfitabilityStrategyConfig
    signals: list[RecordedStrategySignal] = Field(default_factory=list)
    validation: ProfitabilityValidationConfig = Field(default_factory=ProfitabilityValidationConfig)
    cost_stresses: list[ProfitabilityCostStress] = Field(default_factory=default_cost_stresses, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_base_cost_scenario(self):
        if len({item.name for item in self.cost_stresses}) != len(self.cost_stresses):
            raise ValueError("cost stress scenario names must be unique")
        if not any(
            item.fee_multiplier == item.slippage_multiplier == item.spread_multiplier == item.commission_multiplier == 1
            for item in self.cost_stresses
        ):
            raise ValueError("cost_stresses must contain an unmodified base scenario")
        return self


class DataQualityEvidence(BaseModel):
    passed: bool
    fingerprint: str
    bar_count: int
    unique_timestamp_count: int
    duplicate_timestamp_count: int
    invalid_ohlc_count: int
    symbol_mismatch_count: int
    volume_coverage_pct: float
    funding_event_count: int = 0
    contract_series_type: str | None = None
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    median_interval_seconds: float | None = None
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class StrategyAdapterEvidence(BaseModel):
    adapter_id: str
    strategy_origin: str
    native: bool
    repository_path: str | None = None
    repository_commit: str | None = None
    repository_clean: bool | None = None
    strategy_sha256: str | None = None
    reproducible: bool = False
    dependencies: dict[str, str] = Field(default_factory=dict)
    independent_strategy: bool = True
    order_count: int = 0
    signal_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class ProfitabilityFoldResult(BaseModel):
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    test_bar_count: int
    run_id: str
    fingerprint: str
    return_pct: float
    benchmark_return_pct: float
    excess_return_pct: float
    closed_trades: int
    metrics: DerivativesMetrics


class ProfitabilityScenarioResult(BaseModel):
    name: str
    compounded_return_pct: float
    maximum_drawdown_pct: float
    closed_trades: int
    liquidation_count: int
    potential_debt: float


class ProfitabilityMetrics(BaseModel):
    out_of_sample_bars: int
    closed_trades: int
    compounded_return_pct: float
    annualized_sharpe_ratio: float
    annualized_sortino_ratio: float
    maximum_drawdown_pct: float
    period_win_rate_pct: float
    profit_factor: float | None = None
    benchmark_return_pct: float
    excess_return_pct: float
    bootstrap_return_lower_pct: float
    bootstrap_return_median_pct: float
    bootstrap_return_upper_pct: float
    probability_of_profit: float
    liquidation_count: int
    rejection_count: int
    potential_debt: float
    worst_cost_stress_return_pct: float


class ProfitabilityStudyReport(BaseModel):
    study_id: str
    fingerprint: str
    name: str
    bot_id: str
    symbol: str
    asset_class: str
    verdict: ProfitabilityVerdict
    verdict_reasons: list[str] = Field(default_factory=list)
    data_quality: DataQualityEvidence
    adapter: StrategyAdapterEvidence | None = None
    metrics: ProfitabilityMetrics | None = None
    folds: list[ProfitabilityFoldResult] = Field(default_factory=list)
    scenarios: list[ProfitabilityScenarioResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class ProfitabilityComparisonRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    studies: list[ProfitabilityStudyRequest] = Field(min_length=2, max_length=10)


class ProfitabilityRanking(BaseModel):
    rank: int
    study_id: str
    bot_id: str
    symbol: str
    asset_class: str
    verdict: ProfitabilityVerdict
    score: float | None = None


class ProfitabilityComparisonReport(BaseModel):
    comparison_id: str
    fingerprint: str
    name: str
    studies: list[ProfitabilityStudyReport]
    rankings: list[ProfitabilityRanking]
    winner_study_id: str | None = None
    winner_bot_id: str | None = None
    comparable: bool
    comparison_reasons: list[str] = Field(default_factory=list)
