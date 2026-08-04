"""Разовое уведомление в Telegram, что сервис стартовал.

Дёргается из systemd (ExecStartPost) после запуска бота. Тихо выходит, если
Telegram не настроен. Текст можно переопределить первым аргументом.
"""
import _bootstrap  # noqa: F401
import socket
import sys

from copier import telegram
from copier.config import load_config
from copier.secrets import telegram_token


def main():
    cfg = load_config()
    tg = cfg.get("telegram", {}) or {}
    token, chat_id = telegram_token(), tg.get("chat_id")
    if not tg.get("enabled") or not token or not chat_id:
        return
    host = socket.gethostname()
    net = cfg.get("binance", {}).get("network", "?")
    msg = sys.argv[1] if len(sys.argv) > 1 else (
        f"🟢 <b>hl-copier запущен</b>\nхост: <code>{host}</code> · сеть: {net}\n"
        f"автозапуск (systemd) активен"
    )
    try:
        telegram.send_message(token, chat_id, msg)
    except Exception:
        pass


if __name__ == "__main__":
    main()
