# Configuration reference

Every setting hypermirror understands: what it does, its default, where it lives, and how
it interacts with the others. Settings are stored in `config/config.json` and most are
editable live from the dashboard's **Settings** panel.

- **Scope `per-account`** — belongs to one copy account (a Binance key + its target list).
  You can run several accounts with different risk profiles.
- **Scope `global`** — one value for the whole process.
- **Scope `hardcoded`** — a constant in code, not exposed in the UI (documented here so you
  can change it in a fork).

Values below show the **code default**; a fresh `config.example.json` may set different
starting values.

---

## 1. Targets & proportion

### `targets[]` · per-account
The Hyperliquid lead wallet(s) you copy. Each entry:

```json
{ "address": "0x…", "weight": 1.0, "label": "my lead" }
```

- `address` — the lead's Hyperliquid wallet (public; no keys needed to read it).
- `weight` — relative share when copying **several** leads at once. With one lead it's just `1.0`.
- `label` — a name shown in the UI and Telegram alerts.

Your exposure to each coin is the weighted sum across all targets, taken as a proportion of
**your** equity.

### `proportion_include_spot` · per-account · default `true`
Chooses the lead's **base capital** for the proportion:

- `true` — base = `max(perp equity, spot USDC)`. This matches what dashboards like Hyperdash
  show and treats spot USDC as the cushion backing the perp account.
- `false` — base = perp equity only.

> Why `max`, not the sum: spot USDC *backs* the perp account — it's the same money seen two
> ways. Summing them would double-count and halve your copied size.

### `size_multiplier` · per-account · default `1.0`
A coefficient applied to the lead's proportion **before** the leverage cap and margin buffer.

- `1.0` — one-to-one (lead opens at 2% of their bank → you at ~2% of yours).
- `0.5` — half as aggressive. `2.0` — twice as aggressive.
- `≤ 0` — treated as `1.0` (never zeroes or inverts direction).

The gross leverage cap (below) is still the ceiling on top of this.

---

## 2. Risk caps

These apply in this exact order: **per-coin cap → size multiplier → gross leverage cap →
per-position leverage → margin buffer**.

### `max_notional_per_coin_usd` · per-account · default `1e12` (effectively off)
Hard ceiling on the notional in any single coin, in USD. Stops one instrument from taking
your whole risk budget. Set e.g. `50000` to cap each coin at $50k.

### `leverage_cap` · per-account · default `5`
Cap on your **gross** exposure = `sum(|notional|)` relative to your equity.

- If `gross > equity × leverage_cap`, every position is scaled down proportionally.
- Example: the lead runs 467% exposure; with `leverage_cap = 3` you're clamped to 3×.
- **`0` (or negative) = no cap** — a full mirror of the lead's exposure (their leverage
  becomes yours). Use only if you truly want the lead's risk on a small account.

This is the main protection for a small account copying a large, leveraged lead.

### `leverage_mode` · per-account · default `mirror`
How the **per-position** leverage is chosen:

- `mirror` — take the lead's leverage, capped by `mirror_max_leverage`.
- `fixed` — always use `fixed_leverage`, regardless of the lead.

### `mirror_max_leverage` · per-account · default `10`
Ceiling on per-position leverage in `mirror` mode. If the lead uses 20×, this caps it.

### `fixed_leverage` · per-account · default `3`
The per-position leverage used when `leverage_mode = fixed`.

> Leverage affects the **margin** a position ties up, not its notional size. Size comes from
> the proportion and caps above; leverage decides how much margin backs that size.

### `margin_buffer_pct` · **hardcoded** · default `0.10`
Keeps a reserve of margin so orders don't fail. If the total initial margin required by the
plan exceeds `equity × (1 − buffer)`, the whole plan is scaled down.

- Prevents Binance `-2019 Margin insufficient` when the desired size needs ~100% of equity.
- Not in the UI. To change it, edit `cfg.get("margin_buffer_pct", 0.10)` in
  `copier/core/plan.py` (clamped to `[0, 0.9]`).

---

## 3. Entry & sync gates

### `favorability_gate` · per-account · default `true`
Protects your average entry: on an **open or add**, skip the order if the price is worse than
the lead's average entry by more than the tolerance. **Reductions and full closes are never
gated** — you always follow the lead out.

### `favorability_tol_pct` · per-account · default `0.3`
The tolerance, in percent. For a long, adds are allowed while `price ≤ lead_entry × (1 + tol%)`.

- Higher (e.g. `1`) → tracks the lead's proportion more tightly, but sometimes adds slightly
  above their average.
