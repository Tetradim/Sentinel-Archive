# Sentinel Native Profitability Replay — 2026-07-17

> Research replay only. Positive historical P&L is not proof of future profitability and is not a recommendation to trade.

## Verdict

Pulse's per-symbol April–May-selected settings ended with positive mark-to-market value on all 3 held-out June–July tickers ($1603.76 combined after modeled friction). Only QQQ and TSLA had positive realized gross P&L; SPY's positive ending depended on an open gain after one closed loss. This is encouraging but insufficient evidence of reliable profitability. Chain and Iron cannot yet be ranked because neither initiated a candle-derived order.

## Pulse: April–May tuning, June–July held-out replay

| Symbol | Selected settings | Apr–May net | Jun–Jul net | Jun–Jul return | Closed trades | Max drawdown |
|---|---|---:|---:|---:|---:|---:|
| SPY | avg 14; buy -0.5%; sell 6.0%; stop -2.0%; trail off | $620.77 | $31.76 | 0.318% | 1 | $375.23 |
| QQQ | avg 30; buy -0.5%; sell 6.0%; stop -2.0%; trail off | $678.94 | $463.71 | 4.637% | 1 | $497.37 |
| TSLA | avg 14; buy -1.5%; sell 6.0%; stop -8.0%; trail off | $1915.84 | $1108.29 | 11.083% | 4 | $1155.10 |

The selection rule required at least one completed round trip in April–May. June–July settings were frozen before replay. Open end-of-window positions are marked to the final close and include a hypothetical exit slippage charge; they are not counted as bot-generated sells. A robustness check selected one shared setting across all three tickers (`avg60_buym3p0_sell6p0_stopm2p0_trail2p0`): held-out results were SPY $0.00 (0 orders), QQQ $0.00 (0 orders), TSLA $1120.31 (9 orders). The lack of SPY and QQQ orders shows that the positive per-ticker result is not broad confirmation.

## Pulse + Edge coordination replay (June–July, 15-minute)

| Symbol | Ordering | Net P&L | Return | Edge non-HOLD handoffs | Accepted | Closed trades |
|---|---|---:|---:|---:|---:|---:|
| SPY | edge_first | $-8.96 | -0.090% | 484 | 256 | 4 |
| SPY | pulse_first | $-187.16 | -1.872% | 315 | 252 | 2 |
| QQQ | edge_first | $-468.07 | -4.681% | 496 | 238 | 1 |
| QQQ | pulse_first | $-468.07 | -4.681% | 496 | 238 | 1 |
| TSLA | edge_first | $-1008.42 | -10.084% | 355 | 206 | 7 |
| TSLA | pulse_first | $-1131.41 | -11.314% | 353 | 204 | 7 |

This duo replay exercises Edge's native core ORB/volume/momentum scoring and DecisionEngine, plus Pulse's native Edge buy/sell methods and ticker risk settings. It does not exercise Edge's enhanced chart-pattern analyzer, so it is coordination evidence—not a complete profitability certification for the duo.

## Chain and Iron

| Bot | Orders independently initiated | P&L | Conclusion |
|---|---:|---:|---|
| Chain | 0 | $0.00 | No candle-to-entry automation loop; waits for an external/operator signal. |
| Iron | 0 | $0.00 | Strategy primitives exist, but no autonomous strategy-to-order runtime loop. |

Zero is not a profitable result, but it is also not a losing strategy result. These bots are presently **not autonomously testable as traders** without adding the missing orchestration inside the bots themselves.

## Evidence controls

- Tuning window: `2026-04-01T00:00:00Z` through `2026-06-01T00:00:00Z` (end exclusive).
- Held-out window: `2026-06-01T00:00:00Z` through `2026-07-17T00:00:00Z` (end exclusive; last completed US session July 16).
- Pulse setting runs: 981.
- Execution friction: 2.0 bps per order plus $0.00 commission.
- No synthetic candles, scripted signals, or preselected trade timestamps were used.
- April–May selected settings were frozen before June–July validation.
- Every input series has a SHA-256 fingerprint and malformed OHLC rows were excluded rather than corrected.

## Data manifests

| Provider | Symbol | Interval | Bars | First | Last | Fingerprint | Dropped |
|---|---|---:|---:|---|---|---|---:|
| yahoo_chart | SPY | 1h | 666 | 2026-03-02T14:30:00Z | 2026-07-16T20:00:00Z | `d494e5714c55aee7…` | 0 |
| yahoo_chart | QQQ | 1h | 666 | 2026-03-02T14:30:00Z | 2026-07-16T20:00:00Z | `28ac65b695738677…` | 0 |
| yahoo_chart | TSLA | 1h | 666 | 2026-03-02T14:30:00Z | 2026-07-16T20:00:00Z | `daa757803457d15b…` | 0 |
| yahoo_chart | MES=F | 1h | 2194 | 2026-03-01T23:00:00Z | 2026-07-16T23:00:00Z | `e93f0610d22961a1…` | 543 |
| yahoo_chart | MNQ=F | 1h | 2195 | 2026-03-01T23:00:00Z | 2026-07-16T23:00:00Z | `e32aeac162498db0…` | 542 |
| yahoo_chart | BTC-USD | 1h | 3311 | 2026-03-01T00:00:00Z | 2026-07-16T23:00:00Z | `04fb735d8e5becae…` | 1 |
| yahoo_chart | SPY | 1d | 384 | 2025-01-02T14:30:00Z | 2026-07-16T13:30:00Z | `74d6a45b9a71676f…` | 0 |
| yahoo_chart | SPY | 15m | 833 | 2026-06-01T13:30:00Z | 2026-07-16T20:00:00Z | `6de9165e195e56fa…` | 0 |
| yahoo_chart | QQQ | 1d | 384 | 2025-01-02T14:30:00Z | 2026-07-16T13:30:00Z | `84f107d22b26fc6e…` | 0 |
| yahoo_chart | QQQ | 15m | 833 | 2026-06-01T13:30:00Z | 2026-07-16T20:00:00Z | `d549843e7a10d2c7…` | 0 |
| yahoo_chart | TSLA | 1d | 384 | 2025-01-02T14:30:00Z | 2026-07-16T13:30:00Z | `7571b052e3e701ce…` | 0 |
| yahoo_chart | TSLA | 15m | 833 | 2026-06-01T13:30:00Z | 2026-07-16T20:00:00Z | `1534513e36edcb51…` | 0 |
| bitunix_futures | BTCUSDT | 1h | 2552 | 2026-04-01T00:00:00Z | 2026-07-16T23:00:00Z | `c290dd4a5f89ed77…` | 16 |

## Important limitations

- Yahoo's public chart endpoint is a research feed, not exchange or broker execution truth.
- Pulse was sampled once per recorded candle close. Intrabar price paths were not invented.
- The study models 2 bps per order after native paper fills; Pulse's decisions do not currently wait for Archive General API fill acknowledgements in this adapter.
- Hourly continuous futures data was acquired for Iron feed coverage, but no futures P&L was produced because Iron did not initiate an order.
- BitUnix malformed candles were excluded and counted. Archive did not repair vendor OHLC values.
- A roughly six-and-a-half-week held-out interval is far too short to establish durable profitability.
