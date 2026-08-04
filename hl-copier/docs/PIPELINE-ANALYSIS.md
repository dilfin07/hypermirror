# hl-copier — pipeline architecture breakdown: latency and resilience

> Snapshot as of 2026-06-15. Latency measurements were taken **on the production Pi** (home internet → exchange servers in the US). On a different connection/VPS the numbers will differ.

> 🇷🇺 [Русская версия](PIPELINE-ANALYSIS.ru.md).

## TL;DR
- The copying pipeline is **simple and linear**: lead event (HL) → recompute → orders on Binance.
- **Real event→order latency ≈ 5.7 s** (measured). Of which: debounce 1.2s + a chain of 7 sequential REST calls ≈ 3.9s + order submission ≈ 0.6s.
- **The bottleneck is the sequential REST calls** in `_compute` (network-bound from the home Pi), not the logic.
- Conclusion: the current architecture is good for **slow swing traders** (trades once every minutes/hours), but not for scalpers (a trade every ~3.6s — we fall behind).
- Reducing to **~1.5–1.8s without leaving the Pi** is realistic (parallelism + cache + debounce). Down to **~0.3–0.4s** — only a VPS next to the exchange.

---

## 1. Component map

```
copier/
  hl/rest.py      HLInfo        — reading Hyperliquid (REST). Global throttle + retry on 429.
  hl/ws.py        FillStream    — resilient WS on userFills (auto-reconnect + watchdog + resubscribe).
  core/positions  net_positions, account_value, price_move_pct — pure calculations over HL state.
  core/plan.py    compute_plan  — desired net positions: leverage (fixed/mirror), freezing positive
                                   ones at startup, caps (leverage, notional/coin). Pure function.
  core/sizing.py  desired_mirror/diff_orders — ALTERNATIVE pure helpers (NOT used in the hot
                                   path; candidate for cleanup/merge into plan).
  execution/
    binance.py    BinanceFutures — execution on Binance USDT-M (REST): account/positions/
                                   mark_prices/funding/leverage/market_order/user_trades.
    executor.py   build_orders / build_orders_hedge — diff desired↔current → list of orders
                                   (one-way and hedge). apply() — submission. Pure + apply.
server/
  controller.py   Controller    — the ONLY one that trades. Copier loops (poll/ws), monitor-WS
                                   alerts, status/services, audit, Telegram, trader cards.
  api.py          REST/frontend static.
tools/serve.py    launch of the web interface (systemd service hl-copier on the Pi).
```

Only **`Controller`** trades and holds state (singleton). Everything else is pure functions or thin clients.

---

## 2. Copying pipeline (hot path)

Two modes, switched by `data_mode` (poll | ws):

### WS mode (currently in prod)
```
[Lead trades on HL]
      │  HL WS push (userFills)
      ▼
FillStream.cb → on_fill → self._wake.set()          ← instantly
      │
      ▼
_ws_reconcile_loop:
   wake.wait() → time.sleep(1.2)  ← DEBOUNCE 1.2s (batch a series of fills)
      │
      ▼
_compute(do_apply=live):
   1) hl.all_mids()                 ~0.61s  REST
   2) hl.clearinghouse_state(lead)  ~0.39s  REST
   3) bn.account()                  ~0.87s  REST
   4) bn.positions()                ~0.66s  REST
   5) bn.funding_rates()            ~0.48s  REST   (only needed for UI!)
   6) bn.position_mode()            ~0.37s  REST   (almost never changes)
   ──────────────────────────────── compute_plan() — pure, ~0ms
   7) bn.mark_prices()              ~0.48s  REST
   ──────────────────────────────── build_orders() — pure, ~0ms
   8) executor.apply():
        set_leverage (if needed)    REST
        market_order × N            ~0.64s/order  REST  ← ORDER SENT
   9) bn.positions_detail()         REST   (refresh UI after execution)
   10) status + services + heartbeat
```
**Fallback:** if there was no WS event for 60s — `_ws_reconcile_loop` still runs `_compute` (safety net). On a WS drop — `on_reconnect` wakes an immediate reconciliation (catch up on missed events).

### Poll mode
The same `_compute`, but called on a `poll_interval_sec` (30s) timer, without WS. Simpler, but latency up to 30s.

### What `_compute` does in essence
1. Determine the **desired** positions = scale the lead's exposure to our equity (`compute_plan`): `notional[coin] += szi · mark · (sleeve / target_value)`, then caps (leverage, notional/coin), freezing positive ones at startup.
2. Determine **our current** positions (Binance).
3. `executor.build_orders` — diff desired↔current → market orders (with `reduceOnly` on reduce/close), filtered by `minQty/step/minNotional`.
4. `apply` — set leverage + market orders.

Reconciliation is **idempotent**: we always converge to the target net position, so a missed event "self-heals" on the next tick. This is a plus for resilience, but amplifies drift at minimums (see §5).

---

## 3. Latency budget (measured on the Pi)

| Stage | Time | Nature |
|---|---:|---|
| Debounce `sleep(1.2)` | 1200 ms | baked into the code (batching) |
| HL all_mids | 606 ms | network (Pi→US) |
| HL clearinghouse(lead) | 386 ms | network |
| BN account | 872 ms | network |
| BN positions | 656 ms | network |
| BN funding_rates | 480 ms | network · **UI only** |
| BN position_mode | 373 ms | network · nearly static |
| BN mark_prices | 484 ms | network |
| Order submission (BN POST) | ~640 ms | network |
| **TOTAL event→order** | **≈ 5700 ms** | |

