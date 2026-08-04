# HL → Binance Copier — архитектура и хендофф

Копитрейдинг **без посредника**: источник сигналов — **Hyperliquid**, исполнение — **Binance
USDT-M Futures**, + веб-интерфейс (freqtrade-style) + монитор адресов с Telegram-алертами.
Заменяет платные сервисы ($29–199/мес + комиссия за копирование) — у нас только комса биржи.

## TL;DR запуск
```bash
cd hl-copier
.venv/bin/python tools/serve.py        # API + UI → http://127.0.0.1:8787
```
Старт/стоп/PANIC/dry↔live — кнопками в UI. (CLI: `tools/run_copier.py --live --loop`.)
Запускать ЛИБО serve.py, ЛИБО run_copier.py. **WS-режимы (копи-сокет, монитор) требуют `.venv`.**

## Окружение
- **Python 3.12** в `.venv` (3.14 не годится — нет wheel для `ckzg`; `constraints.txt` пинит `ckzg==1.0.2`).
- Фронт: `cd web && npm install && npm run build` (Vite → `web/dist`, отдаётся API).
  Стек: React + Mantine 7.13.4 + lightweight-charts 4 + @mantine/notifications + свой CalendarHeatmap.

## Поток данных
```
Hyperliquid (цели/мониторы)                    наш Binance
  REST clearinghouseState/allMids/userFills
  WebSocket userFills (копи-сокет + монитор)
        ▼
  core.plan.compute_plan (масштаб экспозиции под МОЙ эквити Binance, плечо fixed/mirror,
        │                 заморозка плюсовых на старте, кэпы, вайтлист, отсечка HIP-3)
        ▼
  execution.executor.build_orders(_hedge) → market-ордера (one-way reduceOnly / hedge positionSide)
        ▼  Binance Futures
```

## Структура
```
copier/
  config.py            load_config(), PROJECT_ROOT, CONFIG_DIR, runtime_path()
  secrets.py           ключи из .env (binance_keys, telegram_token, write_env — мерж без затирания)
  telegram.py          send_message() + get_updates() (Bot API: алерты + приём команд)
  hl/rest.py           HLInfo: meta, all_mids, clearinghouse_state, user_fills, open_orders
  hl/ws.py             stream_fills() (копи) + FillStream (монитор: 1 коннект, add() налету)
  core/positions.py    net_positions, account_value, price_move_pct
  core/events.py       classify_fill (по startPosition), classify_net_change
  core/sizing.py       desired_mirror, diff_orders
  core/plan.py         compute_plan (плечо+заморозка), resolve_leverage
  core/format.py       fmt_usd/fmt_qty/hhmmss/now_iso
  execution/binance.py BinanceFutures (подписанный REST stdlib): account, positions(_detail),
                       position_mode, set_leverage, market_order, klines, user_trades,
                       income, funding_rates, exchange_info, mark_prices. SYMBOL_MAP, round_step
  execution/executor.py build_orders (one-way) / build_orders_hedge / apply / render
server/
  controller.py        ЕДИНСТВЕННОЕ что торгует. Глобал `controller`. Содержит:
                       • цикл копира (poll/ws) + реконсиляция + close/panic
                       • лента активности копи-целей (REST 3с)
                       • МОНИТОР: WS FillStream алерты (мгновенно) + 30с-поллинг для UI-данных
                       • account_stats (uPnl/плечо/маржа/PnL-год/daily для хитмапа)
                       • Telegram: _tg_send, set_telegram, test_telegram (алерты trade/error/monitor)
  api.py               REST (http.server, localhost) + отдаёт web/dist
tools/                 serve.py(UI) · run_copier.py · detect.py · watch_fills.py ·
                       show_orders.py · plan.py · binance_check.py   (через _bootstrap.py)
web/src/
  App.jsx              шапка(бейджи, старт/стоп, dry↔live, опрос/сокет, PANIC) + табы + тосты
  tabs/Dashboard.jsx   Обзор перпов + CalendarHeatmap + позиции + желаемые + цели (компактно — НЕ трогать)
  tabs/Chart.jsx       lightweight-charts (свечи + маркеры наших сделок) + Binance-таблица позиций (клик→тикер)
  tabs/Monitor.jsx     адреса под наблюдением: метрики + 🔔 toggle + раскрытие (live 4с) + 📋 копир/«→ В копир»
  tabs/History.jsx     под-табы: Ордера / Исполнения / Позиции(история) — с нашего Binance (Дашборд НЕ трогаем)
  tabs/Logs.jsx        лента: monitor/target/trade/skip/error/hb + фильтр
  tabs/Settings.jsx    Fieldset-группы: плечо/риск, вайтлист, цели, ключи Binance, Telegram (+тест), ⓘ-подсказки
  CalendarHeatmap.jsx  свой календарь PnL (red/green, тянется на ширину)
config/  runtime/  .env  (.env и runtime — gitignored)
```

