from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SuiteJobStatus = Literal["planned", "skipped", "passed", "warning", "failed"]


class SuiteComputeBudget(BaseModel):
    max_jobs: int = Field(default=25, gt=0)
    max_runtime_seconds: int | None = Field(default=None, gt=0)
    priority: Literal["low", "normal", "high"] = "normal"


class SuitePlanRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    profile: str | None = None
    bots: list[str] = Field(default_factory=list)
    test_families: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    timeframe: str | None = None
    date_range: dict[str, str] = Field(default_factory=dict)
    strategy_presets: list[str] = Field(default_factory=list)
    bracket_presets: list[str] = Field(default_factory=list)
    risk_presets: list[str] = Field(default_factory=list)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    compute_budget: SuiteComputeBudget = Field(default_factory=SuiteComputeBudget)
    schedule: dict[str, Any] = Field(default_factory=dict)
    change_triggers: list[str] = Field(default_factory=list)
    allow_live_execution: bool = False
    required_bots: list[str] = Field(default_factory=list)


class SuiteJob(BaseModel):
    job_id: str
    bot_id: str
    test_family: str
    status: SuiteJobStatus = "planned"
    repo_path: str | None = None
    assets: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class SuitePlan(BaseModel):
    plan_id: str
    created_at: str
    name: str
    profile: str | None = None
    fingerprint: str
    jobs: list[SuiteJob]
    request: dict[str, Any] = Field(default_factory=dict)


class SuiteRun(BaseModel):
    run_id: str
    plan_id: str
    created_at: str
    status: SuiteJobStatus
    fingerprint: str
    jobs: list[SuiteJob]

