"""Глубокое логирование: ротация, эффективное чтение хвоста, перехват исключений.

- Ротация: log.jsonl не растёт бесконечно (был 45 МБ без ротации) — по размеру → .1/.2/.3.
- Запись через один handle (не open на каждую строку — ресурс SD-карты на Pi).
- Чтение хвоста при старте: только последние ~512 КБ, а не весь файл в память.
- excepthook: любое НЕОБРАБОТАННОЕ исключение (в потоке/главном) уходит в лог с
  трейсбеком, а не в тишину stderr. «Отследить любую ошибку».
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import controller as ctrl_mod  # noqa: E402
from server.controller import Controller  # noqa: E402


def _writer(tmp_path, monkeypatch, max_bytes=500):
    monkeypatch.setattr(ctrl_mod, "runtime_path", lambda name: str(tmp_path / name))

    class Stub:
        LOG_MAX_BYTES = max_bytes
        LOG_KEEP = 3
        _log_write = Controller._log_write
        _rotate_log = Controller._rotate_log

    s = Stub()
    s._log_fh = None
    s._log_bytes = 0
    return s


def test_ротация_по_размеру(tmp_path, monkeypatch):
    s = _writer(tmp_path, monkeypatch, max_bytes=500)
    for i in range(200):
        s._log_write({"ts": "t", "level": "info", "msg": "x" * 40})
    base = tmp_path / "log.jsonl"
    assert base.exists(), "активный файл на месте"
    assert (tmp_path / "log.jsonl.1").exists(), "ротация создала поколение .1"
    assert base.stat().st_size < s.LOG_MAX_BYTES, "активный файл усечён после ротации"


def test_ротация_не_копит_больше_KEEP(tmp_path, monkeypatch):
    s = _writer(tmp_path, monkeypatch, max_bytes=300)
    for i in range(600):
        s._log_write({"ts": "t", "level": "info", "msg": "y" * 40})
    gens = [p.name for p in tmp_path.iterdir() if p.name.startswith("log.jsonl")]
    # активный + не больше LOG_KEEP поколений
    assert len(gens) <= s.LOG_KEEP + 1, f"поколений не больше {s.LOG_KEEP}+1: {gens}"
    assert not (tmp_path / "log.jsonl.4").exists(), "старше .3 не держим"


def test_один_handle_переживает_много_записей(tmp_path, monkeypatch):
    s = _writer(tmp_path, monkeypatch, max_bytes=10_000_000)
    for i in range(50):
        s._log_write({"ts": "t", "level": "info", "msg": str(i)})
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    assert len(lines) == 50
    assert json.loads(lines[-1])["msg"] == "49"


def test_load_logs_читает_только_хвост(tmp_path, monkeypatch):
    p = tmp_path / "log.jsonl"
    p.write_text("\n".join(json.dumps({"ts": "t", "level": "info", "msg": str(i)})
                           for i in range(5000)) + "\n", encoding="utf-8")
    monkeypatch.setattr(ctrl_mod, "runtime_path", lambda name: str(tmp_path / name))

    class Stub:
        _load_logs = Controller._load_logs

    s = Stub()
    s.logs = []
    s._load_logs()
    assert len(s.logs) == 300, "берём последние 300 строк"
    assert s.logs[-1]["msg"] == "4999", "и это именно ХВОСТ, а не начало"


def test_load_logs_битые_строки_не_валят(tmp_path, monkeypatch):
    p = tmp_path / "log.jsonl"
    p.write_text('{"ts":"t","level":"info","msg":"ok"}\nне-json-мусор\n', encoding="utf-8")
    monkeypatch.setattr(ctrl_mod, "runtime_path", lambda name: str(tmp_path / name))

    class Stub:
        _load_logs = Controller._load_logs

    s = Stub()
    s.logs = []
    s._load_logs()  # не должно бросить
    assert any(e.get("msg") == "ok" for e in s.logs)


def test_excepthook_ловит_исключение_потока():
    captured = []

    class Stub:
        _install_excepthooks = Controller._install_excepthooks

        def log(self, msg, level="info", tg=True):
            captured.append((level, msg))

    prev = threading.excepthook
    try:
        s = Stub()
        s._install_excepthooks()

        def boom():
            raise RuntimeError("бум-в-потоке")

        t = threading.Thread(target=boom)
        t.start()
        t.join()

        errs = [m for lvl, m in captured if lvl == "error"]
        assert any("бум-в-потоке" in m for m in errs), "исключение потока попало в лог"
        assert any("RuntimeError" in m and "Traceback" in m for m in errs), "с трейсбеком"
    finally:
        threading.excepthook = prev


def test_excepthook_игнорирует_systemexit():
    captured = []

    class Stub:
        _install_excepthooks = Controller._install_excepthooks

        def log(self, msg, level="info", tg=True):
            captured.append((level, msg))

    prev = threading.excepthook
    try:
        s = Stub()
        s._install_excepthooks()
        t = threading.Thread(target=lambda: sys.exit(0))
        t.start()
        t.join()
        assert not captured, "SystemExit — не ошибка, в лог не шлём"
    finally:
        threading.excepthook = prev
