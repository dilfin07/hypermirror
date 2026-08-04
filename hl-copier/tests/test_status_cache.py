"""get_status не должен блокировать HTTP на медленный _compute.

На testnet Binance отвечает ~2с/запрос, а _compute делает их несколько → ~7с.
Раньше get_status пересчитывал синхронно, как только кэш старше 2.5с, поэтому UI
(опрос /status каждые 5с) постоянно попадал на 7с-пересчёт и дашборд крутился.

Теперь отдаём последний кэш (его держит свежим копир-цикл), а синхронный _compute
делаем только если кэша нет совсем или он совсем протух (копир-цикл давно не тикал).
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server._status import StatusMixin  # noqa: E402


class _Stub(StatusMixin):
    def __init__(self, age=0.0, ready=True):
        self.lock = threading.RLock()
        self.status = {"ready": ready, "x": 1} if ready else {}
        self._status_ts = time.time() - age if ready else 0
        self.compute_calls = 0

    def _compute(self, do_apply=False):
        self.compute_calls += 1
        self.status = {"ready": True, "x": 2}
        self._status_ts = time.time()
        return dict(self.status)

    def log(self, *a, **k):
        pass


def test_свежий_кэш_не_пересчитывает():
    s = _Stub(age=3.0)          # старше max_age(2.5), но НЕ протух (< 20с)
    st = s.get_status()
    assert s.compute_calls == 0, "не блокируем HTTP на _compute при живом кэше"
    assert st["x"] == 1, "отдан кэш"


def test_совсем_протух_пересчитывает():
    s = _Stub(age=100.0)        # копир-цикл давно не тикал — обновить некому
    st = s.get_status()
    assert s.compute_calls == 1
    assert st["x"] == 2


def test_нет_кэша_пересчитывает():
    s = _Stub(ready=False)      # первый запрос, кэша ещё нет
    s.get_status()
    assert s.compute_calls == 1


def test_tick_age_отражает_возраст():
    s = _Stub(age=8.0)
    st = s.get_status()
    assert st["tick_age_sec"] >= 7, "UI видит, насколько данные свежие"
