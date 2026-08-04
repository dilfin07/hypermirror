"""Пост-старт хук для systemd: дождаться API, запустить копир (live) и уведомить в Telegram.

Делает бота на Pi самодостаточным при автозапуске: после загрузки сам начинает
копирование в боевом режиме (как было на Mac) и шлёт сообщение, что сервис поднялся.
Вызывается из ExecStartPost. Тихо переживает любые сбои (не валит сервис).
"""
import _bootstrap  # noqa: F401
import json
import socket
import time
import urllib.request

from copier import telegram
from copier.config import load_config
from copier.secrets import get as secret_get, telegram_token

PORT = 8787
BASE = f"http://127.0.0.1:{PORT}"


def _get(path):
    return urllib.request.urlopen(BASE + path, timeout=5).read()


def _post(path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=10).read()


def main():
    cfg = load_config()
    mode = cfg.get("data_mode", "ws")

    up = False
    for _ in range(30):                      # ждём подъёма API до ~30с
        try:
            _get("/api/auth_status"); up = True; break   # без авторизации (status даёт 401 при auth)
        except Exception:
            time.sleep(1)

    # если включена авторизация — логинимся, иначе /api/start вернёт 401
    token = None
    if cfg.get("auth_enabled") and secret_get("UI_PASSWORD"):
        try:
            r = json.loads(_post("/api/login", {"password": secret_get("UI_PASSWORD")}))
            token = r.get("token")
        except Exception:
            pass

    started = False
    if up:
        try:
            _post("/api/start", {"live": True, "mode": mode}, token=token); started = True
        except Exception:
            pass

    tg = cfg.get("telegram", {}) or {}
    token, chat = telegram_token(), tg.get("chat_id")
    if tg.get("enabled") and token and chat:
        host = socket.gethostname()
        net = (cfg.get("binance") or {}).get("network", "?")
        state = ("копирование LIVE запущено ✅" if started else
                 ("API поднят, старт копира не удался ⚠️" if up else "API не ответил ⚠️"))
        msg = (f"🟢 <b>hl-copier запущен</b>\n"
               f"хост: <code>{host}</code> · сеть: {net} · режим: {mode}\n{state}\n"
               f"автозапуск systemd активен")
        try:
            telegram.send_message(token, chat, msg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
