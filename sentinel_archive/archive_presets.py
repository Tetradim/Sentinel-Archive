from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException


PRESET_CATALOG: dict[str, list[dict[str, Any]]] = {
    "strategies": [
        {
            "id": "crypto-momentum-guarded",
            "name": "Crypto Momentum Guarded",
            "description": "Long/short crypto replay with modest leverage, explicit stop, target, funding, fees, and simplified liquidation guardrails.",
            "asset_class": "crypto",
            "request": {
                "asset_class": "crypto",
                "symbol": "BTCUSDT",
                "side": "long",
                "quantity": 0.05,
                "starting_equity": 10000,
                "leverage": 3,
                "stop_loss_pct": 2.5,
                "take_profit_pct": 5.0,
                "trailing_stop_pct": 1.6,
                "cost_model": {
                    "fee_bps": 4,
                    "slippage_bps": 3,
                    "funding_bps_per_step": 0.5,
                    "commission_per_trade": 0,
                    "option_fill_price": "mid",
                    "option_multiplier": 100,
                },
            },
            "labels": ["crypto", "liquidation-check", "paper-only"],
        },
        {
            "id": "stock-orb-long-only",
            "name": "Stock ORB Long-only",
            "description": "Stock engine preset that keeps the current long-only assumption visible until short support is added to the report model.",
            "asset_class": "stock",
            "request": {
                "asset_class": "stock",
                "symbol": "SPY",
                "side": "long",
                "quantity": 10,
                "starting_equity": 25000,
                "leverage": 1,
                "stop_loss_pct": 1.2,
                "take_profit_pct": 2.4,
                "trailing_stop_pct": 0.8,
                "cost_model": {
                    "fee_bps": 0,
                    "slippage_bps": 1,
                    "funding_bps_per_step": 0,
                    "commission_per_trade": 0,
                    "option_fill_price": "mid",
                    "option_multiplier": 100,
                },
            },
            "labels": ["stocks", "long-only", "orb"],
        },
        {
            "id": "options-alert-replay-mid",
            "name": "Options Alert Replay / Mid Fill",
            "description": "Alert replay preset with explicit quote/fill assumptions. This is not a full options pricing model.",
            "asset_class": "options",
            "request": {
                "asset_class": "options",
                "symbol": "SPY",
                "side": "long",
                "quantity": 1,
                "starting_equity": 5000,
                "leverage": 1,
                "stop_loss_pct": None,
                "take_profit_pct": None,
                "trailing_stop_pct": None,
                "cost_model": {
                    "fee_bps": 0,
                    "slippage_bps": 0,
                    "funding_bps_per_step": 0,
                    "commission_per_trade": 0.65,
                    "option_fill_price": "mid",
                    "option_multiplier": 100,
                },
            },
            "labels": ["options", "alert-replay", "assumption-led"],
        },
    ],
    "brackets": [
        {"id": "tight-scalp", "name": "Tight Scalp", "stop_loss_pct": 0.8, "take_profit_pct": 1.6, "trailing_stop_pct": 0.5},
        {"id": "balanced-2r", "name": "Balanced 2R", "stop_loss_pct": 2.0, "take_profit_pct": 4.0, "trailing_stop_pct": 1.25},
        {"id": "swing-wide", "name": "Swing Wide", "stop_loss_pct": 5.0, "take_profit_pct": 10.0, "trailing_stop_pct": 3.0},
    ],
    "risk": [
        {"id": "capital-preservation", "name": "Capital Preservation", "starting_equity": 10000, "quantity": 1, "leverage": 1, "max_jobs": 12},
        {"id": "normal-regression", "name": "Normal Regression", "starting_equity": 25000, "quantity": 5, "leverage": 2, "max_jobs": 25},
        {"id": "stress-lab", "name": "Stress Lab", "starting_equity": 50000, "quantity": 10, "leverage": 5, "max_jobs": 50},
    ],
    "cost_models": [
        {
            "id": "zero-cost-lab",
            "name": "Zero-cost Lab",
            "cost_model": {"fee_bps": 0, "slippage_bps": 0, "funding_bps_per_step": 0, "commission_per_trade": 0, "option_fill_price": "mid", "option_multiplier": 100},
        },
        {
            "id": "retail-stock-options",
            "name": "Retail Stock/Options",
            "cost_model": {"fee_bps": 0, "slippage_bps": 2, "funding_bps_per_step": 0, "commission_per_trade": 0.65, "option_fill_price": "mid", "option_multiplier": 100},
        },
        {
            "id": "crypto-perp-active",
            "name": "Crypto Perp Active",
            "cost_model": {"fee_bps": 4, "slippage_bps": 5, "funding_bps_per_step": 0.5, "commission_per_trade": 0, "option_fill_price": "mid", "option_multiplier": 100},
        },
    ],
    "suite_profiles": [
        {
            "id": "all-bots/full-regression",
            "name": "All Bots / Full Regression",
            "description": "Plans every registered bot/test family within the selected compute budget.",
            "profile": "all-bots/full-regression",
            "compute_budget": {"max_jobs": 25, "priority": "normal"},
        },
        {
            "id": "echo-options-replay",
            "name": "Echo Options Replay",
            "description": "Focused options parser and paper-shadow evidence bundle.",
            "bots": ["echo"],
            "test_families": ["options_replay", "parser_preview", "paper_shadow", "artifact_import"],
            "compute_budget": {"max_jobs": 8, "priority": "normal"},
        },
        {
            "id": "chain-risk-sweep",
            "name": "Chain Risk Sweep",
            "description": "Focused crypto sweep, walk-forward, stress, and artifact import evidence bundle.",
            "bots": ["chain"],
            "test_families": ["crypto_backtest", "sweep", "walk_forward", "stress", "artifact_import"],
            "compute_budget": {"max_jobs": 10, "priority": "high"},
        },
    ],
}


def create_archive_presets_router() -> APIRouter:
    router = APIRouter(prefix="/archive/presets", tags=["archive-presets"])

    @router.get("")
    async def get_catalog():
        return deepcopy(PRESET_CATALOG)

    @router.get("/{category}")
    async def get_category(category: str):
        normalized = category.replace("-", "_")
        if normalized not in PRESET_CATALOG:
            raise HTTPException(status_code=404, detail=f"Preset category '{category}' not found")
        return {normalized: deepcopy(PRESET_CATALOG[normalized])}

    return router