**Where the time goes:** ~3.9s is 7 REST calls **in a row**, each ~0.4–0.9s due to the RTT from the home connection to the exchanges. The logic (compute_plan/build_orders) is single-digit milliseconds — it's not to blame.

The scalper `0x31dea…` makes ~1000 fills/hour (a trade every ~3.6s) → with our 5.7s latency we react when he has already reversed.

---

## 4. What's already done for resilience (strengths)
- **WS with auto-reconnect** (`FillStream`): watchdog (thread alive + message freshness catches half-open), recreating `Info` + resubscribe with backoff, `on_reconnect` catch-up. The SDK doesn't reconnect on its own — we've covered that.
- **HL throttle + retry on 429** (shared pacer ~6–7/sec) — bursts don't take down the status.
- **60s fallback reconciliation** in ws mode + immediate reconciliation after a drop.
- **Idempotent reconciler** — misses self-heal.
- **Freezing positive positions at startup** — we don't copy someone else's profit opened before us.
- **Caps**: `leverage_cap`, `max_notional_per_coin`, `minQty/step/minNotional` filters.
- **Binance -1021** (recvWindow) — resilience to time desync.

---

## 5. Weak points / risks
1. **5.7s latency** (see §3) — sequential REST + debounce.
2. **Drift at minimums**: our equity $566 ≪ a large lead's account → their micro top-ups scale into `<$5 / below the step` → `skip` → our position diverges from the target. In the logs, batches of `$1 < minNotional $5`, `qty < minQty/step`. The remainder is **not accumulated anywhere** → constant drift.
3. **Margin**: a one-off `-2019 Margin is insufficient` — no buffer/pre-check of margin before an order.
4. **WS drops** frequently (once every 15–60 min). Reconnect exists, but during the drop window events come only from the 60s fallback → extra latency; fills within the window arrive as a snapshot and get swallowed (we catch up on position via reconciliation).
5. **Heavy `_compute` on every event**: a full recompute of all symbols + 7 REST, even if only one coin changed. Part of the data is almost static (`funding_rates`, `position_mode`, filters).
6. **Market orders only** → taker fee + slippage (noticeable for frequent trading).
7. **`sizing.py` duplicates `plan.py`** and is not used in the hot path — dead code / risk of divergence.

---

## 6. Recommendations

### A. Latency reduction — cheap, staying on the Pi (target ~5.7s → ~1.5–1.8s)
1. **Parallelize the REST chain** (threads/futures): pull HL state + BN account/positions/marks all at once → not the sum (3.9s), but the slowest (~0.9s). **−~3s.**
2. **Remove static data from the hot path**: `funding_rates` (UI only) and `position_mode` (changes ~never) — cache once every N minutes / compute outside the tick. **−~0.85s.**
3. **Reduce the debounce** 1.2s → ~0.25s (or adaptively: shorter for rare events). **−~0.95s.**
4. **`positions_detail` after the order** — it's for UI, don't let it block the hot path (do it asynchronously).
5. **Latency measurement in logs**: write `event_ts (fill) → order_sent_ts` for each copy — get exact numbers next session instead of estimates.

### B. Latency reduction — infrastructure (target ~0.3–0.4s)
6. **Execution on a VPS next to the exchange** (e.g. AWS Tokyo/ap-northeast — Binance is there): call RTT ~0.5s → ~0.03s. This is the only path to "scalp class". Downside — we leave the home Pi.
7. **Push instead of poll for our own account**: Binance **user-data stream (WS)** — positions/balance arrive on their own, we don't hit `account()/positions()` every tick.
8. **Incremental target state**: keep the lead's net position from the fill stream (we already receive them via WS), instead of requesting `clearinghouse_state` every tick.

### C. Execution resilience / correctness
9. **Accumulate the remainder below minNotional**: don't discard sub-minimal deltas, but accumulate and send an order once the sum crosses $5/step — removes the drift.
10. **Margin buffer + pre-check** before an order (don't load up to the brim) — against `-2019`.
11. **Data freshness guard**: if the state is stale (WS silent, REST failing) — don't execute on old data, mark it "stale".
12. **Limit/post-only orders** for non-urgent settlements — saving on fees/slippage.
13. **Cleanup**: remove the unused `sizing.py` or fold it into `plan.py`.

---

## 7. Conclusion and lead profile
The architecture is functional and understandable; the main debt is the **latency of the REST chain** and **drift at minimums** with a small account.

**Who to copy (given current capabilities):**
- **slow swing/positional** traders: enter/exit once every hours–days, hold positions;
- few assets, no HFT/MM;
- ideally a comparable order of "size", so movements don't fall into sub-minimal territory on our side.

**Who NOT to copy:** scalpers/MM/quant bots (we're 5+ sec slower and lose their edge; see the breakdown of `0xd4bb…` — BTC-MM).

**Recommended order of work:** A1+A2+A3+A5 (parallelism + static cache + debounce + measurement) → check the real latency → optionally B6/B7 (VPS + user-stream) → C9/C10 (remainder + margin buffer).
