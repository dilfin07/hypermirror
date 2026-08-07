# HL → Binance copier

> 🇷🇺 [Русская версия](README.ru.md).

The "Kielwater" project.
**Hyperliquid = signal source** (that's where the traders we follow trade).
**Binance Futures = executor** (Phase 3).

The detector turns an HL trader's actions into normalized events, the planner
computes the desired positions for our deposit/risk, and the executor (Binance) applies them.

## Structure
```
hl-copier/
├── config/                  settings (config.json — gitignored)
│   ├── config.example.json  template
│   └── config_test.json     bots for observation testing
├── copier/                  logic package
│   ├── config.py            config loading, paths
│   ├── hl/                  Hyperliquid SOURCE
│   │   ├── rest.py          REST polling (stdlib)
│   │   └── ws.py            WebSocket push (needs SDK/.venv)
│   ├── core/                EXCHANGE-AGNOSTIC logic
│   │   ├── positions.py     parsing positions/equity
│   │   ├── events.py        action classification (fill + net-change)
│   │   ├── sizing.py        exposure scaling, diff orders
│   │   ├── plan.py          leverage (fixed/mirror) + freeze on start
│   │   └── format.py        output helpers
│   ├── execution/           EXECUTION (Binance)
│   │   ├── binance.py       Binance USDT-M Futures client (signed REST, stdlib)
│   │   └── executor.py      reconciler: desired positions → orders
│   └── secrets.py           reading keys from .env
├── tools/                   entry points (CLI)
│   ├── watch_fills.py       fills stream (observation): REST or --ws
│   ├── show_orders.py       lead's order grid in the book
│   ├── detect.py            NET-position change detector → events.jsonl
│   ├── plan.py              planner (dry-run, no Binance)
│   ├── binance_check.py     Binance keys/balance check
│   └── run_copier.py        MAIN loop: HL plan → Binance execution
├── config/, runtime/, .env  (.env and runtime — gitignored)
└── .venv/                   Python 3.12 + hyperliquid SDK
```

## Polling vs WebSocket
- **REST polling** (default): we query the API ourselves every N sec (`--poll N`).
  No dependencies (stdlib), latency up to N sec. Fine for copying slow swingers.
- **WebSocket** (`--ws` on watch_fills): the event arrives instantly (push), needs the SDK
  (`.venv/bin/python`). For observing fast / low-latency traders.

## Commands
```bash
cd hl-copier
cp config/config.example.json config/config.json     # once; edit to taste

# observing fills (REST):
python3 tools/watch_fills.py 0x1111111111111111111111111111111111111111 --poll 4
# the same via WebSocket (instant, needs venv):
.venv/bin/python tools/watch_fills.py 0x1111111111111111111111111111111111111111 --ws

python3 tools/show_orders.py <addr> [--coin BTC]      # lead's order grid
python3 tools/detect.py --loop                         # NET-position change detector
python3 tools/detect.py --config config_test.json --loop   # on active bots
python3 tools/plan.py [--loop]                         # copy plan (dry-run)
```

## Binance (Phase 3)
1. Keys: `cp .env.example .env`, fill in `BINANCE_API_KEY/SECRET` (for testing — from
   https://testnet.binancefuture.com, Futures permissions). Network — in `config.binance.network`.
2. Check: `python3 tools/binance_check.py` (ping + balance + positions).
3. Main loop (DRY-RUN by default — sends NOTHING):
   ```bash
   python3 tools/run_copier.py            # one pass, dry-run
   python3 tools/run_copier.py --loop     # loop, dry-run
   python3 tools/run_copier.py --live --loop   # LIVE mode
   ```
   Equity is taken from Binance (if keys are present), positions are reconciled to the plan:
   leverage (fixed/mirror) → market orders (reduce-only on close), rounding to
   the symbol's filters, skipping below minNotional. Symbol mapping: BTC→BTCUSDT etc.
4. **Before `--live`:** run `--loop` in dry-run, make sure the orders are sane;
   start on testnet or with a small balance; Binance account mode — **one-way** (not hedge).

## Settings (config/config.json)
- `account_address`, `targets[]` ({address, weight, label}).
- **Leverage:** `leverage_mode` = `fixed` (`fixed_leverage`x) | `mirror` (same as the lead,
  no higher than `mirror_max_leverage`; auto-picks up the lead's leverage changes).
- **Start:** `start_skip_open` = `profitable` (freeze open positions in profit
  `>= start_skip_profit_pct`%) | `all` | `none`. A frozen coin unfreezes
  after its lead FULLY closes it → then a new entry is copied.
- **Risk:** `leverage_cap`, `max_notional_per_coin_usd`, `coin_whitelist`, `skip_builder_dexs`.
- `min_event_delta_pct` — detector threshold (% position change).

## Phases
- [x] P1 Read-only HL client (REST)  • [x] P2 Detector + observation + plan (dry-run)
- [ ] P3 Binance executor (symbols, leverage, reduce-only, abort on slippage)
- [ ] P4 Resilience+risk (reconnect, kill-switch, loss limit, alerts)
- [ ] P5 Run: dry-run on signals → small live

## Web interface (freqtrade-style, Mantine)
```
server/        backend: controller.py (loop+actions) + api.py (REST, localhost)
web/           frontend: React + Mantine + Vite (Dashboard/Logs/Settings tabs)
tools/serve.py launches API + static files
```
Run:
```bash
cd hl-copier/web && npm install && npm run build      # once (build the frontend)
cd .. && .venv/bin/python tools/serve.py               # → http://127.0.0.1:8787
# (python3 also works, but "Socket" mode requires .venv — the SDK lives there)
# frontend development: cd web && npm run dev  (→ :5173, proxies /api to :8787)
```
The data mode is switched by a toggle in the header (or in Settings):
**Polling** — REST every N sec; **Socket** — instant reconciliation on the lead's trades
(fallback every 60s). The mode can only be changed while the bot is stopped.
- **Dashboard:** open copies (+ a "Close" button on each), desired positions,
  leads' positions; in the header — start/stop, dry↔live, **🚨 PANIC** (close everything + stop).
- **Logs:** event/order feed.
- **Settings:** leverage and mode, risk caps, pair whitelist, targets, Binance keys.
- The backend is the only one that trades; the frontend only pokes the API. The buttons move
  real money → the server listens only on **127.0.0.1**. Run EITHER `serve.py`
  OR `run_copier.py`, not both at once (double execution).

## Environment
Python 3.12 (3.14 won't do — no wheel for ckzg). `constraints.txt` pins `ckzg==1.0.2`.
Install: `.venv/bin/pip install -r requirements.txt -c constraints.txt`.
REST tools work on the system `python3` too (stdlib only); `--ws` and P3 — via `.venv`.
