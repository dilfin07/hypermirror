"""Живучесть сторожа: C-2 (не терять алерт) и C-4 (не молчать, когда бот мёртв).

C-2. Дедуп строится на подписи (sig) прошлого прогона: шлём только на смену состояния.
Если подпись сохранить ДО подтверждения доставки, упавший /api/notify молча «съедает»
аварию: на следующем прогоне sig совпадёт с сохранённой, changed=False, сторож промолчит.
Тишина сторожа неотличима от «всё чисто». Значит подпись двигаем только при delivered=True.
tg_down_streak — наоборот, всегда: это гистерезис телеграма, к доставке отношения не имеет.

C-4. Единственным каналом сторожа был сам бот (/api/notify). Умер процесс — умер и
наблюдатель. Теперь есть прямой канал в Telegram; «бот не отвечает» уходит туда после
двух прогонов подряд (гистерезис, чтобы рестарт сервиса не рождал ложную тревогу).
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault("HLC_PASSWORD", "test")
sys.path.insert(0, os.path.join(_ROOT, "watch"))

import watchdog  # noqa: E402


class _FakeTG(BaseHTTPRequestHandler):
    sent = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or "{}")
        _FakeTG.sent.append(body.get("text", ""))
        b = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def _serve_fake_tg():
    srv = HTTPServer(("127.0.0.1", 0), _FakeTG)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_доставлено__подпись_двигается():
    s = watchdog._next_state(True, ["orph:ETH"], "RED", [], "GREEN", 0)
    assert s == {"sig": ["orph:ETH"], "level": "RED", "tg_down_streak": 0}


def test_не_доставлено__подпись_остаётся_прежней():
    """Ключевой инвариант C-2: следующий прогон снова увидит changed=True и повторит."""
    s = watchdog._next_state(False, ["orph:ETH"], "RED", [], "GREEN", 0)
    assert s["sig"] == []
    assert s["level"] == "GREEN"


def test_повтор_на_следующем_прогоне():
    """Сбой → состояние не сдвинулось → changed всё ещё True → шлём снова."""
    prev = watchdog._next_state(False, ["orph:ETH"], "RED", [], "GREEN", 0)
    changed = sorted(["orph:ETH"]) != sorted(prev["sig"])
    assert changed, "после неудачной отправки алерт обязан повториться"

    ok = watchdog._next_state(True, ["orph:ETH"], "RED", prev["sig"], prev["level"], 0)
    assert ok["sig"] == ["orph:ETH"]
    changed_again = sorted(["orph:ETH"]) != sorted(ok["sig"])
    assert not changed_again, "после успешной отправки дубль слать нельзя"


def test_streak_сохраняется_даже_при_сбое_доставки():
    """Гистерезис telegram-down не должен сбрасываться из-за неудачного notify."""
    s = watchdog._next_state(False, ["down:telegram"], "RED", [], "GREEN", 3)
    assert s["tg_down_streak"] == 3


def test_нечего_слать__состояние_фиксируется():
    """GREEN→GREEN: пуша не было, delivered=True — подпись сохраняем как есть."""
    s = watchdog._next_state(True, [], "GREEN", [], "GREEN", 0)
    assert s == {"sig": [], "level": "GREEN", "tg_down_streak": 0}


def test_решено_не_теряется_при_сбое():
    """RED→GREEN с упавшим ✅: prev_level остаётся RED, значит «Решено» уйдёт позже."""
    s = watchdog._next_state(False, [], "GREEN", ["orph:ETH"], "RED", 0)
    assert s["level"] == "RED"
    assert s["sig"] == ["orph:ETH"]


# ---------- C-4: мёртвый бот ----------
def _run_watchdog_against_dead_bot(tmp_path, monkeypatch, srv):
    """Бота нет (порт 1 никто не слушает) — сторож обязан идти в TG напрямую."""
    host, port = srv.server_address
    monkeypatch.setattr(watchdog, "BASE", "http://127.0.0.1:1")
    monkeypatch.setattr(watchdog, "TG_API", f"http://{host}:{port}")
    monkeypatch.setattr(watchdog, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HLC_TG_TOKEN", "FAKE")
    monkeypatch.setenv("HLC_TG_CHAT", "123")
    monkeypatch.setattr(watchdog, "PASSWORD", "")


def test_мёртвый_бот__гистерезис_молчит_на_первом_прогоне(tmp_path, monkeypatch):
    srv = _serve_fake_tg()
    _FakeTG.sent = []
    _run_watchdog_against_dead_bot(tmp_path, monkeypatch, srv)
    watchdog.main()
    assert _FakeTG.sent == [], "один пропущенный опрос — ещё не авария (рестарт сервиса)"
    srv.shutdown()


def test_мёртвый_бот__на_втором_прогоне_зовёт_напрямую(tmp_path, monkeypatch):
    srv = _serve_fake_tg()
    _FakeTG.sent = []
    _run_watchdog_against_dead_bot(tmp_path, monkeypatch, srv)
    watchdog.main()
    watchdog.main()
    assert len(_FakeTG.sent) == 1
    assert "БОТ НЕ ОТВЕЧАЕТ" in _FakeTG.sent[0]

    watchdog.main()   # всё ещё мёртв, но уже сообщили
    assert len(_FakeTG.sent) == 1, "дубль алерта о мёртвом боте недопустим"
    srv.shutdown()


def test_прямой_канал_без_токена_не_падает(tmp_path, monkeypatch):
    monkeypatch.setenv("HLC_TG_TOKEN", "")
    monkeypatch.setenv("HLC_TG_CHAT", "")
    monkeypatch.setattr(watchdog, "_bot_env", lambda k: "")
    monkeypatch.setattr(watchdog, "_bot_chat_id", lambda: "")
    assert watchdog._direct_tg("что-нибудь") is False
