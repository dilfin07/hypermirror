"""Источник текущих позиций для реконсиляции.

Движок берёт позиции из того же снимка account(), что уже запрашивается ради equity,
а не отдельным вызовом /fapi/v2/positionRisk: один момент времени вместо двух чтений,
и на один тяжёлый запрос меньше (positionRisk без фильтра по символу — сотни записей).

Историческая справка: 2026-07-06 на testnet наблюдался churn (копир открывался по кругу).
Виноват оказался НЕ копир и НЕ API, а второй бот (mrfade-стратегия) на тех же ключах —
он фейдил наши входы встречной позицией. На чистом стенде positionRisk и account()
согласованы (18 замеров из 18). Подробности — AUDIT.md, M-8.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.execution.binance import positions_from_account  # noqa: E402


def _acct(positions):
    return {"positions": positions}


def _pos(symbol, amt, side="BOTH"):
    return {"symbol": symbol, "positionAmt": amt, "positionSide": side}


def test_берёт_только_ненулевые():
    a = _acct([_pos("BTCUSDT", "-0.0157"), _pos("ETHUSDT", "0"), _pos("SOLUSDT", "0.000")])
    assert positions_from_account(a) == {("BTCUSDT", "BOTH"): -0.0157}


def test_ключ_учитывает_positionSide_для_hedge():
    a = _acct([_pos("BTCUSDT", "0.5", "LONG"), _pos("BTCUSDT", "-0.2", "SHORT")])
    assert positions_from_account(a) == {("BTCUSDT", "LONG"): 0.5, ("BTCUSDT", "SHORT"): -0.2}


def test_знак_сохраняется():
    a = _acct([_pos("BTCUSDT", "-1.5"), _pos("ETHUSDT", "2.25")])
    got = positions_from_account(a)
    assert got[("BTCUSDT", "BOTH")] < 0
    assert got[("ETHUSDT", "BOTH")] > 0


def test_пустой_или_битый_ответ_не_падает():
    assert positions_from_account({}) == {}
    assert positions_from_account(None) == {}
    assert positions_from_account({"positions": []}) == {}


def test_совместим_по_форме_с_positions():
    """Движок распаковывает ключ как (sym, positionSide) — форма должна совпадать
    с bn.positions(), иначе cur соберётся неверно."""
    a = _acct([_pos("BTCUSDT", "-0.01")])
    (sym, side), amt = next(iter(positions_from_account(a).items()))
    assert (sym, side, amt) == ("BTCUSDT", "BOTH", -0.01)
