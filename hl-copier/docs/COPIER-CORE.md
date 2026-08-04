# Copier core — how and when it works

> The logic of copying HL → Binance: proportion and risk, caps, reconciliation, catch-up,
> position scaling, rounding, baseline freeze, alert format, and a full settings reference.
> See also [CONFIGURATION.md](CONFIGURATION.md) (every setting) and
> [PIPELINE-ANALYSIS.md](PIPELINE-ANALYSIS.md) (architecture / latency).
> 🇷🇺 [Русская версия](COPIER-CORE.ru.md).

---

## 1. The model in one sentence
The copier is **reconciliation-based and idempotent**: on every tick it looks at "where the
lead is now" (net positions on Hyperliquid) and "where we are now" (positions on Binance),
computes the **desired** state scaled to our equity, and drives us there with the minimum
orders. It does **not** replay every trade 1:1 — it continuously converges the position to the
target. Any divergence (a missed event, a manual edit, rounding) self-heals on the next tick.

```
Hyperliquid (lead)              Our compute                    Binance (us)
  net positions      ──►  desired = proportion to our    ──►  diff orders
  (clearinghouse)         equity  →  caps  →  freeze           (market/maker)
        ▲                                                        │
        └──────────── reconciliation trigger ◄───────────────────┘
            lead WS fill · 60s fallback · reconnect · poll every N s
```

---

## 2. Proportion and risk (the essence)

### How the desired size is computed
For each coin:
```
desired_notional = lead_notional × (our_equity / lead_equity) × lead_weight
```
i.e. we hold the **same share of our own capital** that the lead holds of theirs. That is the
lead's "full risk" — we copy their **effective leverage** (notional / equity).

> Example: the lead has an ETH short of $109M on $19M equity → effective leverage **5.73×**.
> Our equity $566 → full proportion = 566 × 5.73 = **~$3,240 short** (also 5.73×).

### When we LIMIT risk (caps)
Three limiters shrink the desired size (in order of application):

| Setting | What it caps | Example (equity $566) |
|---|---|---|
| `max_notional_per_coin_usd` | **position size per coin**, $ | $800 → ETH short at most $800 |
| `leverage_cap` | **gross notional** = equity × cap | 3 → whole book ≤ $1,698 |
| `mirror_max_leverage` / `fixed_leverage` | **per-order leverage** on Binance | 100 → lead's leverage not cut |

The **strictest** one wins. In the example: proportion $3,240 → cut by `max_notional_per_coin`
to **$800** (1.41× our equity) → we hold ~25% of the lead's risk.

### Full risk vs limited — how to switch
- **Limited (default, recommended for a small account):** `max_notional_per_coin` and
  `leverage_cap` below the proportion → we hold a slice. Safe, but smaller than the lead.
- **Full lead risk:** raise ALL three ceilings above the proportion:
  `max_notional_per_coin_usd` → very large; `leverage_cap` ≥ the lead's effective leverage;
  per-order leverage ≥ effective leverage (otherwise margin is insufficient:
  notional / leverage > equity → `-2019`).
  ⚠️ On a small account, full risk = almost all margin in one position, liquidation close by;
  if the lead is liquidated, so are you.

### Leverage: mirror vs fixed
- `leverage_mode = mirror` → per-order leverage = `min(lead_leverage, mirror_max_leverage)`.
- `leverage_mode = fixed` → always `fixed_leverage`.
- **Important:** the "leverage setting" ≠ "effective leverage". If the lead's position is
  underwater, their equity drops and effective leverage (notional / equity) drifts **above**
  their setting. Our margin usage = effective_leverage ÷ leverage_setting (lead 5.73/3 = 187%,
  us 1.41/3 = 47%).

---

## 3. Reconciliation — when and what triggers it

| Trigger | Mode | Delay |
|---|---|---|
| Lead WS fill (on HL) | `data_mode=ws` | +1.2s debounce (batches a burst) |
| Fallback reconciliation | `ws` | every 60s (safety net) |
| After a WS drop (`on_reconnect`) | `ws` | immediately (catch up misses) |
| Poll timer | `data_mode=poll` | `poll_interval_sec` (30s) |

Each tick: fetch lead state (HL) + ours (Binance) → `compute_plan` (desired) →
`build_orders` (diff) → `apply` (orders). Detailed latency budget (~5.7s from a home Pi) is in
[PIPELINE-ANALYSIS.md](PIPELINE-ANALYSIS.md).

**Idempotency:** a missed fill isn't lost — the next tick sees the position gap and catches up.
This also means a manual edit to our Binance position is **reverted** back toward the target by
reconciliation (by design — unless you use the gates in §4/§9 to keep a manual overlay).

---

## 4. Catch-up and position scaling

- **Entry catch-up (favorability gate):** on an OPEN/ADD we don't enter if the price is now
  **worse than the lead's entry** (within `favorability_tol_pct`, default 0.3%). LONG — price
  not above the lead's entry; SHORT — not below. Exits (reduce/close) are NOT gated (we always
  de-risk). This kills "chasing a moved price" caused by our latency. If the price returns to a
  favorable zone (or the lead adds and raises their average entry), reconciliation enters on the
  next tick. Toggle: `favorability_gate`.
- **Auto-scaling:** the desired size is recomputed every tick from current equities. Our equity,
  or the lead's equity/notional, changes → the desired drifts → the position is adjusted. Nothing
  to do manually.
- **Remainder accumulation:** sub-minimal adds aren't executed one by one — they accumulate in the
  "target ↔ ours" gap and fire once they cross the minimum (see §5).

---

## 5. Exchange minimums and rounding (matters for drift)

Binance rejects orders below `minNotional` (e.g. $5–$20) and `minQty` / `stepSize`.
Logic (`_resolve_qty`, churn-free under reconciliation):

