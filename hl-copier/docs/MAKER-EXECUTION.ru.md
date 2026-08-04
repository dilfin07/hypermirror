# Мейкер-исполнение копира — дизайн-спека (НЕ реализовано, план на будущее)

> Статус: проект. Сейчас движок шлёт только `market_order` (тейкер). Этот документ —
> спека для добавления пассивного (мейкер) исполнения, чтобы копировать трейдеров,
> чей эдж — в мейкер-исполнении (пассивный набор лимитками + фандинг на неликвиде,
> напр. альт-фейдер `0x92bbd811…`: ASTER/NEAR/ZEC/ZRO, набор шорта за часы).

## 1. Зачем
- Тейкером мы **платим спред** на каждом копи-ордере. На неликвидных альтах спред
  жирный — это и есть эдж копируемого трейдера, который мы сейчас дарим бирже.
- Мейкером **ловим спред (или хотя бы не платим его)** + потенциально фандинг.
- На BTC/ETH смысла мало (спред ~1bp) — фича целевая под **альты**.

## 2. Конфиг
```
"execution_mode": "taker" | "maker" | "maker_only"   // дефолт taker (как сейчас)
"maker_offset_ticks": 0          // на сколько тиков от лучшей цены ставить (0 = на лучшей)
"maker_wait_sec": 8              // сколько ждать филла перед перестановкой
"maker_max_chases": 2            // сколько раз переставлять, прежде чем фолбэк
"maker_fallback_taker": true     // после max_chases добить рынком (гарантия трекинга)
```
- `taker` — текущее поведение.
- `maker` — **maker-first, taker-fallback** (рекомендуемый): пытаемся пассивно, не вышло — добиваем рынком.
- `maker_only` — только пост-онли, без фолбэка (РИСК недо-исполнения/дрейфа от цели).

## 3. Новые примитивы (`copier/execution/binance.py`)
Сейчас есть только `market_order`. Добавить:
- `book_ticker(symbol)` → лучший bid/ask (публичный `/fapi/v1/ticker/bookTicker`).
- `limit_order(symbol, side, qty, price, post_only=True, position_side=...)` → лимитка
  с `timeInForce=GTX` (post-only: биржа отклонит, если ордер пересёк бы стакан = стал тейкером).
- `cancel_order(symbol, order_id)` и `cancel_all(symbol)`.
- `order_status(symbol, order_id)` → статус/исполненный объём (или брать из `open_orders_all` + `user_trades`).

## 4. Состояние (Controller)
- `self._maker_orders = {}` — `(symbol, position_side) -> {order_id, side, qty, price, placed_ts, chases}`.
  Персист в runtime (чтобы после рестарта отменить висяки). На старте — `cancel_all` по нашим символам, сброс.

## 5. Поток (на каждый реконсиляционный тик, для `maker`)
Вместо «посчитал дельту → market_order»:
1. Посчитать целевую дельту по символу (как сейчас, build_orders/_hedge).
2. **Учесть висящие мейкер-ордера** (см. §6): нужная_дельта = desired − (filled + pending).
3. Если есть наш резткий ордер по символу:
   - **исполнился/частично** → обновить позицию, остаток оставить/переставить;
   - **цена ушла** (наш ордер уже не у лучшей) ИЛИ истёк `maker_wait_sec` → `cancel` + переставить у новой лучшей цены, `chases++`;
   - `chases ≥ maker_max_chases` и `maker_fallback_taker` → отменить, **добить `market_order`** на нужную_дельту.
4. Если ордера нет и нужна_дельта ≠ 0 → поставить `limit_order(GTX)` у лучшей цены на своей стороне:
   - покупка (закрытие шорта / лонг) → у лучшего **bid**;
   - продажа (шорт / закрытие лонга) → у лучшего **ask**.
5. **Полное закрытие/срочное** (panic, выход лида) → всегда **тейкер** (мейкер нельзя — можем не успеть).

## 6. Реконсиляция с учётом pending (КРИТИЧНО)
Сейчас дифф = `desired` против `filled` (позиция на бирже). С мейкером появляются
**висящие ордера**, и если их не учитывать — на каждом тике настакаем дубли.
→ `effective_current = filled_position + sum(наши открытые maker-ордера по символу)`.
Диффить `desired` против `effective_current`. `build_orders/_hedge` принимают «current»,
поэтому передавать туда **filled + pending наших ордеров**.

## 7. Краевые случаи
- **Частичный филл** — учесть исполненную часть, остаток в ордере; не дублировать.
- **Post-only reject** (цена пересеклась) — ретрай у новой лучшей цены.
- **Цель быстро двинулась, мы не исполнились** — `maker` фолбэкнет в тейкер; `maker_only` отстанет (дрейф — флаг риска).
- **favorability-gate** — применять к цене ЛИМИТКИ (а не марка): постим только если наша лимит-цена не хуже входа цели.
- **Рестарт** — отменить все наши висящие ордера на старте (иначе зомби-ордера).
- **Отмена не прошла** (ордер уже исполнился между проверкой и cancel) — обработать как филл.

