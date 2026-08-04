# Operations — how it runs and how to control it

> A working cheat sheet for the bot: modes, toggles, config, safe deploy.
> Source of truth for the copier core is [COPIER-CORE.md](COPIER-CORE.md), for the maker path
> [MAKER-EXECUTION.md](MAKER-EXECUTION.md), for every setting [CONFIGURATION.md](CONFIGURATION.md).
> 🇷🇺 [Русская версия](OPERATIONS.ru.md).

## Live control (no restart)
- **Footer → ⚙️**: data source (poll/websocket — only while stopped), **Execution: Taker/Maker**,
  start/stop, PANIC.
- **Telegram → /menu**: a reply-keyboard remote (🔧 Synchronize / ▶️ Start / ⏹ Stop / 📊 Status /
  🚨 PANIC). `/sync` shows a preview with confirmation.

## Order execution (`execution_mode`)
- **taker** — market order, instant (you pay the spread). The safe default.
- **maker** — passive post-only limit (GTX) at the best price → waits `maker_wait_sec` (5) → if it
  doesn't fill / `-5022`, re-prices (`maker_max_chases` 1) → **falls back to taker** for the
  remainder. A **full close / PANIC is always taker** (guaranteed exit).
- Maker pays off on **alts** (wide spread + funding). On BTC/ETH it barely matters.
- If maker keeps missing on a thin alt (doesn't fill), flip to **Taker** in ⚙️.
- Logs: `🪙 … maker … (waiting)` = limit placed; `✅ …` = filled; `taker fallback` = finished at market.

## Proportion (honest)
`size = lead_size × (our_equity / lead_base)`, then the caps (`leverage_cap`,
`max_notional_per_coin_usd`). **Lead base = perp equity + spot cash (USDC/USDT)**
(`proportion_include_spot=true`) — this reflects the lead's true leverage to capital and doesn't
"breathe" as margin is shuffled perp↔spot. The monitor card shows `Spot` / `Capital (base)`.

## Auto-sync and manual scaling (`auto_sync`)
- **off (default)** — the copier applies only lead movements; it **does not revert your manual
  edits**. You can scale by hand.
- **🔧 Synchronize** (button / `/sync`) — a one-shot full sync to the lead: first a **preview**
  (what it will do + price deviation from the lead's entry + how many catch-ups favorability will
  cut) → ✅ Apply.
- **favorability gate** — opens/adds only if the price is no worse than the lead's entry
  (`favorability_tol_pct` 0.3%); exits are free. Protects "don't drift from the entry".

## Copy journal (the "Journal" tab)
- **Active / Paper (dry) / Closed.** A session = one period of copying a lead.
- **realized = bot trades only** (bot attribution via `_bot_orders`); a manual overlay is shown
  separately ("✋ manual overlay"). Funding is account-level.
- **Paper (DRY)** — a mark-to-market simulator on the HL mid price (no Binance).

## Monitor and alerts
- WS detection of trades from watched addresses. **Anti-spam**: large/terminal moves (open/close/
  flip, ≥ `monitor_instant_notional_usd`) fire instantly; small TWAP slices are collapsed into a
  **single summary** (📊, VWAP / N trades / window).
- **TG queue**: alerts are sent ~1/sec with a 429 retry → nothing is lost on bursts.

## Bot-vs-manual classifier (`manage_only_bot_positions`, default off)
When **on**: the bot manages only **its own** sub-position (`_bot_pos`, seeded to the current
position when enabled) and **leaves manual positions and other coins alone**. Repair clamps it to
reality. Enable from a clean/known position (the seed treats the current position as "the bot's").

## Safe deploy (dev → server)
`./deploy.sh --build` (rsync + restart; does NOT touch config/.env/runtime). On restart, `on_start`
brings up LIVE → the first tick reconciles to the lead.
- **If flat or in sync** — the restart won't move anything.
- **Risky to change the position?** DRY-first: temporarily set `on_start` `live:False` → come up in
  DRY → check `planned_orders` → flip to LIVE via the API → restore `on_start`.
- The live config (`config.json`) and state (`runtime/`) on the server are never overwritten by a
  deploy.

## Key config flags
`execution_mode` taker|maker · `maker_wait_sec`/`maker_max_chases`/`maker_fallback_taker` ·
`proportion_include_spot` · `auto_sync` · `manage_only_bot_positions` ·
`favorability_gate`/`favorability_tol_pct` · `leverage_cap`/`max_notional_per_coin_usd`/`leverage_mode` ·
`min_notional_roundup` · `data_mode` poll|ws ·
`monitor_instant_notional_usd`/`monitor_coalesce_quiet_sec`/`monitor_coalesce_max_sec`.
Full reference: [CONFIGURATION.md](CONFIGURATION.md).

## What to watch (copy-quality metrics)
- **Average entry** doesn't drift from the lead's entry (favorability holds it).
- **Risk**: your exposure/leverage ↔ the lead's risk (honest proportion + caps).
- **Funding** accrues (usually positive on alt shorts).
- Maker fill-rate vs taker fallback (from the 🪙 logs).
