"""Устойчивый WebSocket-источник Hyperliquid (push) с авто-реконнектом.

SDK hyperliquid (0.24) НЕ переподключается сам: WebsocketManager.run() вызывает
run_forever() ровно один раз, обработчиков on_close/on_error нет — при обрыве
поток менеджера тихо умирает навсегда, а подписки теряются (на этом и прогорали:
алерты замолкали до рестарта процесса).

Этот модуль оборачивает SDK и делает поток надёжным:
  • watchdog следит за живостью — поток менеджера жив И входят сообщения
    (сервер шлёт pong примерно раз в 50с, ловим в т.ч. half-open соединения);
  • при смерти пересоздаёт Info и заново оформляет ВСЕ подписки (с backoff);
  • on_reconnect() дёргается после каждого (пере)подключения — чтобы догнать
    то, что произошло за время обрыва (снимок isSnapshot мы проглатываем).
Требует hyperliquid SDK (.venv).
"""
import threading
import time

from .rest import MAINNET

_STALE_SEC = 90      # нет ни одного сообщения дольше — коннект считаем мёртвым (pong ~раз в 50с)
_WATCH_SEC = 5       # период проверки здоровья
_BACKOFF_MAX = 30    # потолок паузы между попытками реконнекта, сек
_SEEN_MAX = 5000     # ограничение памяти под дедуп tid


class FillStream:
    """Устойчивая подписка на userFills нескольких адресов (адреса можно добавлять налету).

    on_fill(addr, fill) — на каждый НОВЫЙ филл (снимок isSnapshot проглатывается).
    on_reconnect()      — после каждого успешного (пере)подключения (необязательно).
    Сам переподключается и пере-подписывается при любом обрыве.
    """

    def __init__(self, on_fill, base=MAINNET, log=None, on_reconnect=None):
        self.on_fill = on_fill
        self.base = base
        self.log = log or (lambda *a, **k: None)
        self.on_reconnect = on_reconnect
        self.subs = set()           # адреса подписки
        self._sids = {}             # addr -> subscription_id (для отписки)
        self.seen = set()           # tid филлов — дедуп между реконнектами/снимками
        self._info = None
        self._last_rx = 0.0
        self._lock = threading.Lock()
        self._started = False

    # ---- публичное API ----
    def add(self, addr):
        with self._lock:
            if addr in self.subs:
                return
            self.subs.add(addr)
            info = self._info
        if info is not None:                       # уже подключены — подписываем налету
            try:
                self._subscribe_one(info, addr)
            except Exception as e:
                self.log(f"WS subscribe {addr[:8]} failed: {e}", "error")

    def remove(self, addr):
        """Отписать адрес: убрать из subs (не переподпишется на реконнекте) + unsubscribe на живом коннекте."""
        with self._lock:
            match = next((a for a in self.subs if a.lower() == (addr or "").lower()), None)
            if match is None:
                return
            self.subs.discard(match)
            sid = self._sids.pop(match, None)
            info = self._info
        if info is not None and sid is not None:
            try:
                info.unsubscribe({"type": "userFills", "user": match}, sid)
            except Exception as e:
                self.log(f"WS unsubscribe {match[:8]} failed: {e}", "error")

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def connected(self):
        """Есть живой коннект (для статус-бара)."""
        return self._info is not None and self._alive(self._info)

    # ---- внутреннее ----
    def _make_cb(self, addr):
        def cb(msg):
            self._last_rx = time.time()
            data = (msg or {}).get("data", {}) or {}
            snap = data.get("isSnapshot", False)
            for fl in data.get("fills", []):
                tid = fl.get("tid")
                if tid in self.seen:
                    continue
                self.seen.add(tid)
                if snap:                           # снимок-история при подписке — не алертим
                    continue
                try:
                    self.on_fill(addr, fl)
                except Exception as e:
                    import time as _t, traceback
                    if _t.time() - getattr(self, "_onfill_err_ts", 0) > 30:   # троттл: не флудить лог на повторе
                        self._onfill_err_ts = _t.time()
                        self.log(f"WS on_fill crash {addr[:8]}: {type(e).__name__}: {e} | "
                                 f"{traceback.format_exc().strip().splitlines()[-1][:160]}", "error")
            if len(self.seen) > _SEEN_MAX:
                self.seen = set()
        return cb

    def _subscribe_one(self, info, addr):
        sid = info.subscribe({"type": "userFills", "user": addr}, self._make_cb(addr))
        with self._lock:
            self._sids[addr] = sid

    def _connect(self):
        from hyperliquid.info import Info
        info = Info(self.base, skip_ws=False)
        try:  # отметка свежести на ЛЮБОЕ входящее сообщение (включая pong) — детектор half-open
            orig = info.ws_manager.ws.on_message

            def wrapped(_ws, message, _orig=orig):
                self._last_rx = time.time()
                return _orig(_ws, message)

            info.ws_manager.ws.on_message = wrapped
        except Exception:
            pass
        self._last_rx = time.time()
        with self._lock:
            addrs = list(self.subs)
        for addr in addrs:
            self._subscribe_one(info, addr)
        return info

    def _alive(self, info):
        try:
            return info.ws_manager.is_alive() and (time.time() - self._last_rx) <= _STALE_SEC
        except Exception:
            return False

    def _run(self):
        backoff = 1
        while True:
            try:
                info = self._connect()
                with self._lock:
                    self._info = info
                self.log(f"WS connected · subscriptions {len(self.subs)}", "info")
                backoff = 1
                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception:
                        pass
                while self._alive(info):
                    time.sleep(_WATCH_SEC)
                self.log("WS dropped — reconnecting", "error")
            except Exception as e:
                self.log(f"WS error: {e}", "error")
            try:
                if self._info is not None:
                    self._info.ws_manager.stop()
            except Exception:
                pass
            with self._lock:
                self._info = None
            time.sleep(backoff)
            backoff = min(_BACKOFF_MAX, backoff * 2)


def stream_fills(addresses, on_fill, base=MAINNET, log=None, on_reconnect=None):
    """Устойчивая подписка на userFills адресов. Блокирует вызывающий поток (как и раньше).

    Внутри — FillStream с авто-реконнектом; on_fill(addr, fill) на каждый новый филл."""
    fs = FillStream(on_fill, base=base, log=log, on_reconnect=on_reconnect)
    for a in addresses:
        fs.add(a)
    fs.start()
    while True:
        time.sleep(3600)
