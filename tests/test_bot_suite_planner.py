from __future__ import annotations

import pytest


def test_plan_expands_only_selected_bots_and_test_families():
    from sentinel_archive.bot_suite.models import SuitePlanRequest
    from sentinel_archive.bot_suite.planner import build_suite_plan

    plan = build_suite_plan(
        SuitePlanRequest(
            name="focused crypto",
            bots=["chain"],
            test_families=["crypto_backtest"],
            assets=["BTCUSDT"],
            compute_budget={"max_jobs": 5},
        )
    )

    assert [job.bot_id for job in plan.jobs] == ["chain"]
    assert [job.test_family for job in plan.jobs] == ["crypto_backtest"]


def test_full_regression_requires_explicit_profile():
    from sentinel_archive.bot_suite.models import SuitePlanRequest
    from sentinel_archive.bot_suite.planner import build_suite_plan

    targeted = build_suite_plan(SuitePlanRequest(name="targeted", bots=["chain"], test_families=["crypto_backtest"]))
    full = build_suite_plan(SuitePlanRequest(name="full", profile="all-bots/full-regression"))

    assert len(targeted.jobs) < len(full.jobs)
    assert {job.bot_id for job in full.jobs} >= {"chain", "edge", "pulse", "echo"}


def test_live_execution_is_rejected():
    from sentinel_archive.bot_suite.models import SuitePlanRequest
    from sentinel_archive.bot_suite.planner import build_suite_plan

    with pytest.raises(ValueError, match="live execution"):
        build_suite_plan(
            SuitePlanRequest(
                name="bad",
                bots=["chain"],
                test_families=["crypto_backtest"],
                allow_live_execution=True,
            )
        )


def test_repeated_suite_runs_keep_history_with_same_fingerprint():
    from sentinel_archive.bot_suite.models import SuitePlanRequest
    from sentinel_archive.bot_suite.planner import build_suite_plan, build_suite_run

    plan = build_suite_plan(
        SuitePlanRequest(
            name="focused crypto",
            bots=["chain"],
            test_families=["crypto_backtest"],
        )
    )

    first = build_suite_run(plan)
    second = build_suite_run(plan)

    assert first.fingerprint == second.fingerprint
    assert first.run_id != second.run_id
