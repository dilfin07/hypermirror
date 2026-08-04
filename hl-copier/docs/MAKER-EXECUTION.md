# Copier maker execution — design spec (NOT implemented, future plan)

> Status: draft. Currently the engine sends only `market_order` (taker). This document is
> a spec for adding passive (maker) execution, in order to copy traders whose edge is
> in maker execution (passive accumulation with limit orders + funding on illiquid names,
> e.g. the alt-fader `0x92bbd811…`: ASTER/NEAR/ZEC/ZRO, building a short over hours).

> 🇷🇺 [Русская версия](MAKER-EXECUTION.ru.md).

## 1. Why
- As a taker we **pay the spread** on every copy order. On illiquid alts the spread is
  fat — and that is precisely the edge of the copied trader, which we currently hand to the exchange.
- As a maker we **capture the spread (or at least don't pay it)** + potentially funding.
- On BTC/ETH there is little point (spread ~1bp) — the feature is targeted at **alts**.

## 2. Config
```
"execution_mode": "taker" | "maker" | "maker_only"   // default taker (as now)
"maker_offset_ticks": 0          // how many ticks from best price to place (0 = at best)
"maker_wait_sec": 8              // how long to wait for a fill before re-placing
"maker_max_chases": 2            // how many times to re-place before fallback
"maker_fallback_taker": true     // after max_chases finish with market (tracking guarantee)
```
- `taker` — current behavior.
- `maker` — **maker-first, taker-fallback** (recommended): we try passively, and if it doesn't work we finish with market.
- `maker_only` — post-only only, no fallback (RISK of under-execution / drift from the target).

## 3. New primitives (`copier/execution/binance.py`)
Currently there is only `market_order`. Add:
- `book_ticker(symbol)` → best bid/ask (public `/fapi/v1/ticker/bookTicker`).
- `limit_order(symbol, side, qty, price, post_only=True, position_side=...)` → limit order
  with `timeInForce=GTX` (post-only: the exchange rejects it if the order would cross the book = become a taker).
- `cancel_order(symbol, order_id)` and `cancel_all(symbol)`.
- `order_status(symbol, order_id)` → status / filled volume (or take it from `open_orders_all` + `user_trades`).

## 4. State (Controller)
- `self._maker_orders = {}` — `(symbol, position_side) -> {order_id, side, qty, price, placed_ts, chases}`.
  Persisted in runtime (so that after a restart we can cancel dangling orders). At startup — `cancel_all` on our symbols, reset.

## 5. Flow (on every reconciliation tick, for `maker`)
Instead of "computed the delta → market_order":
1. Compute the target delta for the symbol (as now, build_orders/_hedge).
2. **Account for outstanding maker orders** (see §6): needed_delta = desired − (filled + pending).
3. If we have a resting order on the symbol:
   - **filled / partially filled** → update the position, keep/re-place the remainder;
   - **price moved away** (our order is no longer at best) OR `maker_wait_sec` elapsed → `cancel` + re-place at the new best price, `chases++`;
   - `chases ≥ maker_max_chases` and `maker_fallback_taker` → cancel, **finish with `market_order`** for needed_delta.
4. If there is no order and needed_delta ≠ 0 → place a `limit_order(GTX)` at the best price on our side:
   - buy (closing a short / long) → at the best **bid**;
   - sell (short / closing a long) → at the best **ask**.
5. **Full close / urgent** (panic, lead exit) → always **taker** (maker is not allowed — we might not make it in time).

## 6. Reconciliation with pending taken into account (CRITICAL)
Currently the diff = `desired` vs `filled` (the position on the exchange). With maker there appear
**outstanding orders**, and if they are not accounted for, on every tick we will stack up duplicates.
→ `effective_current = filled_position + sum(our open maker orders on the symbol)`.
Diff `desired` against `effective_current`. `build_orders/_hedge` take "current",
so pass it **filled + pending of our orders**.

## 7. Edge cases
- **Partial fill** — account for the executed portion, remainder stays in the order; do not duplicate.
- **Post-only reject** (price crossed) — retry at the new best price.
- **Target moved fast, we didn't get filled** — `maker` will fall back to taker; `maker_only` will lag behind (drift — a risk flag).
- **favorability-gate** — apply to the LIMIT ORDER price (not the mark): we post only if our limit price is no worse than the target's entry.
- **Restart** — cancel all our outstanding orders at startup (otherwise zombie orders).
- **Cancel failed** (the order already filled between the check and the cancel) — handle as a fill.

## 8. Fill detection
Polling the status every tick is expensive; options:
- from `open_orders_all` (what is still resting) + `positions` (what got filled) — by diff;
- or `user_trades` for the symbol (has orderId) — exact fills of our orders.
Binance WS userData-stream (ORDER_TRADE_UPDATE) — the most precise, but it's yet another WS layer (later).

## 9. Trade-offs / safety
- A maker fill is NOT guaranteed → an entry lag is possible. For slow passive targets (hours) — fine;
  for scalpers — a miss (we don't copy them at all).
- More moving parts → more failures. Therefore **MVP = one GTX attempt + timeout + taker fallback**,
  without aggressive chase. Chase / multi re-place — phase 2.
- `maker` (with fallback) is safe for tracking (the position always catches up). `maker_only` — only deliberately.

## 10. Phases
- **P1 (MVP):** primitives (book/limit-GTX/cancel/status) + `execution_mode=maker`: one post-only at the best price,
  `maker_wait_sec`, fallback to taker. pending-aware reconciliation. No chase.
- **P2:** chase / re-place (`maker_max_chases`), partial fills handled carefully.
- **P3 (optional):** userData WS for instant fill detection.

## 11a. Confirmed by research (web + local references) — specifics

Studied: **Hummingbot** (Apache-2.0, locally `~/Documents/hummingbot` — free to study),
**nautilus_trader** (LGPL-3.0), **freqtrade** (GPLv3 — patterns only, do not copy code),
**ccxt/python-binance/binance-connector** (MIT), and the local clean reference
`ProfitTrailer-2.5.72/study/binance_futures_client.py` (written from scratch "inspired by", NOT decompilation —
**a ready-made template of primitives**: `create_order`/`cancel_order`/`book_ticker`/`UserDataStream`).

**Exact Binance USDT-M mechanics (confirmed):**
- **Post-only = `type=LIMIT` + `timeInForce=GTX`** (NOT `LIMIT_MAKER` — that's spot-only!).
- **GTX-reject = synchronous REST error `-5022` GTX_ORDER_REJECT** on the POST itself (the order is NOT written to history → don't look for it later via GET, you'll get -2013). We interpret `-5022` as "would cross the book → re-place one tick inside / fall back to taker".
- **`newClientOrderId`** (regex `^[\.A-Z\:/a-z0-9_-]{1,36}$`) — we generate OUR OWN in advance as the primary key (idempotency, POST↔WS correlation, idempotent cancel via `origClientOrderId`). ⚠️ ProfitTrailer bakes in the broker prefix `x-K0X7lAfm…` and **skims a referral share off the turnover** — our tag is OUR OWN/empty, the fees are entirely ours.
- **Best bid/ask:** REST `/fapi/v1/ticker/bookTicker` (weight 2 with symbol) or WS `<symbol>@bookTicker` (lowercase in the path).
- **Cancel:** `DELETE /fapi/v1/order` (orderId|origClientOrderId), not on the book → `-2011`. Query → `-2013` if absent. Cancel-all `/fapi/v1/allOpenOrders`.
- **userData-WS (instant fill detection):** the `listenKey` lives **60 min** → keepalive PUT **every ~30 min IN A SEPARATE THREAD**; connect `wss://fstream.binance.com/ws/<listenKey>`, force-disconnect after 24h → auto-reconnect + new listenKey. Event **`ORDER_TRADE_UPDATE`** (under `o`): `c`=clientOrderId, `X`=status (FILLED/PARTIALLY_FILLED), `x`=execType (TRADE), `z`=cumulative filled, `l`/`L`=last fill qty/price, `ap`=average price. Fills are deduped by `trade_id`. On reconnect — a one-time `GET /fapi/v1/openOrders` for resync.
- **Rounding the limit-order price to `PRICE_FILTER.tickSize`** (we already have stepSize for qty — add tickSize for price), otherwise `-1013`.

**Key patterns (what to take):**
- **clientOrderId-keyed state** (Hummingbot/nautilus): our own id is primary, dedup by it, survives an ACK loss/restart.
- **Repricing with a tolerance-band** (Hummingbot): don't cancel+replace if the new target differs from the live order by less than a threshold OR its age < max_age. Kills churn and preserves queue position.
- **Cancel-and-chase with 2 safety rules** (freqtrade): (1) do NOT re-place a partially-filled order — reconcile the remainder separately; (2) do NOT place a replacement until the cancel is confirmed (otherwise double exposure).
- **Exchange-as-truth + cancel danglers at startup**: positions from positionRisk, open orders are queried; on restart we cancel our dangling orders.
- **Hybrid fill-detect**: userData-WS primary + REST polling fallback (silence >60s → poll every 5s, otherwise every 120s).

**What we ALREADY have (matching production-grade):** a layered `_request`+retry+rate-limit, HMAC signing, `sync_time` (-1021), exchangeInfo stepSize rounding, a TG queue (queue+worker+retry), a resilient HL WS (FillStream reconnect). → the connector foundation is already "grown-up grade".
**What to ADD for maker:** `book_ticker`, `limit_order(GTX)`, `cancel_order`, `order_status`, userData-WS (a ws client is needed: either a thin RFC6455 handroll, or the mini-dependency `websocket-client`), clientOrderId, pending-aware reconciliation, tolerance-band + cancel-and-chase, tickSize price rounding.
**What NOT to take (overkill):** the Hummingbot framework (Controller/Executor/Cython, SQL-recorder, BudgetChecker), nautilus event-sourcing/Cache, the freqtrade ORM/DCA engine. We take the logic, not the machinery. The primitives template is `study/binance_futures_client.py`.

## 11b. Order state machine + tracker ("the brains", from Hummingbot — a minimal port)

Studied production Hummingbot (Apache-2.0): `core/data_type/in_flight_order.py`, `connector/client_order_tracker.py`,
`connector/derivative/binance_perpetual/*`. We take the DESIGN, we write our own (without asyncio/cachetools/Cython —
our style: a dict under `self.lock` + persist to runtime JSON).

**State machine (our Order — a dict keyed by `client_order_id`):**
- Fields: `coid, symbol, side, type, qty, price, state, exchange_order_id, executed_qty, avg_price, fills{trade_id:…}, created_ts, updated_ts`.
- States: `PENDING_CREATE → OPEN → PARTIALLY_FILLED → FILLED | CANCELED | FAILED`.
- **TWO types of update (don't confuse them):** `order_update` (changes state, sets exchange_order_id once we learn it) and `trade_update` (a fill).
- **Fills are deduped by `trade_id`** (the same fill may arrive both from WS and from REST polling → don't double-count). `executed_qty/quote` accumulate, `avg_price` is recomputed from the fills.
- **`is_done`/`is_filled` = terminal state OR `executed_qty >= qty`** (KEY: a late FILLED never "gets stuck").

**Tracker (resilience to races/disconnects):**
- Three sets: `active` + `cached` (TTL ~30s — catches late updates for an already-closed order) + `lost` (after N=3 consecutive "not found" → mark, but do NOT delete — a late fill may still arrive). "fillable" = active+cached+lost.
- `order_not_found` counter per coid; -2013 (does not exist) / -2011 (unknown) — from the Binance constants.
- **exchange_order_id may be unknown right after the POST** (lost ACK) → we reconcile by `client_order_id`, we don't blindly re-place.

**Update sources (both feed the same `order_update`/`trade_update`, and trade_id dedup makes them idempotent):**
- **userData-WS `ORDER_TRADE_UPDATE`** (instant): fields under `o` — `c`=coid, `t`=trade_id, `X`=status, `z`=cumulative filled, `l`/`L`=last fill qty/price, `n`/`N`=fee/asset, `ap`=average. Status mapping: NEW→OPEN, FILLED→FILLED, PARTIALLY_FILLED→PARTIALLY_FILLED, EXPIRED→CANCELED, REJECTED→FAILED.
- **REST fallback**: `GET v1/order` (status) + `v1/userTrades` (fills) — when WS was silent/dropped.

**Persist + restart:** `to_json/from_json` → `runtime/maker_orders.json`. At startup: load the tracker, `GET order` for each open one, **cancel dangling orders**, reconcile the position to the target (exchange-as-truth).

**What we do NOT take from HB (and our differences):** no timer-framework/Cython/SQL-recorder; **we add a taker fallback** (HB has none — a GTX-reject there = FAILED and stop); **clientOrderId without a broker prefix** (HB bakes in `x-nbQe1H39`, PT — `x-K0X7lAfm`, both skim a referral share; our tag is our own/empty → the fees are entirely ours).

**The minimal set of "brains" for our bot:** an `Order` dict + an `OrderTracker` (active/cached/lost, update_order/update_trade with trade_id dedup, is_done by the dual condition) + persist + userData-WS (the `UserDataStream` class from `study/binance_futures_client.py` — a ready template) + a REST fallback. That is enough for resilient maker execution without a framework.

## 11. Test
- Testnet/dry: verify GTX placement, cancel, fallback, pending accounting (no duplicates).
- Small size on mainnet on a liquid name, then on an alt; confirm that the position converges to the target and that the spread is actually saved (compare avg-fill vs mark).
