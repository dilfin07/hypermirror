# HL → Binance copier

Проект «это что за покемон».
**Hyperliquid = источник сигналов** (там торгуют те, за кем следим).
**Binance Futures = исполнитель** (Фаза 3).

Детектор превращает действия HL-трейдера в нормализованные события, планировщик
считает желаемые позиции под наш депозит/риск, исполнитель (Binance) их применяет.

## Структура
```
hl-copier/
├── config/                  настройки (config.json — gitignored)
│   ├── config.example.json  шаблон
│   └── config_test.json     боты для теста наблюдения
├── copier/                  пакет с логикой
│   ├── config.py            загрузка конфига, пути
│   ├── hl/                  ИСТОЧНИК Hyperliquid
│   │   ├── rest.py          REST-поллинг (stdlib)
│   │   └── ws.py            WebSocket push (нужен SDK/.venv)
│   ├── core/                БИРЖА-АГНОСТИК логика
│   │   ├── positions.py     разбор позиций/эквити
│   │   ├── events.py        классификация действий (fill + net-change)
│   │   ├── sizing.py        масштаб экспозиции, diff-ордера
│   │   ├── plan.py          плечо (fixed/mirror) + заморозка на старте
│   │   └── format.py        хелперы вывода
│   ├── execution/           ИСПОЛНЕНИЕ (Binance)
│   │   ├── binance.py       клиент Binance USDT-M Futures (подписанный REST, stdlib)
│   │   └── executor.py      реконсилятор: желаемые позиции → ордера
│   └── secrets.py           чтение ключей из .env
├── tools/                   точки входа (CLI)
│   ├── watch_fills.py       поток филлов (наблюдение): REST или --ws
│   ├── show_orders.py       сетка ордеров цели в стакане
│   ├── detect.py            детектор изменений NET-позиции → events.jsonl
│   ├── plan.py              планировщик (dry-run, без Binance)
│   ├── binance_check.py     проверка ключей/баланса Binance
│   └── run_copier.py        ГЛАВНЫЙ цикл: HL план → Binance исполнение
├── config/, runtime/, .env  (.env и runtime — gitignored)
└── .venv/                   Python 3.12 + hyperliquid SDK
```

## Polling vs WebSocket
- **REST-поллинг** (по умолчанию): сами спрашиваем API раз в N сек (`--poll N`).
  Без зависимостей (stdlib), задержка до N сек. Для копирования медленных свингеров — ок.
- **WebSocket** (`--ws` у watch_fills): событие прилетает мгновенно (push), нужен SDK
  (`.venv/bin/python`). Для наблюдения за быстрыми / низкой задержки.

## Команды
```bash
cd hl-copier
cp config/config.example.json config/config.json     # один раз; правь под себя

# наблюдение за филлами (REST):
python3 tools/watch_fills.py 0x1111111111111111111111111111111111111111 --poll 4
# то же через WebSocket (мгновенно, нужен venv):
.venv/bin/python tools/watch_fills.py 0x1111111111111111111111111111111111111111 --ws

python3 tools/show_orders.py <addr> [--coin BTC]      # сетка ордеров цели
python3 tools/detect.py --loop                         # детектор изменений NET-позиции
python3 tools/detect.py --config config_test.json --loop   # на активных ботах
python3 tools/plan.py [--loop]                         # план копирования (dry-run)
```

## Binance (Фаза 3)
1. Ключи: `cp .env.example .env`, вписать `BINANCE_API_KEY/SECRET` (для теста — с
   https://testnet.binancefuture.com, права Futures). Сеть — в `config.binance.network`.
2. Проверка: `python3 tools/binance_check.py` (ping + баланс + позиции).
3. Главный цикл (DRY-RUN по умолчанию — НИЧЕГО не шлёт):
   ```bash
   python3 tools/run_copier.py            # один проход, dry-run
   python3 tools/run_copier.py --loop     # цикл, dry-run
   python3 tools/run_copier.py --live --loop   # БОЕВОЙ режим
   ```
   Эквити берётся с Binance (если ключи есть), позиции сводятся к плану:
   плечо (fixed/mirror) → market-ордера (reduce-only на закрытие), округление к
   фильтрам символа, пропуск ниже minNotional. Маппинг символов: BTC→BTCUSDT и т.д.
4. **Перед `--live`:** прогони `--loop` в dry-run, убедись что ордера адекватны;
   начни на testnet или мелким балансом; режим аккаунта Binance — **one-way** (не hedge).

## Настройки (config/config.json)
- `account_address`, `targets[]` ({address, weight, label}).
- **Плечо:** `leverage_mode` = `fixed` (`fixed_leverage`x) | `mirror` (как у цели,
  не выше `mirror_max_leverage`; авто-подхватывает смену плеча у цели).
- **Старт:** `start_skip_open` = `profitable` (заморозить открытые с прибылью
  `>= start_skip_profit_pct`%) | `all` | `none`. Замороженная монета размораживается
  после ПОЛНОГО закрытия её целью → тогда новый вход копируется.
- **Риск:** `leverage_cap`, `max_notional_per_coin_usd`, `coin_whitelist`, `skip_builder_dexs`.
- `min_event_delta_pct` — порог детектора (% изменения позиции).

## Фазы
- [x] Ф1 Read-only клиент HL (REST)  • [x] Ф2 Детектор + наблюдение + план (dry-run)
- [ ] Ф3 Binance-исполнитель (символы, плечо, reduce-only, abort по слиппеджу)
- [ ] Ф4 Устойчивость+риск (реконнект, kill-switch, лимит убытка, алерты)
- [ ] Ф5 Прогон: dry-run на сигналах → мелкий live

## Веб-интерфейс (freqtrade-style, Mantine)
```
server/        бэкенд: controller.py (цикл+действия) + api.py (REST, localhost)
web/           фронт: React + Mantine + Vite (табы Дашборд/Логи/Настройки)
tools/serve.py запуск API + статики
```
Запуск:
```bash
cd hl-copier/web && npm install && npm run build      # один раз (собрать фронт)
cd .. && .venv/bin/python tools/serve.py               # → http://127.0.0.1:8787
# (python3 тоже работает, но режим «Сокет» требует .venv — там стоит SDK)
# разработка фронта: cd web && npm run dev  (→ :5173, проксирует /api на :8787)
```
Режим данных переключается тумблером в шапке (или в Настройках):
**Опрос** — REST раз в N сек; **Сокет** — мгновенная реконсиляция по сделкам цели
(фолбэк раз в 60с). Менять режим можно только когда бот остановлен.
- **Дашборд:** открытые копии (+ кнопка «Закрыть» на каждой), желаемые позиции,
  позиции целей; в шапке — старт/стоп, dry↔live, **🚨 PANIC** (закрыть всё + стоп).
- **Логи:** лента событий/ордеров.
- **Настройки:** плечо и режим, риск-кэпы, вайтлист пар, цели, ключи Binance.
- Бэкенд — единственный, кто торгует; фронт только дёргает API. Кнопки двигают
  реальные деньги → сервер слушает только **127.0.0.1**. Запускай ЛИБО `serve.py`,
  ЛИБО `run_copier.py`, не оба сразу (двойное исполнение).

## Окружение
Python 3.12 (3.14 не годится — нет wheel для ckzg). `constraints.txt` зажимает `ckzg==1.0.2`.
Установка: `.venv/bin/pip install -r requirements.txt -c constraints.txt`.
REST-инструменты работают и на системном `python3` (только stdlib); `--ws` и Ф3 — через `.venv`.