| Case | Behavior |
|---|---|
| **Full close** (target → 0) | always executed (reduceOnly isn't blocked by the minimum) |
| **Opening** a sub-minimal position | `min_notional_roundup=true` → **round up** to `minNotional` (otherwise a small position can't be copied at all) |
| **Add / partial reduce** below `minNotional` | **dead-band** — left alone; the delta accumulates and fires once it crosses the minimum |

**Why not "just round up everywhere":** in reconciliation that would cause churn (open at min →
next tick cuts it back → repeat). A dead-band on sub-minimal edits eliminates it.

**Rounding:** `round_step` rounds quantity **down** to `stepSize`. The remainder (< a step)
accumulates in the gap and is filled later. "Dust" below `minQty` can't be closed — it remains
(an exchange limitation).

**Consequence for a small account:** a large lead's micro-moves scale down to `<minNotional` for
us → some small trims are deferred (dead-band) until they accumulate. Unnoticeable on slow
swingers; on scalpers, copying is pointless (see PIPELINE-ANALYSIS, lead profile).

---

## 6. Baseline freeze (what we do with positions the lead ALREADY has open)

When we start copying, the lead often already has open positions — we "missed the entry". On the
FIRST tick (`baseline`) we decide whether to copy them:

| `start_skip_open` | Behavior at start |
|---|---|
| `profitable` (default) | freeze positions already up ≥ `start_skip_profit_pct` |
| `all` | freeze ALL positions open at start (copy only new entries) |
| `none` / other | don't freeze — copy the lead's whole book as-is |

- `start_skip_profit_pct` — the threshold in %. Reds and moderately green positions (up to +5%)
  are copied; only "rockets" >+5% are frozen.
- The freeze is **sticky**: the decision is made at baseline and held until the lead closes the
  position (then it unfreezes). It isn't recomputed on the fly — only a restart resets it (a fresh
  baseline on the current state).

---

## 7. Execution resilience

- **Binance retries:** transient errors (429/418/5xx, codes -1003/-1001/-1007, network resets) →
  up to 3 retries with exponential backoff honoring `Retry-After`. `-1021` (clock skew) → resync
  and retry. Permanent (`-2019` margin, `-1013` filter, `-4xxx`) → immediate error, no retry.
- **Resilient WS:** the Hyperliquid SDK doesn't reconnect itself — our `FillStream` watches
  liveness (stream alive + message freshness, catches half-open), recreates the connection +
  re-subscription with backoff, and `on_reconnect` triggers catch-up. Fills are de-duplicated by
  `tid`; the snapshot on subscribe is swallowed.
- **Hedge / one-way:** both Binance account modes are supported (a LONG/SHORT leg, or a net
  position).

---

## 8. Copy alerts (Telegram)

A detailed format + the **source of the action**:
```
📋 Copied · pension-usdt
🔴 ETH SHORT · ➖ Reduce
• Size: -0.455 → -0.441 (-3.1%)
• Order: BUY 0.014 (~$25) @ $1,818
• Our position: ~$802 (1.41× equity)
• Leg: SHORT
🔄 Source: reconciliation (bot synced the position)
```
- `🎯 Source: lead trade` — the lead actually moved the position (detected by whether their net
  position changed on this tick).
- `🔄 Source: reconciliation` — the bot converged the position to target itself (holding a cap /
  reverting a manual edit / catch-up), with no lead move.

---

## 9. Settings reference

The complete, always-current reference — with defaults, scope (UI vs hardcoded) and interactions —
now lives in **[CONFIGURATION.md](CONFIGURATION.md)**. Quick map of the risk-relevant keys:

| Key | Purpose | Typical |
|---|---|---|
| `targets[]` | leads: `{address, label, weight}` | 1 lead, weight 1.0 |
| `data_mode` | `ws` (push, instant) / `poll` | `ws` |
| `leverage_mode` | `mirror` / `fixed` | `mirror` |
| `leverage_cap` | gross-notional cap = equity × cap | 3 |
| `max_notional_per_coin_usd` | per-coin size cap, $ | 800 |
| `start_skip_open` | baseline freeze: `profitable`/`all`/`none` | `profitable` |
| `favorability_gate` / `favorability_tol_pct` | don't chase a bad entry | true / 0.3 |
| `min_notional_roundup` | round sub-minimal opens up to minNotional | true |

Live `config/config.json` / `.env` / `runtime/` exist only on the server and `deploy.sh` never
touches them.

---

## 10. Recipes (cheat sheet)

| I want | Settings |
|---|---|
| Full lead risk 1:1 | `max_notional_per_coin` huge, `leverage_cap` ≥ eff. leverage, per-order leverage ≥ eff. leverage |
| Cap size per coin | `max_notional_per_coin_usd` = desired $ ceiling |
| Cap total leverage | `leverage_cap` = N (book ≤ equity×N) |
| Take the lead's leverage | `leverage_mode=mirror`, high `mirror_max_leverage` |
| My own fixed leverage | `leverage_mode=fixed`, `fixed_leverage=N` |
| Copy the lead's current book at start | `start_skip_open=none` |
| Don't jump into others' run-ups | `start_skip_open=profitable`, `start_skip_profit_pct=5` |
| Don't chase a bad price | `favorability_gate=true`, tune `favorability_tol_pct` |
| Instant copies | `data_mode=ws` |

---

## 11. Known limitations
- Event→order latency ~5.7s from a home Pi (REST chain + debounce) → scalpers can't be tracked.
- Small account: the lead's micro-moves fall into the dead-band until they accumulate.
- Favorability compares Binance mark vs HL entry (different venues; the basis is covered by the
  tolerance).
- "Dust" below minQty isn't closed (exchange limitation).
- The freeze isn't recomputed on the fly — only by a restart.
