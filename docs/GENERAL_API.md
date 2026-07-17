# Sentinel Archive General API

`archive.general.v1` lets several bots watch the same recorded market timeline and use Archive as a virtual brokerage. Archive releases market events, accepts bot-created orders, emulates broker responses, relays bot-created control directives, and records the result. It does not contain or invoke a trading strategy.

## Non-negotiable boundary

- A market replay cannot create an order.
- Every order has a registered `participant_id`, `bot_id`, client order ID, Archive order ID, and preserved normalized bot request.
- A report always exposes `archive_generated_order_count`, which is fixed at `0`.
- P&L is attributable only to fills whose originating bot order is present.
- Participant market routes expose released bars only. They do not return the future dataset.
- Pattern observations and risk directives must be published by a connected bot. Archive never manufactures them.

## Shared replay model

One dataset can contain many symbols and asset classes. One run owns a single virtual clock. Participants subscribe to only the symbols they need:

| Participant | Roles | Example subscriptions | Behavior |
| --- | --- | --- | --- |
| Pulse | `trader` | `SPY` | Receives SPY bars and submits stock orders. |
| Iron | `trader` | `ES` | Receives E-mini S&P 500 bars and submits futures orders. |
| Edge | `observer`, `risk_controller` | `SPY`, `ES` | Records pattern decisions and publishes risk directives. |

All three receive events from the same replay timestamp. Accounts and private broker events remain isolated.

## Connection settings for bot Brokerage tabs

Each bot's future **General API** section needs these values:

| Setting | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:9200/api/general` |
| Replay run ID | Returned when the run is created. |
| Participant ID | Chosen during bot registration. |
| Bot token | Returned once during registration. Send it as `X-Archive-Bot-Token`. |
| Event transport | WebSocket stream or cursor-based REST polling. |

Register each bot separately. Do not reuse one participant or token across bots.

## Creating a recorded dataset and run

Import requires an explicit `data_kind`. Archive preserves the source label and SHA-256 fingerprint in every report.

```http
POST /api/general/datasets/import/csv
Content-Type: application/json

{
  "name": "May-June recorded market",
  "data_kind": "recorded",
  "source_name": "provider export",
  "retrieved_at": "2026-07-16T00:00:00Z",
  "csv_text": "timestamp,symbol,open,high,low,close,volume\n...",
  "instruments": [
    {"symbol": "SPY", "asset_class": "stock", "tick_size": "0.01"},
    {
      "symbol": "ES",
      "asset_class": "future",
      "tick_size": "0.25",
      "multiplier": "50",
      "initial_margin": "12000"
    }
  ]
}
```

```http
POST /api/general/runs
Content-Type: application/json

{
  "dataset_id": "dataset-...",
  "name": "May-June ecosystem replay",
  "speed": 100,
  "loop": false
}
```

`speed` is timestamp batches per real second. Manual `POST /runs/{run_id}/step` is available for deterministic testing.

## Registering a bot

```http
POST /api/general/runs/{run_id}/participants
Content-Type: application/json

{
  "participant_id": "pulse-may-june",
  "bot_id": "sentinel-pulse",
  "roles": ["trader"],
  "subscribed_symbols": ["SPY"],
  "starting_cash": "100000",
  "commission_per_order": "1.00",
  "slippage_bps": "1"
}
```

The response includes the bot token. Archive stores only its hash.

## Reading released market events

REST polling uses a durable sequence cursor:

```http
GET /api/general/runs/{run_id}/events?participant_id={participant_id}&after=0
X-Archive-Bot-Token: {token}
```

The response returns `next_after`. Send it as the next `after` value. `market.bar` events contain one released OHLCV bar and its data kind.

WebSocket clients can connect to:

```text
ws://127.0.0.1:9200/api/general/runs/{run_id}/stream/{participant_id}
```

Use the same token header. A `token` query parameter is supported for clients that cannot set WebSocket headers.

## Submitting broker orders

```http
POST /api/general/runs/{run_id}/participants/{participant_id}/orders
X-Archive-Bot-Token: {token}
Content-Type: application/json

{
  "client_order_id": "pulse-spy-cycle-17-entry",
  "symbol": "SPY",
  "side": "buy",
  "quantity": "10",
  "order_type": "market",
  "time_in_force": "day",
  "strategy_id": "pulse-range-cycle"
}
```

Accepted orders are eligible against the next released bar. Market orders use the next bar open. Limit and stop orders use the next bar's OHLC range. Volume participation can create partial fills. Bot client order IDs are idempotent within that participant account.

Supported broker operations:

- Submit market, limit, or stop orders.
- Submit reduce-only exits.
- Group exit orders with `oco_group`.
- List and cancel orders.
- Query individual orders, fills, and subscribed instrument specifications.
- Read account, buying power, margin, positions, fills, realized P&L, unrealized P&L, and total return.

Fifteen-minute OHLCV cannot prove the exact ordering of events inside a bar. When one bar touches both sides of an OCO bracket, Archive processes the stop before the limit so the result is deterministic and adverse rather than profit-biased. Use quote or trade-tape data when exact ordering materially affects the result.

## Publishing observations and cross-bot controls

Edge can record what it independently recognized:

```http
POST /api/general/runs/{run_id}/participants/edge/observations
X-Archive-Bot-Token: {edge_token}

{
  "event_type": "market_shift_detected",
  "symbol": "ES",
  "decision": "halt_futures_entries",
  "reason": "bearish structure threatens the open strategy",
  "confidence": "0.87"
}
```

It can then publish a directive to Iron:

```http
POST /api/general/runs/{run_id}/participants/edge/directives
X-Archive-Bot-Token: {edge_token}

{
  "directive_type": "halt_new_orders",
  "target_participant_ids": ["iron"],
  "symbol": "ES",
  "reason": "market regime shifted bearish",
  "severity": "critical"
}
```

Iron reads and acknowledges the directive through its own token. After acknowledgment, the virtual broker rejects new opening orders for Iron while still accepting position-reducing exits. Archive does not close the position automatically. A `flatten_requested` directive likewise requires Iron to create its own exit order.

## Report truth fields

```http
GET /api/general/runs/{run_id}/report
```

The report includes:

- Dataset identity, source label, recorded/synthetic classification, date range, and checksum.
- Every participant and isolated account result.
- Every bot-generated order and broker fill.
- `archive_generated_order_count: 0`.
- `pnl_exists_only_from_bot_orders` for every participant.
- Published and acknowledged cross-bot directives.
- The complete replay sequence range and event count.

A participant with no submitted orders and no fills remains at zero P&L. Archive cannot claim that the participant traded.
