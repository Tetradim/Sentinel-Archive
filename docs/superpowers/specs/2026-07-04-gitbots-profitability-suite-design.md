# GitBots Profitability Suite Design

Date: 2026-07-04
Target repo: Sentinel-Archive
Approved direction: Archive-primary, backend-first, modular kernel with selective run planning.

## Purpose

Sentinel Archive will become the command center for testing, backtesting, and profitability evidence across the GitBots suite without turning every bot into a coupled monolith. Archive owns the canonical backend contract: datasets, run plans, backtest runs, suite runs, saved history, reports, exports, safety rankings, and later UI data.

Other bots remain specialized. Archive integrates their useful testing and profitability capabilities through local adapters, imported artifacts, or safe read-only health/status checks. Repo-specific code changes are reserved for cases where a bot cannot expose the needed evidence any other way.

The UI is intentionally deferred until the backend contract is stable. This prevents a fragmented interface and lets the later workbench be designed around complete user workflows.

## Non-Negotiable Constraints

- Backtesting and bot-suite testing must not expose a live execution path.
- Full all-bots regression is available only as an explicit run profile.
- Default runs must be targeted and compute-aware.
- Results must be persisted so users can compare runs over time.
- Every run must record enough assumptions to be reproducible.
- Archive should be useful even if only one bot adapter or one asset-class engine is available.
- Existing user changes in other repos must not be overwritten.

## System Shape

The backend is split into two related subsystems:

1. `sentinel_archive.backtesting`
   - Owns datasets, asset-class engines, sweeps, walk-forward tests, stress scenarios, metrics, safety ranking, and export payloads.
   - Implements first-class crypto, stock, and options backtesting inside Archive.
   - Ports Sentinel Chain's crypto backtest concepts into Archive rather than importing Chain at runtime.

2. `sentinel_archive.bot_suite`
   - Owns selective run plans, bot adapters, test family selection, schedule metadata, run budgeting, and artifact normalization.
   - Imports useful evidence from Edge, Pulse, Echo, Flare, Iron, Core, Nexus, Link, and Chain.
   - Produces canonical suite-run records that the future UI can display next to backtest runs.

Both subsystems share a persistence layer and a common report model.

## Backend Module Layout

```text
sentinel_archive/
  backtesting/
    __init__.py
    models.py
    datasets.py
    metrics.py
    ranking.py
    sweeps.py
    walk_forward.py
    stress.py
    exports.py
    store.py
    router.py
    engines/
      __init__.py
      crypto.py
      stocks.py
      options.py
      darkpool.py
      futures_risk.py
  bot_suite/
    __init__.py
    models.py
    planner.py
    registry.py
    store.py
    router.py
    artifacts.py
    adapters/
      __init__.py
      chain.py
      edge.py
      pulse.py
      echo.py
      flare.py
      iron.py
      core.py
      nexus.py
      link.py
```

If implementation shows that `backtesting.store` and `bot_suite.store` duplicate persistence concerns, they should use one shared store module with separate tables and schema functions.

## API Contract

Archive should expose routes under the existing `/api` namespace:

```text
POST /api/archive/backtest/runs
POST /api/archive/backtest/sweeps
POST /api/archive/backtest/walk-forward
POST /api/archive/backtest/stress
GET  /api/archive/backtest/runs
GET  /api/archive/backtest/runs/{run_id}
GET  /api/archive/backtest/runs/{run_id}/export.json
GET  /api/archive/backtest/runs/{run_id}/export.csv

POST /api/archive/bot-suite/plans
GET  /api/archive/bot-suite/plans
GET  /api/archive/bot-suite/plans/{plan_id}
POST /api/archive/bot-suite/plans/{plan_id}/run
GET  /api/archive/bot-suite/runs
GET  /api/archive/bot-suite/runs/{run_id}
GET  /api/archive/bot-suite/runs/{run_id}/export.json
```

The user originally named routes without `/api`; Archive's current API uses `/api`, so the canonical routes should use `/api/archive/...`. Compatibility aliases without `/api` can be added later if a consumer requires them.

## Selective Run Planner

The run planner is a first-class backend component, not a UI convenience. A plan declares what should run, why, and under which budget.

