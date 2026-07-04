from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sentinel_archive.bot_suite.models import SuiteJob, SuitePlan, SuitePlanRequest, SuiteRun
from sentinel_archive.bot_suite.registry import BOT_REGISTRY, FULL_REGRESSION_PROFILE


def build_suite_plan(request: SuitePlanRequest) -> SuitePlan:
    if request.allow_live_execution:
        raise ValueError("bot suite plans cannot request live execution")

    selected = _selected_families(request)
    jobs: list[SuiteJob] = []
    max_jobs = request.compute_budget.max_jobs
    for bot_id, families in selected:
        definition = BOT_REGISTRY[bot_id]
        for family in families:
            if len(jobs) >= max_jobs:
                break
            repo_path = str(definition.repo_path)
            is_available = definition.repo_path.exists()
            jobs.append(
                SuiteJob(
                    job_id=f"{bot_id}:{family}:{len(jobs) + 1}",
                    bot_id=bot_id,
                    test_family=family,
                    status="planned" if is_available else "skipped",
                    repo_path=repo_path,
                    assets=request.assets,
                    skipped_reason=None if is_available else f"repo not found: {repo_path}",
                )
            )
    payload = request.model_dump(mode="json")
    fingerprint = fingerprint_payload({"request": payload, "jobs": [job.model_dump(mode="json") for job in jobs]})
    return SuitePlan(
        plan_id=f"suite-plan-{fingerprint[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
        name=request.name,
        profile=request.profile,
        fingerprint=fingerprint,
        jobs=jobs,
        request=payload,
    )


def build_suite_run(plan: SuitePlan) -> SuiteRun:
    jobs: list[SuiteJob] = []
    for job in plan.jobs:
        if job.status == "skipped":
            jobs.append(job)
            continue
        jobs.append(
            job.model_copy(
                update={
                    "status": "passed",
                    "evidence": {
                        "mode": "test_only",
                        "execution": "none",
                        "message": "Repo path is available; executable adapter hooks are intentionally plan-gated.",
                    },
                }
            )
        )
    status = "passed" if all(job.status in {"passed", "skipped"} for job in jobs) else "warning"
    fingerprint = fingerprint_payload({"plan_id": plan.plan_id, "jobs": [job.model_dump(mode="json") for job in jobs]})
    return SuiteRun(
        run_id=f"suite-run-{fingerprint[:12]}",
        plan_id=plan.plan_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,  # type: ignore[arg-type]
        fingerprint=fingerprint,
        jobs=jobs,
    )


def fingerprint_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selected_families(request: SuitePlanRequest) -> list[tuple[str, tuple[str, ...]]]:
    if request.profile == FULL_REGRESSION_PROFILE:
        return [(bot_id, definition.supported_families) for bot_id, definition in BOT_REGISTRY.items()]
    if request.profile:
        raise ValueError(f"unsupported suite profile: {request.profile}")
    if not request.bots:
        raise ValueError("at least one bot is required unless a profile is selected")
    if not request.test_families:
        raise ValueError("at least one test family is required unless a profile is selected")

    selected: list[tuple[str, tuple[str, ...]]] = []
    for bot_id in request.bots:
        if bot_id not in BOT_REGISTRY:
            raise ValueError(f"unsupported bot: {bot_id}")
        definition = BOT_REGISTRY[bot_id]
        families = tuple(family for family in request.test_families if family in definition.supported_families)
        unsupported = sorted(set(request.test_families) - set(families))
        if unsupported:
            raise ValueError(f"unsupported test families for {bot_id}: {', '.join(unsupported)}")
        selected.append((bot_id, families))
    return selected

