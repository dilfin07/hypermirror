"""M-1 — отклонённый ордер не должен «съедать» движение лида.

`_prev_tgt_pos` — baseline позиций цели: по нему движок решает, породил ли ордер лид
(тогда исполняем даже при auto_sync=off) или это правка расхождения (тогда откладываем
до ручной кнопки «Синхронизировать»).

Baseline двигался безусловно после любого торгового тика. Если биржа ордер отклонила
(-2019 маржа, -1111 точность, -4164 minNotional), движение лида всё равно считалось
отработанным — и на следующем тике тот же ордер выглядел уже «синхронизацией», которую
auto_sync=off откладывает навсегда. Для ЗАКРЫТИЯ это означало позицию, которую копир
больше никогда не попытается закрыть.

Инвариант: по символам с отклонёнными ордерами baseline остаётся прежним.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server._engine import advance_prev_tgt  # noqa: E402


def _moved(cur, prev, sym):
    """Тот же критерий, что в движке: лид сдвинулся по символу?"""
    p = prev.get(sym, 0.0)
    return abs(cur.get(sym, 0.0) - p) > max(1e-9, abs(p) * 0.001)


def test_успешный_тик__baseline_догоняет_цель():
    cur = {"ETHUSDT": -0.9, "BTCUSDT": 0.02}
    prev = {"ETHUSDT": -0.5, "BTCUSDT": 0.02}
    assert advance_prev_tgt(cur, prev, set()) == cur


def test_отклонённый_символ__baseline_не_двигается():
    cur = {"ETHUSDT": -0.9, "BTCUSDT": 0.02}
    prev = {"ETHUSDT": -0.5, "BTCUSDT": 0.02}
    new = advance_prev_tgt(cur, prev, {"ETHUSDT"})
    assert new["ETHUSDT"] == -0.5, "движение лида по ETH не отработано — baseline прежний"
    assert new["BTCUSDT"] == 0.02, "успешные символы догоняют цель"


def test_отклонение_повторяется_на_следующем_тике():
    """Ключевой инвариант M-1: после отказа moved остаётся True → ордер пройдёт гейт."""
    cur = {"ETHUSDT": -0.9}
    prev = {"ETHUSDT": -0.5}
    assert _moved(cur, prev, "ETHUSDT")

    after_reject = advance_prev_tgt(cur, prev, {"ETHUSDT"})
    assert _moved(cur, after_reject, "ETHUSDT"), "отклонённый ордер обязан повториться"

    after_ok = advance_prev_tgt(cur, prev, set())
    assert not _moved(cur, after_ok, "ETHUSDT"), "успешный ордер не должен исполниться дважды"


def test_отклонённое_закрытие_остаётся_к_исполнению():
    """Лид вышел (цель 0), наше закрытие отклонено — на следующем тике снова закрываем."""
    cur = {"ETHUSDT": 0.0}
    prev = {"ETHUSDT": -0.5}
    after = advance_prev_tgt(cur, prev, {"ETHUSDT"})
    assert after["ETHUSDT"] == -0.5
    assert _moved(cur, after, "ETHUSDT"), "закрытие нельзя терять — позиция осталась висеть"


def test_новый_символ_с_отказом_не_попадает_в_baseline():
    """Лид открыл монету, которой у нас в baseline не было, ордер отклонён.
    Если записать её в baseline, следующий тик сочтёт вход «уже отработанным»."""
    cur = {"SOLUSDT": 1.5}
    prev = {}
    after = advance_prev_tgt(cur, prev, {"SOLUSDT"})
    assert "SOLUSDT" not in after
    assert _moved(cur, after, "SOLUSDT")


def test_несколько_символов__страдает_только_отклонённый():
    cur = {"ETHUSDT": -0.9, "BTCUSDT": 0.03, "SOLUSDT": 2.0}
    prev = {"ETHUSDT": -0.5, "BTCUSDT": 0.02, "SOLUSDT": 1.0}
    after = advance_prev_tgt(cur, prev, {"BTCUSDT", "SOLUSDT"})
    assert after == {"ETHUSDT": -0.9, "BTCUSDT": 0.02, "SOLUSDT": 1.0}


def test_baseline_не_алиасит_cur_tgt():
    """advance_prev_tgt обязан вернуть КОПИЮ: иначе мутация cur_tgt задним числом
    поменяет baseline и «движение лида» исчезнет."""
    cur = {"ETHUSDT": -0.9}
    after = advance_prev_tgt(cur, {}, set())
    cur["ETHUSDT"] = -99.0
    assert after["ETHUSDT"] == -0.9
