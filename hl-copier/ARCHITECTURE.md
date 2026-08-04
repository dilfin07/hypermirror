# HL → Binance Copier — architecture and handoff

> 🇷🇺 [Русская версия](ARCHITECTURE.ru.md).

Copytrading **without a middleman**: the signal source is **Hyperliquid**, execution is on **Binance
USDT-M Futures**, plus a web interface (freqtrade-style) plus an address monitor with Telegram alerts.
Replaces paid services ($29–199/mo + a copying fee) — with us it's just the exchange's fee.

## TL;DR launch
```bash
cd hl-copier
.venv/bin/python tools/serve.py        # API + UI → http://127.0.0.1:8787
```
Start/stop/PANIC/dry↔live — via buttons in the UI. (CLI: `tools/run_copier.py --live --loop`.)
Run EITHER serve.py OR run_copier.py. **WS modes (copy socket, monitor) require `.venv`.**

## Environment
- **Python 3.12** in `.venv` (3.14 won't do — there's no wheel for `ckzg`; `constraints.txt` pins `ckzg==1.0.2`).
- Frontend: `cd web && npm install && npm run build` (Vite → `web/dist`, served by the API).
  Stack: React + Mantine 7.13.4 + lightweight-charts 4 + @mantine/notifications + a custom CalendarHeatmap.

## Data flow
```
Hyperliquid (leads/monitors)                    our Binance
  REST clearinghouseState/allMids/userFills
  WebSocket userFills (copy socket + monitor)
        ▼
  core.plan.compute_plan (scale exposure to MY Binance equity, leverage fixed/mirror,
        │                 freeze profitable positions at start, caps, whitelist, HIP-3 cutoff)
        ▼
  execution.executor.build_orders(_hedge) → market orders (one-way reduceOnly / hedge positionSide)
        ▼  Binance Futures
```

## Structure
```
copier/
  config.py            load_config(), PROJECT_ROOT, CONFIG_DIR, runtime_path()
  secrets.py           keys from .env (binance_keys, telegram_token, write_env — merge without overwriting)
  telegram.py          send_message() + get_updates() (Bot API: alerts + receiving commands)
  hl/rest.py           HLInfo: meta, all_mids, clearinghouse_state, user_fills, open_orders
  hl/ws.py             stream_fills() (copy) + FillStream (monitor: 1 connection, add() on the fly)
  core/positions.py    net_positions, account_value, price_move_pct
  core/events.py       classify_fill (by startPosition), classify_net_change
  core/sizing.py       desired_mirror, diff_orders
  core/plan.py         compute_plan (leverage+freeze), resolve_leverage
  core/format.py       fmt_usd/fmt_qty/hhmmss/now_iso
  execution/binance.py BinanceFutures (signed REST, stdlib): account, positions(_detail),
                       position_mode, set_leverage, market_order, klines, user_trades,
                       income, funding_rates, exchange_info, mark_prices. SYMBOL_MAP, round_step
  execution/executor.py build_orders (one-way) / build_orders_hedge / apply / render
server/
  controller.py        THE ONLY thing that trades. Global `controller`. Contains:
                       • copier loop (poll/ws) + reconciliation + close/panic
                       • activity feed of copy leads (REST 3s)
                       • MONITOR: WS FillStream alerts (instant) + 30s polling for UI data
                       • account_stats (uPnl/leverage/margin/PnL-year/daily for the heatmap)
                       • Telegram: _tg_send, set_telegram, test_telegram (trade/error/monitor alerts)
  api.py               REST (http.server, localhost) + serves web/dist
tools/                 serve.py(UI) · run_copier.py · detect.py · watch_fills.py ·
                       show_orders.py · plan.py · binance_check.py   (via _bootstrap.py)
web/src/
  App.jsx              header (badges, start/stop, dry↔live, poll/socket, PANIC) + tabs + toasts
  tabs/Dashboard.jsx   Perps overview + CalendarHeatmap + positions + desired + leads (compact — DON'T touch)
  tabs/Chart.jsx       lightweight-charts (candles + markers of our trades) + Binance positions table (click→ticker)
  tabs/Monitor.jsx     watched addresses: metrics + 🔔 toggle + expand (live 4s) + 📋 copier/"→ To copier"
  tabs/History.jsx     sub-tabs: Orders / Fills / Positions(history) — from our Binance (leave Dashboard alone)
  tabs/Logs.jsx        feed: monitor/target/trade/skip/error/hb + filter
  tabs/Settings.jsx    Fieldset groups: leverage/risk, whitelist, leads, Binance keys, Telegram (+test), ⓘ tooltips
  CalendarHeatmap.jsx  custom PnL calendar (red/green, stretches to width)
config/  runtime/  .env  (.env and runtime — gitignored)
```

