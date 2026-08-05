"""Контроллер: гоняет цикл копира в фоне, держит состояние, выполняет действия.

Единственное место, которое трогает Binance. API дёргает его методы.
"""
import html
import itertools
import json
import os
import queue
import threading
import time

from copier.config import load_config, runtime_path, CONFIG_DIR, atomic_write_json
from copier.secrets import binance_keys, telegram_token, write_env, get as env_get
from copier.hl.rest import HLInfo, MAINNET as HL_MAIN, TESTNET as HL_TEST
from copier.core.format import now_iso
from copier.core.accounts import resolve_targets
from copier.execution.binance import BinanceFutures, symbol_filters
from server._telegram import TelegramMixin
from server._monitor import MonitorMixin
from server._status import StatusMixin
from server._engine import EngineMixin
from server._journal import JournalMixin


class Controller(EngineMixin, MonitorMixin, StatusMixin, TelegramMixin, JournalMixin):
    def __init__(self):
        self.lock = threading.RLock()
        self.logs = []                 # [{ts, level, msg}]
        self.running = False
        self.live = False
        self.thread = None
        self.disabled = set()          # монеты, временно отключённые (после ручного close)
        self.status = {"ready": False}
        self._status_ts = 0
        self.data_mode = "poll"        # poll | ws
        self._wake = threading.Event() # триггер реконсиляции в ws-режиме
        self._ws_started = False
        self._seen_fills = {}          # addr -> set(tid) для ленты активности
        self._fills_seeded = set()     # addr, где историю уже проглотили
        self._act_ts = 0               # троттл опроса активности
        self._hb_ts = 0                # троттл heartbeat
        self._last_skips = set()
        self._mon_view = {}     # addr -> готовые данные для UI
        self._mon_snap = {}     # addr -> {coin: snap} предыдущий снимок для backstop-диффа
        self._mon_builder = {}  # addr -> {positions, snap} позиции на builder-dexs (HIP-3), опрос реже
        self._builder_dexs = None  # кэш списка builder-deployed перп-dexs
        self._mon_alert_seen = {}  # (addr,coin,action) -> ts последнего алерта (дедуп WS↔опрос)
        self._mon_pending = {}     # (addr,coin) -> бакет коалесинга мелких TWAP-филлов (anti-spam)
        self._copier_fs = None     # FillStream целей копира (для статус-бара)
        self._hl_ok_ts = 0         # ts последнего удачного REST-ответа Hyperliquid
        self._bn_ok_ts = 0         # ts последнего удачного REST-ответа Binance
        self._last_mon_event_ts = 0  # ts последнего события монитора (WS/опрос)
        self._prev_tgt_pos = {}    # symbol -> szi цели на прошлом торговом тике (источник алерта: трейдер vs реконсиляция)
        self._force_sync = False   # разовый флаг ручной синхронизации (TG-кнопка) при auto_sync=off
        self._adopt_next = False   # adopt при старте/переключении: подхватить позиции счёта без форс-догона
        self._last_compute = None  # снимок последнего расчёта для превью синхры (sync_preview)
        self._spot_cache = {}      # addr -> (ts, spot_usd) для честной пропорции (TTL 60с)
        self._tg_queue = queue.PriorityQueue(maxsize=1000)  # очередь отправки в TG: копи/управление вперёд, монитор после; протухший монитор дропается
        self._tg_seq = itertools.count()  # стабильный порядок внутри приоритета (FIFO при равном prio)
        self._tg_dedup = {}        # текст -> (ts последней отправки, сколько повторов подавлено)
        self._tg_ok_ts = 0         # ts последней УСПЕШНОЙ отправки в TG (health-пайплайна)
        self._tg_fail = None       # {ts, err} последней неудачной отправки в TG
        self._fill_stream = None       # None=не пробовали · False=init упал (ретрай по кулдауну) · объект=живой
        self._fill_stream_fail_ts = 0.0  # ts последней неудачи init WS-стрима (кулдаун ретрая)
        self._tokens = set()    # активные сессии UI
        self._bot_orders = set()  # orderId ордеров, размещённых НАМИ (бот/UI), для метки бот/ручное
        self._bot_save_ts = 0
        self._acct_active = {}     # key_env -> ts последней активности счёта (аудит «живой/заброшен»)
        self._acct_active_ts = 0   # троттл записи accounts_active.json
        self._reload()
        self._load_logs()
        self._load_bot_orders()
        self._bot_pos = {}             # (symbol, positionSide) -> signed qty: позиция, набранная БОТОМ
        self._bot_pos_seeded = False   # классификатор bot-vs-manual: seed = текущая позиция на enable
        self._load_bot_pos()
        self._load_acct_active()
        self._load_sessions()
        self.data_mode = self.cfg.get("data_mode", "poll")
        self._install_excepthooks()    # любое НЕОБРАБОТАННОЕ исключение → в лог, а не в тишину
        threading.Thread(target=self._activity_worker, daemon=True).start()
        threading.Thread(target=self._monitor_worker, daemon=True).start()
        threading.Thread(target=self._builder_monitor_worker, daemon=True).start()
        threading.Thread(target=self._mon_flush_worker, daemon=True).start()
        threading.Thread(target=self._tg_sender_worker, daemon=True).start()
        threading.Thread(target=self._telegram_command_worker, daemon=True).start()
        self._start_monitor_ws()

    def _install_excepthooks(self):
        """Ловим НЕОБРАБОТАННЫЕ исключения глобально — в потоках и в главном.

        Наши фоновые циклы обёрнуты в try/except, но это подстраховка на всё остальное:
        колбэки WS-SDK, init потоков, любой непокрытый путь. Без хука такое падало бы в
        stderr (в journald, куда никто не смотрит) и терялось. Теперь — с полным
        трейсбеком в единый лог (и в Telegram как error)."""
        import sys
        import traceback

        def _fmt(exc_type, exc_value, exc_tb, where):
            tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            return f"UNHANDLED [{where}]: {exc_type.__name__}: {exc_value}\n{tb[-2000:]}"

        def _thread_hook(args):
            if args.exc_type is SystemExit:
                return
            name = args.thread.name if args.thread else "?"
            try:
                self.log(_fmt(args.exc_type, args.exc_value, args.exc_traceback, f"thread {name}"), "error")
            except Exception:
                pass

        def _main_hook(exc_type, exc_value, exc_tb):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_tb)
                return
            try:
                self.log(_fmt(exc_type, exc_value, exc_tb, "main"), "error")
            except Exception:
                pass

        threading.excepthook = _thread_hook
        sys.excepthook = _main_hook

    # ---------- инициализация ----------
    def _active_account(self):
        """Запись активного счёта (key_env/type/network). Дефолт — main/BINANCE/futures (обратная совместимость)."""
        accts = self.cfg.get("accounts") or []
        aid = self.cfg.get("active_account", "main")
        rec = next((a for a in accts if a.get("id") == aid), None)
        return rec or {"id": "main", "key_env": "BINANCE", "type": "futures",
                       "network": (self.cfg.get("binance") or {}).get("network", "mainnet")}

    def _acct_file(self, base):
        """Имя runtime-файла состояния АКТИВНОГО счёта. main/BINANCE → старые имена
        (обратная совместимость с боевым состоянием), прочие счета → суффикс __{key_env}."""
        ke = (self._active_account().get("key_env") or "BINANCE")
        if ke == "BINANCE":
            return base
        stem, dot, ext = base.rpartition(".")
        return f"{stem}__{ke}.{ext}" if dot else f"{base}__{ke}"

    def _reload(self):
        self._cfg_raw = load_config()                        # сырой конфиг (defaults + accounts) — для записи/редактирования
        self.cfg = dict(self._cfg_raw)                       # временно = raw, чтобы _active_account прочитал accounts/active
        acct = self._active_account()                        # бот торгует на АКТИВНОМ счёте
        ov = acct.get("overrides") or {}
        if ov:
            self.cfg.update(ov)                              # ЭФФЕКТИВНЫЙ конфиг = defaults ⊕ оверрайды активного счёта (targets/плечо/гейт/... )
        # Цель копирования НЕ наследуется между счетами: не-main без своей цели = пусто
        # (а не молча цель main). У каждого счёта своя независимая цель.
        is_main = acct.get("id", "main") == "main"
        self._tg_token = telegram_token()   # ДО первого log(): иначе ошибка внутри _reload падает в _tg_send и валит старт
        self.cfg["targets"] = resolve_targets(is_main, self._cfg_raw.get("targets"), ov.get("targets"))
        self.hl = HLInfo(HL_TEST if self.cfg.get("network") == "testnet" else HL_MAIN)
        self.account_type = acct.get("type", "futures")      # futures | copy | spot — для type-specific нюансов
        key, secret = binance_keys(acct.get("key_env", "BINANCE"))
        net = acct.get("network") or (self.cfg.get("binance") or {}).get("network", "testnet")
        self.account_net = net                               # сеть активного счёта (для статуса/бейджа)
        self.bn = BinanceFutures(key, secret, network=net)
        self.have_keys = bool(key and secret)
        self._lead_symbols = None                            # кэш whitelist копи-портфеля (ленивая загрузка)
        self.filters = {}
        self._filters_ts = 0      # ts последней ПОПЫТКИ загрузить фильтры (кулдаун ленивого добора)
        self.ensure_filters()     # сеть на старте может быть не готова (ребут/DNS) — не фатально, доберём позже
        csp = runtime_path(self._acct_file(self.cfg.get("copy_state_file", "copy_state.json")))
        self.copy_state = json.load(open(csp)) if os.path.exists(csp) else {}
        self._load_bot_orders()   # атрибуция и сабпозиция — состояние АКТИВНОГО счёта (важно при переключении)
        self._load_bot_pos()

    def ensure_filters(self):
        """Фильтры биржи (шаг лота/цены, minNotional) — без них НЕЛЬЗЯ считать размеры ордеров.
        На старте их могло не быть (после ребута Pi сеть/DNS поднимаются позже сервиса), поэтому
        добираем лениво на тиках, не чаще раза в 30с. Возвращает True, если фильтры на руках."""
        if self.filters:
            return True
        if time.time() - self._filters_ts < 30:
            return False
        self._filters_ts = time.time()
        try:
            self.filters = symbol_filters(self.bn.exchange_info())
            if self.filters:
                self.log(f"[copy] exchangeInfo: filters loaded ({len(self.filters)} symbols)", "info", tg=False)
        except Exception as e:
            self.log(f"[copy] exchangeInfo: {e}", "error")
        return bool(self.filters)

    def _save_copy_state(self):
        csp = runtime_path(self._acct_file(self.cfg.get("copy_state_file", "copy_state.json")))
        atomic_write_json(csp, self.copy_state, indent=2)

    def _load_acct_active(self):
        """last_active по счетам (key_env -> ts) — отметки в runtime, не в профиле."""
        self._acct_active = {}
        p = runtime_path("accounts_active.json")
        if os.path.exists(p):
            try:
                self._acct_active = {str(k): float(v) for k, v in json.load(open(p)).items()}
            except Exception:
                pass

    def _stamp_active(self, force=False):
        """Отметить активность текущего счёта (пока торгует/при переключении). Запись троттлится."""
        ke = self._active_account().get("key_env") or "BINANCE"
        now = time.time()
        self._acct_active[ke] = now
        if force or now - self._acct_active_ts > 60:
            self._acct_active_ts = now
            try:
                atomic_write_json(runtime_path("accounts_active.json"), self._acct_active, indent=2)
            except Exception:
                pass

    def _save_raw(self):
        """Сохранить СЫРОЙ конфиг (defaults + accounts). Эффективный self.cfg — только для чтения."""
        atomic_write_json(os.path.join(CONFIG_DIR, "config.json"), self._cfg_raw, indent=2, ensure_ascii=False)

    def _set_global(self, key, val):
        """Глобальный параметр → top-level сырого конфига (+ синхр эффективного), сохранить."""
        self._cfg_raw[key] = val
        self.cfg[key] = val
        self._save_raw()

    def _set_active_targets(self, targets):
        """Цель копирования — на АКТИВНЫЙ счёт (не-main → в его overrides, main → top-level)."""
        raw = self._cfg_raw
        aid = raw.get("active_account", "main")
        acct = next((a for a in (raw.get("accounts") or []) if a.get("id") == aid), None) if aid != "main" else None
        if acct is not None:
            acct.setdefault("overrides", {})["targets"] = targets
        else:
            raw["targets"] = targets
        self.cfg["targets"] = targets        # эффективный — сразу
        self._save_raw()

    def _load_logs(self):
        p = runtime_path("log.jsonl")
        if os.path.exists(p):
            try:
                # читаем ТОЛЬКО хвост (последние ~512 КБ), а не весь файл: при 45 МБ логе
                # read() тянул бы всё в память ради последних 300 строк.
                size = os.path.getsize(p)
                with open(p, "rb") as f:
                    if size > 512 * 1024:
                        f.seek(size - 512 * 1024)
                        f.readline()                       # отбросить обрезанную первую строку
                    tail = f.read().decode("utf-8", errors="replace")
                out = []
                for x in tail.splitlines()[-300:]:
                    if not x.strip():
                        continue
                    try:
                        out.append(json.loads(x))       # битую строку пропускаем, не теряем весь хвост
                    except Exception:
                        continue
                self.logs = out
            except Exception:
                pass

    def _load_bot_orders(self):
        self._bot_orders = set()                       # сброс — не тащить атрибуцию прошлого счёта
        p = runtime_path(self._acct_file("bot_orders.json"))
        if os.path.exists(p):
            try:
                self._bot_orders = set(json.load(open(p)))
            except Exception:
                pass

    def _record_bot_order(self, resp):
        oid = (resp or {}).get("orderId") if isinstance(resp, dict) else resp
        if oid in (None, "", "ok"):
            return
        self._bot_orders.add(str(oid))
        if len(self._bot_orders) > 6000:
            self._bot_orders = set(list(self._bot_orders)[-3000:])
        if time.time() - self._bot_save_ts > 5:
            self._bot_save_ts = time.time()
            try:
                atomic_write_json(runtime_path(self._acct_file("bot_orders.json")), list(self._bot_orders))
            except Exception:
                pass

    def _load_bot_pos(self):
        self._bot_pos = {}; self._bot_pos_seeded = False   # сброс — состояние сабпозиции прошлого счёта не тащим
        p = runtime_path(self._acct_file("bot_pos.json"))
        if os.path.exists(p):
            try:
                d = json.load(open(p))
                self._bot_pos_seeded = bool(d.get("seeded"))
                self._bot_pos = {tuple(k.split("|")): float(v) for k, v in (d.get("pos") or {}).items()}
            except Exception:
                pass

    def _save_bot_pos(self):
        try:
            atomic_write_json(runtime_path(self._acct_file("bot_pos.json")),
                              {"seeded": self._bot_pos_seeded,
                               "pos": {f"{s}|{ps}": q for (s, ps), q in self._bot_pos.items()}}, indent=2)
        except Exception:
            pass

    # ---------- запись лога: один handle, ротация по размеру ----------
    LOG_MAX_BYTES = 20 * 1024 * 1024   # порог ротации log.jsonl (~20 МБ)
    LOG_KEEP = 3                        # сколько поколений держать: .1 .2 .3

    def _log_write(self, entry):
        """Дозапись строки в log.jsonl через ОДИН открытый handle (не open на каждую
        запись — экономит syscalls и ресурс SD-карты на Pi). Ротация по размеру.
        Вызывается под self.lock. Ошибки глушим — лог не должен ронять бота."""
        try:
            if getattr(self, "_log_fh", None) is None:
                p = runtime_path("log.jsonl")
                self._log_bytes = os.path.getsize(p) if os.path.exists(p) else 0
                self._log_fh = open(p, "a", encoding="utf-8")
            row = json.dumps(entry, ensure_ascii=False) + "\n"
            self._log_fh.write(row)
            self._log_fh.flush()
            self._log_bytes += len(row.encode("utf-8"))
            if self._log_bytes > self.LOG_MAX_BYTES:
                self._rotate_log()
        except Exception:
            self._log_fh = None            # уроним handle → следующий вызов переоткроет

    def _rotate_log(self):
        """log.jsonl → .1 → .2 → .3 (старшее удаляется). Держим ограниченную историю,
        чтобы файл не рос бесконечно (был 45 МБ без ротации)."""
        try:
            if self._log_fh:
                self._log_fh.close()
            base = runtime_path("log.jsonl")
            old = f"{base}.{self.LOG_KEEP}"
            if os.path.exists(old):
                os.remove(old)
            for i in range(self.LOG_KEEP - 1, 0, -1):
                src = f"{base}.{i}"
                if os.path.exists(src):
                    os.replace(src, f"{base}.{i + 1}")
            os.replace(base, f"{base}.1")
        except Exception:
            pass
        finally:
            self._log_fh = None
            self._log_bytes = 0

    def log(self, msg, level="info", tg=True):
        entry = {"ts": now_iso(), "level": level, "msg": str(msg)}
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > 500:
                self.logs = self.logs[-500:]
            self._log_write(entry)
        if not tg:
            return                                   # tg=False — только в UI-лог (богатый алерт шлём отдельно)
        if level == "trade":
            self._tg_send(f"📋 <b>Copied</b>\n{msg}")
        elif level == "error":
            # escape: в текст ошибки попадает «<urlopen error ...>» — Telegram считает это
            # битой разметкой, отбивает 400, и сообщение уходит повтором уже без parse_mode
            # (в чате видны сырые теги). ttl — не доставлять протухшее после долгого обрыва.
            self._tg_send(f"❌ <b>Error</b>\n{html.escape(str(msg))}", ttl=self.TG_ERROR_TTL, dedup=True)

    # Telegram (_tg_send / команды / _restart / set_telegram / test_telegram) → TelegramMixin (server/_telegram.py)

    # Ядро (активность/heartbeat, _compute/циклы, start/stop/close/panic) → EngineMixin (server/_engine.py)
    # Монитор → MonitorMixin · UI-данные/статус → StatusMixin · Telegram → TelegramMixin
    # ---------- статус / конфиг ----------
    def get_logs(self):
        with self.lock:
            return list(self.logs)

    def get_config(self):
        c = dict(self.cfg)
        c.pop("paper_equity_usd", None)
        accts = c.get("accounts") or [{"id": "main", "label": "Main", "key_env": "BINANCE",
                                       "type": "futures",
                                       "network": (c.get("binance") or {}).get("network", "mainnet")}]
        # обогащаем last_active (ts последней активности счёта) для аудита «живой/заброшен» в UI
        accts = [dict(a, last_active=self._acct_active.get(a.get("key_env") or "BINANCE", 0)) for a in accts]
        return {
            "accounts": accts,                       # профили API + last_active
            "active_account": c.get("active_account", "main"),
            "leverage_mode": c.get("leverage_mode"),
            "fixed_leverage": c.get("fixed_leverage"),
            "mirror_max_leverage": c.get("mirror_max_leverage"),
            "leverage_cap": c.get("leverage_cap"),
            "max_notional_per_coin_usd": c.get("max_notional_per_coin_usd"),
            "start_skip_open": c.get("start_skip_open"),
            "start_skip_profit_pct": c.get("start_skip_profit_pct"),
            "coin_whitelist": c.get("coin_whitelist"),
            "poll_interval_sec": c.get("poll_interval_sec"),
            "data_mode": c.get("data_mode", "poll"),
            "favorability_gate": c.get("favorability_gate", True),
            "favorability_tol_pct": c.get("favorability_tol_pct", 0.3),
            "min_notional_roundup": c.get("min_notional_roundup", True),
            # эхо остальных редактируемых полей (set_config их принимает) — чтобы UI показывал реальные значения
            "execution_mode": c.get("execution_mode", "taker"),
            "auto_sync": c.get("auto_sync", False),
            "proportion_include_spot": c.get("proportion_include_spot", True),
            "size_multiplier": c.get("size_multiplier", 1.0),
            "manage_only_bot_positions": c.get("manage_only_bot_positions", False),
            "skip_builder_dexs": c.get("skip_builder_dexs", True),
            "maker_wait_sec": c.get("maker_wait_sec", 5),
            "maker_max_chases": c.get("maker_max_chases", 1),
            "maker_fallback_taker": c.get("maker_fallback_taker", True),
            "monitor_instant_notional_usd": c.get("monitor_instant_notional_usd", 10000),
            "monitor_coalesce_quiet_sec": c.get("monitor_coalesce_quiet_sec", 45),
            "monitor_coalesce_max_sec": c.get("monitor_coalesce_max_sec", 300),
            "monitor_alert_ttl_sec": c.get("monitor_alert_ttl_sec"),
            "binance_network": (c.get("binance") or {}).get("network"),
            "targets": c.get("targets"),
            "has_keys": self.have_keys,
            "telegram": {
                "enabled": (c.get("telegram") or {}).get("enabled", False),
                "chat_id": (c.get("telegram") or {}).get("chat_id", ""),
                "has_token": bool(self._tg_token),
            },
            "auth_enabled": c.get("auth_enabled", False),
            "has_ui_password": bool(env_get("UI_PASSWORD")),
        }

    # параметры, которые могут быть СВОИ на каждый счёт (идут в overrides не-main счёта)
    PER_ACCOUNT = {"targets", "execution_mode", "leverage_mode", "fixed_leverage", "mirror_max_leverage",
                   "leverage_cap", "max_notional_per_coin_usd", "coin_whitelist", "favorability_gate",
                   "favorability_tol_pct", "auto_sync", "manage_only_bot_positions", "start_skip_open",
                   "start_skip_profit_pct", "maker_wait_sec", "maker_max_chases", "maker_fallback_taker",
                   "proportion_include_spot", "size_multiplier"}   # база пропорции (общий банк vs только перп) — своя на счёт
    # глобальные — одни на весь процесс (всегда в top-level), общие для всех счетов
    GLOBAL = {"poll_interval_sec", "data_mode", "min_notional_roundup",
              "monitor_instant_notional_usd", "monitor_coalesce_quiet_sec", "monitor_coalesce_max_sec",
              "monitor_alert_ttl_sec", "skip_builder_dexs", "accounts", "active_account"}

    def set_config(self, patch):
        with self.lock:
            raw = self._cfg_raw                              # пишем в СЫРОЙ конфиг (не в эффективный self.cfg)
            aid = raw.get("active_account", "main")
            # для НЕ-main активного счёта параметры-счёта пишем в его overrides; main = defaults (top-level)
            acct = next((a for a in (raw.get("accounts") or []) if a.get("id") == aid), None) if aid != "main" else None
            ov = acct.setdefault("overrides", {}) if acct else None
            for k, v in patch.items():
                if k in self.PER_ACCOUNT and ov is not None:
                    ov[k] = v                                # параметр конкретного счёта → в его оверрайды
                elif k in self.PER_ACCOUNT or k in self.GLOBAL:
                    raw[k] = v                               # main-параметр (=defaults) или глобальный → top-level
            if "binance_network" in patch:
                if acct:
                    acct["network"] = patch["binance_network"]                        # сеть конкретного счёта
                else:
                    raw.setdefault("binance", {})["network"] = patch["binance_network"]  # main/defaults
            atomic_write_json(os.path.join(CONFIG_DIR, "config.json"), raw, indent=2, ensure_ascii=False)
            self._reload()
        self.log("settings updated", "info")
        return self.get_config()

    # ---------- авторизация UI ----------
    def auth_required(self):
        return bool(self.cfg.get("auth_enabled")) and bool(env_get("UI_PASSWORD"))

    def auth_status(self):
        return {"auth_enabled": self.auth_required()}

    def login(self, password):
        import hmac as _hmac
        import secrets as _secrets
        pw = env_get("UI_PASSWORD")
        if pw and password and _hmac.compare_digest(str(password), str(pw)):
            tok = _secrets.token_urlsafe(24)
            self._tokens.add(tok)
            return {"ok": True, "token": tok}
        return {"ok": False, "error": "wrong password"}

    def check_token(self, tok):
        return bool(tok) and tok in self._tokens

    def set_ui_auth(self, password, enabled):
        if password:
            write_env({"UI_PASSWORD": password})
        with self.lock:
            self._set_global("auth_enabled", bool(enabled))
        self.log("access settings updated", "info")
        return {"auth_enabled": self.auth_required()}

    def set_keys(self, api_key, api_secret, key_env="BINANCE"):
        p = key_env or "BINANCE"                 # ключи пишутся в префикс выбранного профиля
        write_env({f"{p}_API_KEY": api_key, f"{p}_API_SECRET": api_secret})
        self._reload()                           # перечитываем активный счёт (для прочих профилей — просто хранение ключей)
        self.log(f"Binance keys updated (profile {p})", "info")
        return {"has_keys": self.have_keys}

    def set_active_account(self, account_id, force=False):
        """Сменить активный счёт (бот начнёт торговать им). БЕЗОПАСНО: отказ, если бот
        запущен или на текущем счёте есть открытая позиция — иначе она осиротеет."""
        cur = self.cfg.get("active_account", "main")
        if account_id == cur:
            return {"ok": True, "active": cur}
        rec = next((a for a in (self.cfg.get("accounts") or []) if a.get("id") == account_id), None)
        if not rec:
            return {"error": "no such account"}
        k, s = binance_keys(rec.get("key_env", "BINANCE"))
        if not (k and s):
            return {"error": f"account «{rec.get('label') or account_id}» has no keys set (prefix {rec.get('key_env')})"}
        if self.running and not force:
            return {"error": "Stop the bot before switching accounts."}
        # позиции текущего счёта при переключении НЕ закрываем — оставляем «дышать»;
        # вернёшься на этот счёт → бот подхватит их (adopt), полный догон лида — «Синхронизировать»
        try:
            if self.bn.positions():
                self.log("⚠️ current account positions remain unmanaged until you switch back to it", "info")
        except Exception:
            pass
        self._stamp_active(force=True)                       # счёт, который покидаем, был активен до этого момента
        with self.lock:
            self._cfg_raw["active_account"] = account_id
            self._save_raw()
            self._reload()                                   # подхватит ключи/сеть/тип/состояние/оверрайды нового счёта
        self.log(f"active account → {rec.get('label') or account_id} ({rec.get('type', 'futures')}, {rec.get('key_env')})", "info")
        return {"ok": True, "active": account_id, "type": rec.get("type", "futures"), "has_keys": self.have_keys}


controller = Controller()