Plan inputs:

- `name`
- `description`
- `bots`: selected bot ids such as `chain`, `edge`, `pulse`, `echo`, `flare`, `iron`, `core`, `nexus`, `link`
- `test_families`: selected families such as `crypto_backtest`, `stock_backtest`, `options_replay`, `walk_forward`, `sweep`, `stress`, `monte_carlo`, `drift`, `readiness`, `artifact_import`
- `assets`: symbols, option contracts, markets, exchanges, or datasets
- `timeframe`
- `date_range`
- `strategy_presets`
- `bracket_presets`
- `risk_presets`
- `cost_model`: fees, slippage, funding, commissions, bid/ask assumptions
- `compute_budget`: max runtime seconds, max scenarios, max parallel jobs, priority
- `schedule`: manual, nightly, weekly, or change-triggered metadata
- `change_triggers`: repo changed, dataset changed, strategy changed, or risk preset changed

Planner behavior:

- Expand a plan into concrete jobs only for the selected bots and test families.
- Skip unavailable adapters and record clear skipped reasons.
- Reject plans that imply live execution.
- Enforce compute budgets before job execution.
- Produce a deterministic fingerprint for plan inputs and resolved jobs.
- Treat `all-bots/full-regression` as an explicit profile, never as the default.

Example targeted profiles:

```text
chain/crypto-sweep
chain/crypto-walk-forward
echo/options-alert-replay
pulse/replay-health
edge/monte-carlo-risk
edge/stop-trailing-dca-compare
flare/darkpool-followthrough
iron/futures-risk-readiness
core/operator-readiness
link/discord-bridge-health
all-bots/full-regression
```

## Backtesting Engines

### Crypto Engine

The crypto engine ports the Sentinel Chain backtest behavior into Archive-owned code:

- signal and candle path backtests
- long and short support
- fees, slippage, and funding assumptions
- leverage and liquidation-before-stop checks
- stop loss, take profit, trailing stop, staged take-profit concepts
- forced final close option
- stress scenario runs
- MAE and MFE
- realized, unrealized, and total PnL
- max drawdown, win rate, profit factor, average win/loss

Archive should not mutate a live Chain engine. The port should use isolated data models and pure calculations.

### Stock Engine

The stock engine uses Archive market bars and imported CSV/replay datasets:

- long-only first, with a clear extension point for short support
- entry and exit rules based on strategy presets
- stop loss, take profit, trailing stop, DCA, and time stop support
- commissions and slippage
- position sizing by fixed quantity, cash allocation, or risk percent
- benchmark comparison when benchmark bars are supplied

### Options Engine

The options engine starts with alert replay and historical quote assumptions:

- replay Echo-style parsed option alerts
- use bid, ask, mid, last, or configured fill assumption
- track contract metadata: underlying, expiration, strike, call/put
- model entry, scale-out, stop, target, expiration, and time-stop exits
- flag missing quote coverage and stale quote assumptions
- report per-contract and per-alert-family performance

The first implementation does not need a full options pricing model. It should make fill assumptions explicit and persist them with each run.

### Dark-Pool and Futures-Risk Engines

These are lightweight engines for profitability and readiness evidence:

- Flare-style dark-pool print follow-through sanity checks
- Iron-style futures risk and margin estimate checks
- no live broker calls
- clear warnings when data is too thin for a reliable conclusion

## Metrics and Ranking

Every backtest report should include:

- starting equity
- ending equity
- realized PnL
- unrealized PnL
- total PnL
- total return percent
- win rate
- trade count
- gross profit
- gross loss
- profit factor
- maximum drawdown
- MAE
- MFE
- average win
- average loss
- fees
- slippage
- funding
- stop/target/trailing outcomes
- data coverage warnings
- safety flags

Safe-vs-unsafe ranking should combine profitability and risk. The ranking model should penalize:

- liquidation before stop
- max drawdown above threshold
- poor profit factor
- too few trades
- missing data coverage
- excessive slippage sensitivity
- daily loss threshold breach
- strategy instability across walk-forward windows

The initial score can be deterministic and simple. It must expose its inputs so users can understand why a run ranked well or poorly.

