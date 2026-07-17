from __future__ import annotations

import hashlib
import json
from itertools import combinations

from sentinel_archive.backtesting.derivatives import run_derivatives_backtest
from sentinel_archive.backtesting.models import (
    AuditDivergence,
    DifferentialAuditReport,
    DifferentialAuditRequest,
    DerivativesReport,
    ExecutionEvent,
)


TRACE_EVENTS = {
    "filled",
    "partial_fill",
    "rejected",
    "unfilled",
    "position_closed",
    "liquidated",
    "funding",
    "same_bar_ambiguity",
}


def run_differential_audit(request: DifferentialAuditRequest) -> DifferentialAuditReport:
    payload = request.model_dump(mode="json")
    fingerprint = _fingerprint(payload)
    layers: dict[str, DerivativesReport] = {}
    seen: set[str] = set()
    for layer in request.layers:
        if layer.layer_id in seen:
            raise ValueError(f"duplicate audit layer: {layer.layer_id}")
        seen.add(layer.layer_id)
        candidate = request.base_request.model_copy(
            update={
                "bot_id": layer.bot_id,
                "orders": layer.orders,
                "metadata": {**request.base_request.metadata, **layer.metadata, "audit_layer": layer.layer_id},
            }
        )
        layers[layer.layer_id] = run_derivatives_backtest(candidate)

    divergences: list[AuditDivergence] = []
    for left_id, right_id in combinations(layers, 2):
        divergences.extend(
            _compare_layers(
                left_id,
                layers[left_id],
                right_id,
                layers[right_id],
                tick_size=request.base_request.contract.tick_size,
                price_tolerance_ticks=request.event_price_tolerance_ticks,
                pnl_tolerance=request.pnl_tolerance,
            )
        )

    critical = [item for item in divergences if item.severity == "critical"]
    warnings = [item for item in divergences if item.severity == "warning"]
    metrics = [report.metrics for report in layers.values()]
    event_signatures = [_trace_signature(report.executions) for report in layers.values()]
    unanimous = len(set(event_signatures)) == 1
    safety_flags = sorted({flag for report in layers.values() for flag in report.metrics.safety_flags})
    combined = {
        "layer_count": len(layers),
        "unanimous_execution_trace": unanimous,
        "agreement_score": _agreement_score(len(layers), divergences),
        "critical_divergence_count": len(critical),
        "warning_divergence_count": len(warnings),
        "net_pnl_range": [min(item.net_pnl for item in metrics), max(item.net_pnl for item in metrics)],
        "ending_equity_range": [min(item.ending_equity for item in metrics), max(item.ending_equity for item in metrics)],
        "worst_potential_debt": max(item.potential_debt for item in metrics),
        "minimum_safety_score": min(item.safety_score for item in metrics),
        "combined_safety_flags": safety_flags,
        "verdict": _verdict(unanimous, critical, safety_flags),
        "note": "Agreement is evidence of parity, not proof of correctness; shared assumptions can still be wrong.",
    }
    return DifferentialAuditReport(
        audit_id=f"audit-{fingerprint[:16]}",
        fingerprint=fingerprint,
        name=request.name,
        layers=layers,
        divergences=divergences,
        combined_assessment=combined,
    )


def _compare_layers(
    left_id: str,
    left: DerivativesReport,
    right_id: str,
    right: DerivativesReport,
    *,
    tick_size: float,
    price_tolerance_ticks: float,
    pnl_tolerance: float,
) -> list[AuditDivergence]:
    divergences: list[AuditDivergence] = []
    left_trace = [item for item in left.executions if item.event_type in TRACE_EVENTS]
    right_trace = [item for item in right.executions if item.event_type in TRACE_EVENTS]
    max_length = max(len(left_trace), len(right_trace))
    tolerance = tick_size * price_tolerance_ticks
    for index in range(max_length):
        if index >= len(left_trace) or index >= len(right_trace):
            divergences.append(
                AuditDivergence(
                    left_layer=left_id,
                    right_layer=right_id,
                    category="trace_length",
                    first_sequence=index + 1,
                    severity="critical",
                    detail=f"execution trace lengths differ: {len(left_trace)} vs {len(right_trace)}",
                )
            )
            break
        lhs = left_trace[index]
        rhs = right_trace[index]
        if _event_identity(lhs) != _event_identity(rhs):
            divergences.append(
                AuditDivergence(
                    left_layer=left_id,
                    right_layer=right_id,
                    category="execution_event",
                    first_sequence=index + 1,
                    severity="critical",
                    detail=f"{_event_identity(lhs)} != {_event_identity(rhs)}",
                )
            )
            break
        if lhs.price is not None and rhs.price is not None and abs(lhs.price - rhs.price) > tolerance:
            divergences.append(
                AuditDivergence(
                    left_layer=left_id,
                    right_layer=right_id,
                    category="execution_price",
                    first_sequence=index + 1,
                    severity="warning",
                    detail=f"fill prices differ by {abs(lhs.price - rhs.price):.8f}, tolerance {tolerance:.8f}",
                )
            )
            break

    pnl_delta = abs(left.metrics.net_pnl - right.metrics.net_pnl)
    if pnl_delta > pnl_tolerance:
        divergences.append(
            AuditDivergence(
                left_layer=left_id,
                right_layer=right_id,
                category="net_pnl",
                severity="critical" if pnl_delta > max(1.0, abs(left.metrics.net_pnl) * 0.05) else "warning",
                detail=f"net P&L differs by {pnl_delta:.8f}",
            )
        )
    if left.metrics.liquidation_count != right.metrics.liquidation_count:
        divergences.append(
            AuditDivergence(
                left_layer=left_id,
                right_layer=right_id,
                category="liquidation",
                severity="critical",
                detail=f"liquidation counts differ: {left.metrics.liquidation_count} vs {right.metrics.liquidation_count}",
            )
        )
    if left.metrics.rejection_count != right.metrics.rejection_count:
        divergences.append(
            AuditDivergence(
                left_layer=left_id,
                right_layer=right_id,
                category="rejections",
                severity="warning",
                detail=f"rejection counts differ: {left.metrics.rejection_count} vs {right.metrics.rejection_count}",
            )
        )
    return divergences


def _event_identity(event: ExecutionEvent) -> tuple:
    return (
        event.event_type,
        event.timestamp,
        event.side,
        round(event.filled_quantity, 12),
        event.reason,
    )


def _trace_signature(events: list[ExecutionEvent]) -> str:
    payload = [_event_identity(event) for event in events if event.event_type in TRACE_EVENTS]
    return _fingerprint(payload)


def _agreement_score(layer_count: int, divergences: list[AuditDivergence]) -> float:
    pair_count = max(1, layer_count * (layer_count - 1) // 2)
    penalty = sum(30 if item.severity == "critical" else 10 if item.severity == "warning" else 2 for item in divergences)
    return max(0.0, 100.0 - penalty / pair_count)


def _verdict(unanimous: bool, critical: list[AuditDivergence], safety_flags: list[str]) -> str:
    if "potential_debt" in safety_flags or "liquidated" in safety_flags:
        return "unsafe"
    if critical:
        return "investigate_divergence"
    if unanimous:
        return "parity_observed"
    return "review_required"


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