## 8. Детект исполнения
Опрос статуса каждый тик дорог; варианты:
- из `open_orders_all` (что ещё висит) + `positions` (что исполнилось) — диффом;
- либо `user_trades` по символу (есть orderId) — точные филлы наших ордеров.
WS userData-stream Binance (ORDER_TRADE_UPDATE) — точнее всего, но это ещё один WS-слой (later).

## 9. Трейдоффы / безопасность
- Мейкер-филл НЕ гарантирован → возможен лаг входа. Для медленных пассивных целей (часы) — ок;
  для скальперов — промах (для них вообще не копируем).
- Больше движущихся частей → больше отказов. Поэтому **MVP = одна попытка GTX + таймаут + тейкер-фолбэк**,
  без агрессивного chase. Chase/мульти-перестановка — фаза 2.
- `maker` (с фолбэком) безопасен по трекингу (позиция всегда догонит). `maker_only` — только осознанно.

## 10. Фазы
- **Ф1 (MVP):** примитивы (book/limit-GTX/cancel/status) + `execution_mode=maker`: один пост-онли у лучшей цены,
  `maker_wait_sec`, фолбэк в тейкер. pending-aware реконсиляция. Без chase.
- **Ф2:** chase/перестановка (`maker_max_chases`), частичные филлы аккуратно.
- **Ф3 (опц.):** userData WS для мгновенного детекта филлов.

## 11а. Подтверждено ресёрчем (веб + локальные референсы) — конкретика

Изучено: **Hummingbot** (Apache-2.0, локально `~/Documents/hummingbot` — изучать свободно),
**nautilus_trader** (LGPL-3.0), **freqtrade** (GPLv3 — только паттерны, код не копировать),
**ccxt/python-binance/binance-connector** (MIT), и локальный чистый референс
`ProfitTrailer-2.5.72/study/binance_futures_client.py` (написан с нуля «по мотивам», НЕ декомпиляция —
**готовый шаблон примитивов**: `create_order`/`cancel_order`/`book_ticker`/`UserDataStream`).

**Точная механика Binance USDT-M (подтверждено):**
- **Post-only = `type=LIMIT` + `timeInForce=GTX`** (НЕ `LIMIT_MAKER` — это спот-онли!).
- **GTX-reject = синхронная REST-ошибка `-5022` GTX_ORDER_REJECT** на самом POST (ордер НЕ записывается в историю → не искать его потом через GET, получишь -2013). `-5022` трактуем как «пересёк бы стакан → переставить на тик внутрь / фолбэк в тейкер».
- **`newClientOrderId`** (regex `^[\.A-Z\:/a-z0-9_-]{1,36}$`) — генерим СВОЙ заранее как первичный ключ (идемпотентность, корреляция POST↔WS, идемпотентный cancel через `origClientOrderId`). ⚠️ ProfitTrailer вшивает брокерский префикс `x-K0X7lAfm…` и **скимит реф-долю с оборота** — у нас тег СВОЙ/пустой, комса целиком наша.
- **Лучший бид/аск:** REST `/fapi/v1/ticker/bookTicker` (вес 2 с symbol) или WS `<symbol>@bookTicker` (lowercase в пути).
- **Cancel:** `DELETE /fapi/v1/order` (orderId|origClientOrderId), не на книге → `-2011`. Query → `-2013` если нет. Cancel-all `/fapi/v1/allOpenOrders`.
- **userData-WS (мгновенный детект филлов):** `listenKey` живёт **60 мин** → keepalive PUT **каждые ~30 мин В ОТДЕЛЬНОМ ПОТОКЕ**; коннект `wss://fstream.binance.com/ws/<listenKey>`, форс-разрыв через 24ч → авто-reconnect + новый listenKey. Событие **`ORDER_TRADE_UPDATE`** (под `o`): `c`=clientOrderId, `X`=статус (FILLED/PARTIALLY_FILLED), `x`=execType (TRADE), `z`=накоплено исполнено, `l`/`L`=последний филл qty/цена, `ap`=средняя цена. Филлы дедупим по `trade_id`. На реконнекте — разовый `GET /fapi/v1/openOrders` для ресинка.
- **Округление цены лимитки под `PRICE_FILTER.tickSize`** (у нас уже есть stepSize для qty — добавить tickSize для price), иначе `-1013`.

**Ключевые паттерны (что забрать):**
- **clientOrderId-keyed state** (Hummingbot/nautilus): свой id первичен, дедуп по нему, переживает обрыв ACK/рестарт.
- **Реприсинг с tolerance-band** (Hummingbot): не cancel+replace, если новая цель отличается от живого ордера меньше порога ИЛИ возраст < max_age. Убивает churn и бережёт очередь.
- **Cancel-and-chase с 2 правилами безопасности** (freqtrade): (1) НЕ переставлять частично-исполненный ордер — остаток реконсилим отдельно; (2) НЕ ставить замену, пока cancel не подтверждён (иначе двойная экспозиция).
- **Exchange-as-truth + cancel danglers на старте**: позиции из positionRisk, открытые ордера запрашиваем; на рестарте отменяем свои висяки.
- **Hybrid fill-detect**: userData-WS основной + REST-поллинг фолбэк (тишина >60с → опрос 5с, иначе 120с).

