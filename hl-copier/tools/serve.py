"""Запуск веб-интерфейса (API + статика фронта).

    python3 tools/serve.py [--port 8787] [--host 127.0.0.1]
Открой http://127.0.0.1:8787  (или дев-фронт на :5173 при разработке).
ВНИМАНИЕ: кнопки close/panic/start --live двигают реальные деньги.
По умолчанию слушает только localhost; --host 0.0.0.0 откроет в LAN (только с авторизацией!).
"""
import _bootstrap  # noqa: F401
import sys

from server.api import serve


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    host = _arg("--host", "127.0.0.1")
    port = int(_arg("--port", "8787"))
    serve(host=host, port=port)


if __name__ == "__main__":
    main()
