from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotDefinition:
    bot_id: str
    repo_path: Path
    supported_families: tuple[str, ...]


GITBOTS_ROOT = Path("C:/Users/automation/GitBots")


BOT_REGISTRY: dict[str, BotDefinition] = {
    "chain": BotDefinition(
        bot_id="chain",
        repo_path=GITBOTS_ROOT / "Sentinel-Chain",
        supported_families=("crypto_backtest", "sweep", "walk_forward", "stress", "artifact_import"),
    ),
    "edge": BotDefinition(
        bot_id="edge",
        repo_path=GITBOTS_ROOT / "Sentinel-Edge",
        supported_families=("monte_carlo", "drift", "readiness", "stop_trailing_dca", "orb_backtest", "artifact_import"),
    ),
    "pulse": BotDefinition(
        bot_id="pulse",
        repo_path=GITBOTS_ROOT / "Sentinel-Pulse",
        supported_families=("replay_health", "paper_engine", "market_hours_engine", "artifact_import"),
    ),
    "echo": BotDefinition(
        bot_id="echo",
        repo_path=GITBOTS_ROOT / "Sentinel-Echo",
        supported_families=("options_replay", "parser_preview", "paper_shadow", "artifact_import"),
    ),
    "flare": BotDefinition(
        bot_id="flare",
        repo_path=GITBOTS_ROOT / "Sentinel-Flare",
        supported_families=("darkpool_followthrough", "risk_envelope", "artifact_import"),
    ),
    "iron": BotDefinition(
        bot_id="iron",
        repo_path=GITBOTS_ROOT / "Sentinel-Iron",
        supported_families=("futures_risk_readiness", "margin_readiness", "artifact_import"),
    ),
    "core": BotDefinition(
        bot_id="core",
        repo_path=GITBOTS_ROOT / "Sentinel-Core",
        supported_families=("operator_readiness", "artifact_import"),
    ),
    "nexus": BotDefinition(
        bot_id="nexus",
        repo_path=GITBOTS_ROOT / "Sentinel-Nexus",
        supported_families=("mobile_control_health", "artifact_import"),
    ),
    "link": BotDefinition(
        bot_id="link",
        repo_path=GITBOTS_ROOT / "Sentinel-Link",
        supported_families=("discord_bridge_health", "artifact_import"),
    ),
}


FULL_REGRESSION_PROFILE = "all-bots/full-regression"