**Что у нас УЖЕ есть (совпадает с боевыми):** слоистый `_request`+retry+rate-limit, HMAC-подпись, `sync_time` (-1021), exchangeInfo stepSize-округление, очередь TG (queue+worker+retry), устойчивый WS HL (FillStream reconnect). → connector-фундамент уже «как у взрослых».
**Что ДОБАВИТЬ под мейкер:** `book_ticker`, `limit_order(GTX)`, `cancel_order`, `order_status`, userData-WS (нужен ws-клиент: либо тонкий хэндрол RFC6455, либо мини-деп `websocket-client`), clientOrderId, pending-aware реконсиляция, tolerance-band + cancel-and-chase, tickSize-округление цены.
**Что НЕ брать (оверкилл):** фреймворк Hummingbot (Controller/Executor/Cython, SQL-recorder, BudgetChecker), event-sourcing/Cache nautilus, ORM/DCA-движок freqtrade. Берём логику, не машинерию. Шаблон примитивов — `study/binance_futures_client.py`.

## 11б. Стейт-машина ордера + трекер («мозги», из Hummingbot — минимальный порт)

Изучен боевой Hummingbot (Apache-2.0): `core/data_type/in_flight_order.py`, `connector/client_order_tracker.py`,
`connector/derivative/binance_perpetual/*`. Берём ДИЗАЙН, пишем своё (без asyncio/cachetools/Cython —
наш стиль: dict под `self.lock` + персист в runtime JSON).

**Стейт-машина (наш Order — dict по `client_order_id`):**
- Поля: `coid, symbol, side, type, qty, price, state, exchange_order_id, executed_qty, avg_price, fills{trade_id:…}, created_ts, updated_ts`.
- Состояния: `PENDING_CREATE → OPEN → PARTIALLY_FILLED → FILLED | CANCELED | FAILED`.
- **ДВА типа апдейта (не путать):** `order_update`(меняет state, проставляет exchange_order_id когда узнали) и `trade_update`(филл).
- **Филлы дедупим по `trade_id`** (один и тот же филл может прийти и из WS, и из REST-поллинга → не задвоить). `executed_qty/quote` копим, `avg_price` пересчитываем из филлов.
- **`is_done`/`is_filled` = терминальный state ИЛИ `executed_qty >= qty`** (КЛЮЧЕВОЕ: запоздавший FILLED никогда не «застревает»).

**Трекер (устойчивость к гонкам/обрывам):**
- Три набора: `active` + `cached` (TTL ~30с — ловит запоздавшие апдейты по уже закрытому ордеру) + `lost` (после N=3 «not found» подряд → пометить, но НЕ удалять — поздний филл ещё может прийти). «fillable» = active+cached+lost.
- `order_not_found` счётчик на coid; -2013 (не существует) / -2011 (unknown) — из констант Binance.
- **exchange_order_id может быть неизвестен сразу после POST** (потерян ACK) → реконсилим по `client_order_id`, не перевыставляем вслепую.

**Источники апдейтов (оба кормят те же `order_update`/`trade_update`, дедуп по trade_id делает их идемпотентными):**
- **userData-WS `ORDER_TRADE_UPDATE`** (мгновенно): поля под `o` — `c`=coid, `t`=trade_id, `X`=статус, `z`=накоплено исполнено, `l`/`L`=последний филл qty/цена, `n`/`N`=комиссия/актив, `ap`=средняя. Статус-маппинг: NEW→OPEN, FILLED→FILLED, PARTIALLY_FILLED→PARTIALLY_FILLED, EXPIRED→CANCELED, REJECTED→FAILED.
- **REST-фолбэк**: `GET v1/order` (статус) + `v1/userTrades` (филлы) — когда WS молчал/обрыв.

**Персист + рестарт:** `to_json/from_json` → `runtime/maker_orders.json`. На старте: загрузить трекер, по каждому открытому `GET order`, **отменить висяки**, свести позицию к цели (exchange-as-truth).

**Чего у HB НЕ берём (и наши отличия):** нет таймера-фреймворка/Cython/SQL-recorder; **добавляем taker-fallback** (у HB его нет — GTX-reject у них = FAILED и стоп); **clientOrderId без брокерского префикса** (HB вшивает `x-nbQe1H39`, PT — `x-K0X7lAfm`, оба скимят реф-долю; у нас тег свой/пустой → комса целиком наша).

**Минимальный набор «мозгов» для нашего бота:** `Order`-dict + `OrderTracker` (active/cached/lost, update_order/update_trade с trade_id-дедупом, is_done по двойному условию) + персист + userData-WS (класс `UserDataStream` из `study/binance_futures_client.py` — готовый шаблон) + REST-фолбэк. Этого достаточно для устойчивого мейкер-исполнения без фреймворка.

## 11. Тест
- Testnet/dry: проверить постановку GTX, отмену, фолбэк, pending-учёт (нет дублей).
- Малый размер на mainnet на ликвиде, затем на альте; сверить, что позиция сходится к цели и спред реально экономится (сравнить avg-fill vs mark).