## Persistence

Saved records should be stored locally with stable ids and deterministic fingerprints:

- datasets
- backtest runs
- sweep runs
- walk-forward runs
- stress runs
- suite plans
- suite runs
- normalized artifacts
- export metadata

SQLite is the preferred persistence target for the new suite data because Archive already has local-first behavior and the records need queryable history. If the current Archive persistence layer already offers a simpler durable JSON path for a specific artifact type, implementation can reuse it for that artifact while keeping the public store interface stable.

## Bot Adapter Responsibilities

Adapters should be thin and safe:

- locate local repo paths
- read known test artifacts
- call safe local status endpoints when available
- run explicitly allowed test commands only when a plan requests them
- normalize results into Archive suite-run artifacts
- mark skipped, failed, passed, or warning states
- avoid changing bot configuration unless a future plan explicitly adds that capability

Initial adapter map:

- Chain: crypto backtest concepts and strategy/risk presets
- Edge: simulation lab concepts, Monte Carlo risk, drift detection, stop/trailing/DCA comparison
- Pulse: replay health, paper-engine evidence, all-bots Playwright artifact import
- Echo: options alert replay, parser preview evidence, paper shadow artifacts
- Flare: dark-pool follow-through and risk-envelope evidence
- Iron: futures readiness, margin/risk estimates, kill-switch style checks
- Core: operator console readiness and event visibility checks
- Nexus: mobile-control health/evidence imports
- Link: Chrome/Discord bridge queue and delivery health evidence

## Error Handling

- Invalid asset class, bot id, test family, or preset returns a 422-style validation error.
- Missing datasets or artifacts return a clear not-found response.
- Unavailable bot repos produce skipped adapter results, not whole-suite failure, unless the plan marks them required.
- Budget overruns stop pending jobs and mark the run as budget-limited.
- Any request that attempts live execution is rejected before job creation.
- Partial failures are persisted with their trace summary and do not erase successful job results.

## Testing Strategy

Implementation should use test-first development.

Initial tests:

- run planner expands only selected bots and test families
- full-regression does not run unless explicitly requested
- planner records skipped reasons for unavailable adapters
- live execution flags are rejected
- crypto backtest computes PnL, win rate, profit factor, drawdown, MAE, MFE, fees, and funding
- crypto liquidation-before-stop is flagged
- stock backtest supports stops, targets, and slippage
- options replay records missing quote coverage and fill assumptions
- sweep ranks safe results above unsafe results when profitability is similar
- walk-forward stores separate train/test windows
- API creates and retrieves saved runs
- API exports JSON and CSV payloads

Existing Archive tests should continue to pass.

## Milestones

### Milestone 1: Backend Kernel Foundation

- Add backtesting models, metrics, ranking, store, and router.
- Add bot-suite plan models, planner, registry, store, and router.
- Add persistence for saved run history.
- Add tests for selective run planning and persistence.

### Milestone 2: Core Backtest Engines

- Port Chain-style crypto backtesting into Archive.
- Add stock backtesting over Archive market bars and CSV-style datasets.
- Add options alert replay over Echo/Archive-style option records.
- Add sweep, stress, and walk-forward orchestration.

### Milestone 3: Bot Adapters and Evidence Imports

- Add safe adapters and artifact importers for the selected GitBots.
- Add targeted suite profiles.
- Add compute budgets, skipped reasons, and run fingerprints.

### Milestone 4: Backend Reports and Exports

- Normalize JSON and CSV exports.
- Add ranking details and safety flags.
- Add report payloads designed for the later UI.

### Milestone 5: UI Workbench

- Build the Archive UI after the backend model is stable.
- Design around user workflows: plan builder, dataset selection, run history, report comparison, sweep/walk-forward views, safety ranking, artifacts, and exports.
- Avoid incremental feature patches that make the interface feel assembled rather than designed.

## Open Decisions Resolved

- Archive is the primary repo and command center.
- Other repos are integrated through adapters and artifacts unless a repo-specific change is unavoidable.
- Backend comes before UI.
- Selective run planning is required to avoid wasting compute.
- The suite can run all bots, but only through an explicit full-regression profile.

