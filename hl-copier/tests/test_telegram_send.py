"""Сообщение с битой HTML-разметкой не должно теряться.

Шлём с parse_mode=HTML — сводки монитора используют <b>/<code>. Но в текст алертов
попадает содержимое исключений: «<urlopen error [Errno 61] ...>», «<module>» из
трейсбека. Telegram видит незакрытый тег, отвечает 400 «can't parse entities» и не
доставляет НИЧЕГО.

Вдобавок urlopen на 400 бросает HTTPError, а тело ответа с причиной никто не читал —
в статусе бота оседало бесполезное «HTTP Error 400: Bad Request».

Теперь причину читаем, и при ошибке разметки повторяем как обычный текст: алерт без
форматирования лучше недоставленного алерта.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier import telegram  # noqa: E402


class _FakeTG(BaseHTTPRequestHandler):
    received = []          # список payload-ов, дошедших до "Telegram"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        payload = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        _FakeTG.received.append(payload)

        # настоящий Telegram: HTML с незакрытым тегом → 400 + описание в теле
        if payload.get("parse_mode") == "HTML" and "<urlopen" in payload.get("text", ""):
            body = json.dumps({"ok": False, "error_code": 400,
                               "description": "Bad Request: can't parse entities"}).encode()
            self.send_response(400)
        else:
            body = json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FakeTG)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address
    _FakeTG.received = []
    real = telegram.urllib.request.Request

    def _local(url, *a, **kw):
        return real(url.replace("https://api.telegram.org", f"http://{host}:{port}"), *a, **kw)

    monkeypatch.setattr(telegram.urllib.request, "Request", _local)
    return srv


def test_битая_разметка__повтор_без_parse_mode(monkeypatch):
    srv = _serve(monkeypatch)
    ok, info = telegram.send_message("TOK", "123", "❌ ордер: <urlopen error [Errno 61]>")
    srv.shutdown()

    assert ok is True, "алерт обязан дойти, пусть и без форматирования"
    assert len(_FakeTG.received) == 2, "первая попытка HTML, вторая — обычным текстом"
    assert _FakeTG.received[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in _FakeTG.received[1]
    assert _FakeTG.received[1]["text"] == "❌ ордер: <urlopen error [Errno 61]>"


def test_валидная_разметка__уходит_с_html_и_не_повторяется(monkeypatch):
    srv = _serve(monkeypatch)
    ok, _ = telegram.send_message("TOK", "123", "📊 <b>Сводка</b>")
    srv.shutdown()

    assert ok is True
    assert len(_FakeTG.received) == 1, "лишний повтор — лишнее сообщение у пользователя"
    assert _FakeTG.received[0]["parse_mode"] == "HTML"


def test_причина_ошибки_больше_не_теряется():
    """_post читает тело 4xx: раньше HTTPError давал «HTTP Error 400: Bad Request»."""
    assert telegram._is_parse_error({"description": "Bad Request: can't parse entities"})
    assert telegram._is_parse_error({"description": "unsupported start tag"})
    assert not telegram._is_parse_error({"description": "chat not found"})
    assert not telegram._is_parse_error({})


def test_нет_токена__не_шлём():
    assert telegram.send_message("", "123", "x")[0] is False
    assert telegram.send_message("TOK", "", "x")[0] is False


def test_сеть_упала__возвращаем_ok_false_а_не_исключение(monkeypatch):
    """Вызывающий ждёт кортеж (ok, info); исключение наружу сломало бы TG-воркер."""
    def _boom(*a, **kw):
        raise OSError("сеть недоступна")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", _boom)
    ok, info = telegram.send_message("TOK", "123", "x")
    assert ok is False
    assert "сеть недоступна" in str(info)