## REST API (localhost:8787)
- `GET /api/status` — mode, equity, margin_ratio, positions (+breakeven/liq/margin_type/funding), desired, plan, freeze, leads, hedge, data_mode, **tick_age_sec** (liveness: seconds since the last successful tick)
- `GET /api/logs` · `GET /api/config` · `POST /api/config`
- `GET /api/account_stats` — uPnl, account leverage, margin usage, PnL for the year, daily{}
- `GET /api/klines?symbol&interval&limit` · `GET /api/trades?symbol`
- `GET /api/orders` (open) · `/api/fills` (userTrades fills) · `/api/position_history` (closed positions, FIFO reconstruction from fills; cache 25–30s)
- `GET /api/monitors` · `POST /api/monitor_add{address,name}` · `/monitor_remove` · `/monitor_toggle` · `/monitor_refresh`
- `POST /api/copy_set{address}` · `/api/copy_clear` — links monitor↔copier (single lead; clear = stop without liquidation)
- `POST /api/start{live,mode}` · `/stop` · `/close{symbol}` · `/panic` · `/enable{coin}`
- `POST /api/keys{api_key,api_secret}` · `/telegram{token,chat_id,enabled}` · `/telegram_test`
- `GET /api/auth_status` · `POST /api/login{password}` · `/api/ui_auth{password,enabled}` — UI authorization

## Config (config/config.json)
leverage_mode(fixed/mirror), fixed_leverage, mirror_max_leverage, leverage_cap, max_notional_per_coin_usd,
start_skip_open(profitable/all/none)+start_skip_profit_pct, coin_whitelist([]=all), skip_builder_dexs,
data_mode(poll/ws), poll_interval_sec, binance.network(testnet/mainnet), targets[],
monitors[]{address,name,alerts}, monitor_interval_sec, monitor_min_delta_pct, telegram{enabled,chat_id}.

## Monitor + Telegram
- The monitor is a separate tab: you save an address+name, and the bot, via **WebSocket userFills**, sends to Telegram
  the actions (opened/added/reduced/closed/reversed); the name is taken from the label. The 🔔 bell — on/off per address.
- **The monitor's WS stream is created at startup on the MAIN thread** (`_start_monitor_ws`) — otherwise the SDK won't deliver;
  `add()`-ing addresses on the fly = subscribing on a live connection.
- Telegram alerts with tags: **👁 Watched** (monitor), **📋 Copied** (copy fill), **❌ Error**.
  Token in `.env` (TELEGRAM_BOT_TOKEN), enabled+chat_id in the config. chat_id is discovered via the bot's getUpdates.
- **Control from Telegram (two-way)**: `_telegram_command_worker` long-polls getUpdates,
  accepts commands ONLY from its own chat_id: `/status /live /dry /stop /panic /restart /help`.
  `/restart` = `os.execv` (fresh process; positions remain, the copier starts in STOP).

## Liveness / monitor↔copier
- In the header, an indicator **Online/Delayed/Offline** based on `tick_age_sec` (seconds since the last successful tick)
  plus a mode badge SOCKET/POLL. Proves the bot is actually listening to the network and hasn't hung.
- From the Monitor: **"→ To copier"** = `copy_set` (make the address the single copy lead), **"Remove from copier"**
  = `copy_clear` (stop the bot + clear the lead, positions are NOT liquidated). We work with ONE address.
  The copied address is marked 📋. Start/stop of the copier itself — via buttons in the header.

## UI authorization
Login screen (`web/src/Login.jsx`): password → session token. A gate on all `/api/*` (except
`/api/login`, `/api/auth_status`) when `auth_enabled`. Password in `.env` (`UI_PASSWORD`,
constant-time comparison), tokens in memory (after a restart — re-login). OFF by default
(localhost as before). Enable in Settings → "Access". Protects only the UI/API — encrypt the channel
separately (Tailscale/TLS), especially when exposing it on a Pi/to the network.

## Nuances / rules
- It makes sense to copy SLOW swingers (net is stable), not MMs/quants (net jitters, small change < minNotional).
- Freeze at start — we don't enter positions that have run into profit; unfreeze when the lead fully closes the coin.
- Binance hedge account: positionSide + no reduceOnly (detected automatically). One-way: reduceOnly.
- After backend edits — **restart serve.py**. Frontend — `npm run build` + refresh.
- ⚠️ Do NOT test against the working `config.json`/`.env` (you can wipe monitors/keys) — use a temporary port.
- Server is 127.0.0.1 only; the buttons move real money; on the API key — disable withdrawals + IP whitelist.

## Status
Runs on REAL Binance (mainnet), hedge. Binance keys + Telegram token are in `.env`.
Live config values are changed via the UI — see `config/config.json`.