## REST API (localhost:8787)
- `GET /api/status` — режим, эквити, margin_ratio, позиции(+breakeven/liq/margin_type/funding), желаемое, план, заморозка, цели, hedge, data_mode, **tick_age_sec** (liveness: сек с последнего успешного тика)
- `GET /api/logs` · `GET /api/config` · `POST /api/config`
- `GET /api/account_stats` — uPnl, плечо аккаунта, использование маржи, PnL за год, daily{}
- `GET /api/klines?symbol&interval&limit` · `GET /api/trades?symbol`
- `GET /api/orders` (открытые) · `/api/fills` (исполнения userTrades) · `/api/position_history` (закрытые позиции, FIFO-реконструкция из филлов; кэш 25–30с)
- `GET /api/monitors` · `POST /api/monitor_add{address,name}` · `/monitor_remove` · `/monitor_toggle` · `/monitor_refresh`
- `POST /api/copy_set{address}` · `/api/copy_clear` — замыкает монитор↔копир (одна цель; clear = стоп без ликвидации)
- `POST /api/start{live,mode}` · `/stop` · `/close{symbol}` · `/panic` · `/enable{coin}`
- `POST /api/keys{api_key,api_secret}` · `/telegram{token,chat_id,enabled}` · `/telegram_test`
- `GET /api/auth_status` · `POST /api/login{password}` · `/api/ui_auth{password,enabled}` — авторизация UI

## Конфиг (config/config.json)
leverage_mode(fixed/mirror), fixed_leverage, mirror_max_leverage, leverage_cap, max_notional_per_coin_usd,
start_skip_open(profitable/all/none)+start_skip_profit_pct, coin_whitelist([]=все), skip_builder_dexs,
data_mode(poll/ws), poll_interval_sec, binance.network(testnet/mainnet), targets[],
monitors[]{address,name,alerts}, monitor_interval_sec, monitor_min_delta_pct, telegram{enabled,chat_id}.

## Монитор + Telegram
- Монитор — отдельный таб: сохраняешь адрес+имя, бот через **WebSocket userFills** шлёт в Telegram
  действия (открыл/долил/сократил/закрыл/разворот), имя берётся из метки. Колокол 🔔 — вкл/выкл по адресу.
- **WS-стрим монитора создаётся при старте в ГЛАВНОМ потоке** (`_start_monitor_ws`) — иначе SDK не доставляет;
  `add()` адресов налету = подписка на живой коннект.
- Telegram-алерты с тегами: **👁 Наблюдаемый** (монитор), **📋 Скопировано** (копи-исполнение), **❌ Ошибка**.
  Токен в `.env` (TELEGRAM_BOT_TOKEN), enabled+chat_id в конфиге. chat_id узнаётся через getUpdates бота.
- **Управление из Telegram (двусторонний)**: `_telegram_command_worker` long-poll'ит getUpdates,
  принимает команды ТОЛЬКО от своего chat_id: `/status /live /dry /stop /panic /restart /help`.
  `/restart` = `os.execv` (свежий процесс; позиции остаются, копир стартует в STOP).

## Liveness / монитор↔копир
- В шапке индикатор **На связи/Задержка/Нет связи** по `tick_age_sec` (сек с последнего успешного тика)
  + бейдж режима СОКЕТ/ОПРОС. Доказывает, что бот реально слушает сеть, а не завис.
- Из Монитора: **«→ В копир»** = `copy_set` (сделать адрес единственной целью copy), **«Убрать из копира»**
  = `copy_clear` (стоп бота + очистить цель, позиции НЕ ликвидируются). Работаем с ОДНИМ адресом.
  Копируемый адрес помечен 📋. Старт/стоп самого копира — кнопками в шапке.

## Авторизация UI
Логин-экран (`web/src/Login.jsx`): пароль → токен сессии. Гейт на все `/api/*` (кроме
`/api/login`, `/api/auth_status`) при `auth_enabled`. Пароль в `.env` (`UI_PASSWORD`,
constant-time сверка), токены в памяти (после рестарта — перелогин). По умолчанию ВЫКЛ
(localhost как раньше). Вкл в Настройках → «Доступ». Защищает только UI/API — канал шифровать
отдельно (Tailscale/TLS), особенно при выносе на Pi/в сеть.

## Нюансы / правила
- Копировать осмысленно МЕДЛЕННЫХ свингеров (net стабилен), не MM/квантов (net дёргается, мелочь < minNotional).
- Заморозка на старте — не входим в убежавшие в плюс позиции; разморозка при полном закрытии монеты целью.
- Hedge-аккаунт Binance: positionSide+без reduceOnly (определяется авто). One-way: reduceOnly.
- После правок бэкенда — **перезапуск serve.py**. Фронт — `npm run build` + refresh.
- ⚠️ НЕ тестировать на рабочем `config.json`/`.env` (можно затереть мониторы/ключи) — юзать временный порт.
- Сервер только 127.0.0.1; кнопки двигают реальные деньги; на ключе — запрет вывода + IP-whitelist.

## Статус
Работает на РЕАЛЬНОМ Binance (mainnet), hedge. Ключи Binance + Telegram-токен в `.env`.
Live-значения конфига меняются через UI — смотреть `config/config.json`.
