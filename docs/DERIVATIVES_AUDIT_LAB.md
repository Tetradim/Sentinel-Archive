# Sentinel Archive Derivatives Audit Lab

Archive is deliberately brokerless. It consumes recorded market data and bot order intents, simulates execution, and preserves enough evidence to compare Iron, Chain, and Combination without risking a real account.

No backtest can prove a futures bot is safe. Bar data cannot reveal the exact order book, queue position, exchange intervention, broker risk controls, or every intrabar price path. Archive therefore records assumptions and treats agreement between engines as parity evidence—not proof of correctness.

## What the engine models

| Risk or execution behavior | Archive evidence |
| --- | --- |
| Leverage and initial margin | Contract margin schedule, requested leverage, reserved margin, available margin, insufficient-margin rejection. |
| Maintenance and liquidation | Per-bar maintenance requirement, isolated/cross liquidation approximation, gap liquidation, liquidation fee, margin-call count. |
| Account loss beyond equity | Negative wallet/equity is retained as `potential_debt`; it is never clipped to zero. |
| Costs | Maker/taker or generic basis-point fee, flat trade commission, per-contract commission, per-contract exchange fee, funding, liquidation fee. |
| Spread and slippage | Recorded bid/ask when supplied; otherwise a configured synthetic spread. Slippage scales with volume participation and rounds against the trader to the next tick. |
| Liquidity | Maximum bar-volume participation, quantity steps, minimum/maximum quantity, partial fill, IOC remainder cancellation, FOK rejection, missing-volume rejection policy. |
| Contract economics | Venue, instrument type, multiplier, tick size, quantity step, margin rates, maximum leverage, settlement metadata. |
| Protective orders | Stop loss, profit target, trailing stop, automatic bracket/OCO cancellation evidence, explicit close orders. |
| Gaps and ambiguous bars | Configurable gap-through-stop fill and same-bar policies: adverse first, favorable first, OHLC path assumptions, or defer ambiguous execution. |
| Rejected and unfilled orders | Structured execution events with reason, requested/filled/remaining quantity, and order ID. |
| Comparable replay | Canonical JSON fingerprints, deterministic run IDs, ordered execution traces, account curves, and pairwise divergence records. |

## Three-layer audit

`POST /api/archive/derivatives/compare` runs two or more independent layers against the same base request. A typical request supplies Iron, Chain, and Combination order streams. Archive compares:

- execution event identity and first differing sequence;
- fill prices within a configurable tick tolerance;
- net P&L within a configurable currency tolerance;
- liquidation and rejection counts;
- ending equity, debt, flags, and minimum safety score.

The combined layer returns `parity_observed`, `review_required`, `investigate_divergence`, or `unsafe`. A parity verdict only means the submitted order streams behaved the same under the submitted assumptions.

## Market data sources

`GET /api/archive/market-data/providers` returns the live catalog and limitations.

| Adapter | Access | Intended use |
| --- | --- | --- |
| yfinance | No key | Early stock, ETF, crypto, and continuous-futures research. Unofficial and not execution truth. |
| Stooq | No key | Daily stock/futures cross-checks. |
| Alpaca IEX | Free key | US stock/ETF bars from the IEX feed; not consolidated SIP volume. |
| Alpha Vantage | Free key | Rate-limited stock/crypto intraday or daily cross-check. |
| Twelve Data | Free key | Credit-limited stock/crypto bars. |
| Binance Futures | Public | Trade, mark, or index klines plus funding history for Binance contracts. |
| Bybit Futures | Public | Trade, mark, or index klines plus funding history for Bybit contracts. |
| BitUnix Futures | Public | BitUnix futures klines; the adapter exposes the venue's per-request limit as a warning. |
| Coinbase Exchange | Public | Crypto spot candles for basis/reference comparisons, not futures fills. |
| Local dataset | No key | Existing Archive CSV import or direct dataset API for licensed, exported, or operator-recorded data. |

Every fetched result receives a SHA-256 fingerprint over normalized bars and funding events. When `save_dataset` is true, Archive stores the result in SQLite and returns a `dataset_id`. Provider credentials are accepted for the request but excluded from serialized models and dataset metadata.

Free data is useful for development and broad behavioral tests. Before treating a result as futures evidence, verify that the dataset reflects the correct venue, contract month or perpetual, session, timezone, roll method, price type, and funding schedule. Listed-futures audits usually need licensed historical depth for serious fill analysis.

## API workflow

1. Inspect providers and contract research templates:

   ```text
   GET /api/archive/market-data/providers
   GET /api/archive/derivatives/contracts
   ```

2. Fetch and save a dataset:

   ```json
   POST /api/archive/market-data/fetch
   {
     "provider": "binance_futures",
     "symbol": "BTCUSDT",
     "asset_class": "crypto_futures",
     "interval": "5m",
     "start": "2026-07-01T00:00:00Z",
     "end": "2026-07-02T00:00:00Z",
     "price_type": "trade",
     "include_funding": true,
     "save_dataset": true
   }
   ```

3. Submit the normalized bars and funding events to one bot audit:

   ```text
   POST /api/archive/derivatives/run
   ```

4. Submit a base request and bot-specific order lists to the differential audit:

   ```json
   POST /api/archive/derivatives/compare
   {
     "name": "Iron Chain Combination recorded-day replay",
     "base_request": { "...": "same DerivativesRunRequest for every layer" },
     "layers": [
       { "layer_id": "iron", "label": "Iron", "bot_id": "iron", "orders": [] },
       { "layer_id": "chain", "label": "Chain", "bot_id": "chain", "orders": [] },
       { "layer_id": "combination", "label": "Combination", "bot_id": "combination", "orders": [] }
     ]
   }
   ```

5. Retrieve deterministic evidence:

   ```text
   GET /api/archive/derivatives/runs
   GET /api/archive/derivatives/runs/{run_id}
   ```

## Contract templates

The built-in ES, MES, NQ, MNQ, CL, MCL, and BTCUSDT entries are editable research defaults, not current broker margin quotes. Contract specifications and broker margins change. Save the exact verified contract snapshot in the request so a future replay retains the assumptions used at the time.

## Known conservative boundaries

- Linear P&L is used for inverse contracts and receives an explicit safety warning.
- OHLCV bars cannot reconstruct order-book queue position or the true intrabar path.
- A GTC limit/stop waits across bars until its first fill; a liquidity-limited remainder is cancelled and flagged because the simulator currently holds one aggregate position per instrument.
- Stop-limit fills require both the stop and limit to be reachable in the same bar; this is a bar-path approximation.
- Listed-futures variation settlement and changing intraday/overnight broker margin schedules are not inferred. Represent the verified schedule in the saved contract request or split the replay into separately configured sessions.
- Contract rollover, back-adjustment, and continuous-symbol construction remain data-preparation responsibilities and must be recorded in dataset metadata.

## Recommended release gate

Do not connect a futures bot merely because it is profitable. Require, at minimum:

- deterministic repeated results on the same immutable dataset;
- no unexplained Iron/Chain/Combination divergence;
- successful adverse-first and gap stress cases;
- bounded loss with fees, spread, slippage, funding, and partial fills enabled;
- no unhandled rejection, open position, liquidation, or potential-debt flag;
- paper-broker reconciliation using tiny, explicitly authorized orders;
- an independent human review of contract and broker risk settings.
