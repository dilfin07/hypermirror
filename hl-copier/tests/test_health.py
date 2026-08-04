"""Юнит-тесты наблюдаемости («сервис деградировал, а сигнала нет»):

C-5 — health telegram в _services_health: тишина на рынке при пустой очереди = ok,
      down только когда реально не доставляем (очередь копится/распухла, фейлы при стейле).
C-3 — сторож: упавшим считается любой state вне ("ok","warn"), но "off" у сервисов,
      где это «не настроен конфигом» (binance/monitoring/telegram), — не авария.
S-9 — get_updates не глотает ошибки: ok=false поднимает исключение (иначе плохой токен
      неотличим от «нет апдейтов» и PANIC с телефона молча умирает).
"""
import os
import queue
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# сторож на импорте читает UI_PASSWORD из .env бота — подставляем свой, чтобы тест не лез в .env
os.environ.setdefault("HLC_PASSWORD", "test")
sys.path.insert(0, os.path.join(_ROOT, "watch"))

import watchdog
from server._status import StatusMixin


# ---------- C-5: telegram health ----------
class _Ctl(StatusMixin):
    """Минимальный носитель состояния для _services_health (без сети и потоков)."""

    def __init__(self, qsize=0, tg_ok_age=None, tg_fail_age=None, enabled=True):
        self.cfg = {"telegram": {"enabled": enabled, "chat_id": "42"}, "monitors": []}
        self._tg_token = "tok"
        self._tg_queue = queue.Queue()
        for _ in range(qsize):
            self._tg_queue.put(1)
        now = time.time()
        self._tg_ok_ts = (now - tg_ok_age) if tg_ok_age is not None else 0
        self._tg_fail = {"ts": now - tg_fail_age, "err": "x"} if tg_fail_age is not None else None
        # прочее состояние — чтобы _services_health не падал на остальных сервисах
        self._fill_stream = None
        self._copier_fs = None
        self._hl_ok_ts = 0
        self._bn_ok_ts = 0
        self._last_mon_event_ts = 0
        self.have_keys = False
        self.running = False
        self.live = False
        self.data_mode = "poll"


def _tg(**kw):
    return _Ctl(**kw)._services_health({})["telegram"]


def test_tg_quiet_market_empty_queue_is_ok():
    """Ключевой регресс 6 июля: ночь без сделок (last_ok 8ч) при пустой очереди — НЕ down."""
    assert _tg(qsize=0, tg_ok_age=8 * 3600)["state"] == "ok"


def test_tg_never_sent_empty_queue_is_ok():
    """Свежий процесс: ни одной отправки ещё не было (last_ok=None), слать нечего — ok."""
    assert _tg(qsize=0, tg_ok_age=None)["state"] == "ok"


def test_tg_fresh_ok_nonempty_queue_is_ok():
    """Сообщения в очереди, но отправка недавно проходила — рабочий бёрст, не отказ."""
    assert _tg(qsize=5, tg_ok_age=10)["state"] == "ok"


def test_tg_queue_backing_up_while_stale_is_down():
    """Реальный отказ: сообщения копятся И давно ничего не уходило."""
    assert _tg(qsize=3, tg_ok_age=700)["state"] == "down"


def test_tg_bloated_queue_is_down():
    assert _tg(qsize=201, tg_ok_age=10)["state"] == "down"


def test_tg_recent_fail_only_is_warn():
    """Разовый фейл при недавнем успехе — warn, не down."""
    assert _tg(qsize=0, tg_ok_age=30, tg_fail_age=10)["state"] == "warn"


def test_tg_recent_fail_and_stale_is_down():
    """Свежий фейл + давно нет успеха: не доставляем даже при пустой очереди
    (после 4 ретраев сообщение дропается — очередь может быть пуста при мёртвом канале)."""
    assert _tg(qsize=0, tg_ok_age=700, tg_fail_age=10)["state"] == "down"


def test_tg_response_fields_preserved():
    """Контракт для UI/MCP/сторожа: поля state/queue/last_ok_sec/last_fail на месте."""
    t = _tg(qsize=2, tg_ok_age=42, tg_fail_age=5)
    assert set(t) >= {"state", "queue", "last_ok_sec", "last_fail"}
    assert t["queue"] == 2 and t["last_ok_sec"] == 42 and t["last_fail"]["err"] == "x"


def test_tg_disabled_is_off():
    assert _tg(enabled=False)["state"] == "off"


# ---------- C-3: классификация «упавших» сервисов в стороже ----------
def test_watchdog_stopped_copier_counts_as_down():
    """Регресс: остановленный копир приходит как off/stopped — оба должны считаться аварией."""
    assert watchdog._svc_is_down("copier", "off")
    assert watchdog._svc_is_down("copier", "stopped")
    assert watchdog._svc_is_down("copier", "down")


def test_watchdog_ok_and_warn_are_not_down():
    for svc in ("copier", "telegram", "binance", "hyperliquid", "monitoring"):
        assert not watchdog._svc_is_down(svc, "ok")
        assert not watchdog._svc_is_down(svc, "warn")


def test_watchdog_off_by_config_is_not_down():
    """off у binance = «ключи не заданы», у monitoring = «нет адресов», у telegram =
    «выключен в конфиге» — осознанная настройка, не деградация (иначе ложный RED)."""
    assert not watchdog._svc_is_down("binance", "off")
    assert not watchdog._svc_is_down("monitoring", "off")
    assert not watchdog._svc_is_down("telegram", "off")


def test_watchdog_down_and_unknown_states_are_down():
    assert watchdog._svc_is_down("telegram", "down")
    assert watchdog._svc_is_down("hyperliquid", "down")
    assert watchdog._svc_is_down("binance", "down")
    assert watchdog._svc_is_down("copier", "degraded")   # неизвестный state — не глотать


# ---------- S-9: контракт get_updates ----------
def test_get_updates_raises_on_api_error():
    import urllib.request

    import copier.telegram as tgmod

    class _Resp:
        def __init__(self, body):
            self._b = body

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    orig = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda *a, **k: _Resp(b'{"ok": false, "description": "Unauthorized"}')
        try:
            tgmod.get_updates("bad-token")
            raise AssertionError("ok=false должен поднимать исключение, а не возвращать []")
        except RuntimeError:
            pass
        urllib.request.urlopen = lambda *a, **k: _Resp(b'{"ok": true, "result": [{"update_id": 7}]}')
        assert tgmod.get_updates("tok") == [{"update_id": 7}]
    finally:
        urllib.request.urlopen = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok {fn.__name__}")
    print(f"{len(fns)} passed")