- Lower / `0` → protects your average harder, but you'll lag the lead's size more when price
  runs above their entry.

### `auto_sync` · per-account · default `false`
What the bot does with orders that aren't driven by a fresh lead move.

- `false` — apply **only orders from an actual lead movement**. "Catch-up" edits (undoing your
  manual trims, restoring caps after drift) are deferred until you press **Synchronize**. This
  is what lets your manual overlay coexist with the bot.
- `true` — also apply catch-up automatically, always converging to the full mirror.

### `manage_only_bot_positions` · per-account · default `false`
Which position the bot reconciles.

- `false` — the bot treats your **whole** position on that symbol as the copy.
- `true` — the bot reconciles **only its own sub-position** (tracked via order attribution) and
  leaves your manual trades alone.

### `min_notional_roundup` · global · default `true`
When a lead's leg is below the exchange minimum:

- `true` — a sub-minimal **opening** leg is rounded up to `minNotional` (otherwise you could
  never copy a small position). Other sub-minimal changes are dead-banded (left alone) to
  avoid churn.
- `false` — sub-minimal legs are skipped.

---

## 4. What gets copied

### `coin_whitelist` · per-account · default `[]` (copy-all)
Restrict copying to a set of coins, e.g. `["BTC", "ETH", "HYPE"]`. Empty = copy everything the
lead trades. Coins outside the list are skipped.

### `skip_builder_dexs` · global · default `true`
Skip Hyperliquid builder-deployed perps (HIP-3, coins namespaced with `:` such as
`xyz:SPCX`). These are exotic markets (tokenized stocks, commodities, pre-IPO) that don't
exist on Binance and can't be mirrored.

### `start_skip_open` · per-account · default `profitable`
On **adopt** (first tick after start/switch), which of the lead's already-open positions to
**freeze** (not copy):

- `profitable` — freeze positions already up more than `start_skip_profit_pct`.
- `all` — freeze every already-open position; copy only new ones the lead opens later.
- `none` — copy everything from the start.

Frozen coins unfreeze automatically when the lead closes them.

### `start_skip_profit_pct` · per-account · default `5`
The profit threshold (percent) for `start_skip_open = profitable`. Don't jump into a move the
lead is already deep in.

---

## 5. Execution

### `execution_mode` · per-account · default `taker`
- `taker` — market orders (immediate fill).
- `maker` — post-only limit orders first (better fees / price), with a taker fallback.

A **full close always goes taker**, regardless of this setting, to guarantee the exit.

### `maker_wait_sec` · per-account · default `5`
In maker mode, how long to wait for a post-only limit order to fill before re-pricing.

### `maker_max_chases` · per-account · default `1`
How many times to re-price (chase) the maker order before falling back.

### `maker_fallback_taker` · per-account · default `true`
If the maker order didn't fully fill within the chases, take the remainder at market.

---

## 6. System

### `poll_interval_sec` · global · default `30`
How often the tick loop runs when not driven by websocket events.

### `data_mode` · global · default `ws`
- `ws` — subscribe to Hyperliquid websocket for instant lead-move triggers.
- `poll` — REST polling only, at `poll_interval_sec`.

### `monitor_alert_ttl_sec` · global
De-duplication window for the address **monitor**'s Telegram alerts (see
[MONITOR.md](MONITOR.md)).

### `accounts` / `active_account` · global
The set of copy accounts and which one is currently active. Per-account settings (everything
marked *per-account* above) are stored under each account.

---

## Environment (`.env`, never committed)

| Variable | Purpose |
|---|---|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Your Binance Futures API key (futures trading enabled). |
| `TELEGRAM_BOT_TOKEN` | Optional — enables Telegram alerts and remote commands. |
| `UI_PASSWORD` | Dashboard login password for LIVE mode. |
| `HLC_CONFIG_DIR` / `HLC_RUNTIME_DIR` / `HLC_ENV_FILE` | Optional overrides to run a second isolated instance (different config/runtime/port). |

Template: [`.env.example`](../.env.example). Real secrets stay only in `.env`, which is
git-ignored.

---

## Current production profile (example)

A conservative, small-account setup that respects manual overlay:

```
leverage_mode        mirror
leverage_cap         3        # gross exposure capped at 3×
mirror_max_leverage  100      # per-position cap effectively off
margin_buffer_pct    0.10     # hardcoded
size_multiplier      1.0
favorability_gate    on
favorability_tol_pct 1        # add within 1% of the lead's entry
auto_sync            off      # follow new lead moves; keep manual trims
execution_mode       maker
proportion_include_spot on
data_mode            ws
poll_interval_sec    30
```
