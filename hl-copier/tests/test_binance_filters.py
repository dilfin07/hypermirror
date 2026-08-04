"""Регрессы на денежные примитивы Binance: округление лота и отбор торгуемых символов.

Оба бага найдены на живом прогоне копира по testnet (2026-07-06):
  * round_step(0.3, 0.1) отдавал 0.2 — терялся ЦЕЛЫЙ шаг;
  * symbol_filters отдавал символы в статусе SETTLING → бот слал заведомо провальные ордера.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.execution.binance import fmt_num, round_step, symbol_filters  # noqa: E402
from copier.execution.executor import _resolve_qty  # noqa: E402


# ---------- round_step: float-усечение ----------

def test_round_step_не_теряет_целый_шаг():
    """0.3/0.1 == 2.9999999999999996 → без эпсилона int() давал 2 (то есть 0.2)."""
    assert round_step(0.3, 0.1) == 0.3
    assert round_step(2.9, 0.1) == 2.9
    assert round_step(0.29, 0.01) == 0.29


def test_round_step_всё_ещё_округляет_вниз():
    """Эпсилон не должен превратить округление вниз в округление вверх."""
    assert round_step(0.35, 0.1) == 0.3
    assert round_step(0.39999, 0.1) == 0.3
    assert round_step(1.0999, 0.1) == 1.0


def test_round_step_точные_значения_не_меняются():
    assert round_step(0.007, 0.001) == 0.007
    assert round_step(0.648, 0.001) == 0.648
    assert round_step(1.1, 0.1) == 1.1


def test_round_step_ноль_и_вырожденный_шаг():
    assert round_step(0.05, 0.1) == 0.0        # меньше шага → ноль
    assert round_step(1.234, 0) == 1.234       # шаг не задан → как есть


def test_round_step_закрытие_не_оставляет_остаток():
    """Сценарий бага: закрываем 0.3 ETH шагом 0.001 — должно уйти всё."""
    qty = 0.3
    assert round_step(qty, 0.001) == 0.3
    assert round_step(qty, 0.1) == 0.3


# ---------- symbol_filters: только TRADING ----------

def _info(*pairs):
    return {"symbols": [
        {"symbol": sym, "status": st, "quantityPrecision": 3, "pricePrecision": 2,
         "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                     {"filterType": "NOTIONAL", "notional": "5"},
                     {"filterType": "PRICE_FILTER", "tickSize": "0.01"}]}
        for sym, st in pairs
    ]}


def test_symbol_filters_берёт_только_trading():
    f = symbol_filters(_info(("BTCUSDT", "TRADING"), ("LITUSDT", "SETTLING")))
    assert "BTCUSDT" in f
    assert "LITUSDT" not in f, "SETTLING-символ попал в filters → бот пошлёт по нему ордер"


def test_symbol_filters_отсекает_все_неторгуемые_статусы():
    f = symbol_filters(_info(
        ("A_USDT", "TRADING"),
        ("B_USDT", "SETTLING"),
        ("C_USDT", "PENDING_TRADING"),
        ("D_USDT", "CLOSE"),
        ("E_USDT", "BREAK"),
    ))
    assert set(f) == {"A_USDT"}


def test_symbol_filters_разбирает_поля():
    f = symbol_filters(_info(("BTCUSDT", "TRADING")))["BTCUSDT"]
    assert f["stepSize"] == 0.001
    assert f["minQty"] == 0.001
    assert f["minNotional"] == 5.0
    assert f["tickSize"] == 0.01


def test_symbol_filters_only_trading_можно_отключить():
    """Диагностическим утилитам может понадобиться полный список."""
    f = symbol_filters(_info(("BTCUSDT", "TRADING"), ("LITUSDT", "SETTLING")), only_trading=False)
    assert set(f) == {"BTCUSDT", "LITUSDT"}


def test_fmt_num_срезает_float_хвост():
    """Найдено на testnet (2026-07-17): SOL SELL валился с -1111 «Precision is over the maximum».
    Причина — 0.06+0.01=0.06999999999999999 уходил в тело ордера как есть."""
    assert fmt_num(0.06999999999999999) == "0.07"
    assert fmt_num(0.15) == "0.15"
    assert fmt_num(0.0) == "0"
    assert fmt_num("true") == "true"   # не-числа не трогаем
    assert fmt_num(3) == 3


def test_resolve_qty_roundup_без_float_хвоста():
    """Открытие суб-минимальной ноги: округление вниз даёт notional < minNotional,
    добавляем шаг — и результат ОБЯЗАН быть кратным шагу (без 0.0699…)."""
    filt = {"stepSize": 0.01, "minQty": 0.01, "minNotional": 5.0}
    qty, reason = _resolve_qty(-0.05, 75.17, filt, closing=False, opening=True, roundup=True)
    assert reason is None
    assert str(qty) == "0.07"          # чистое, не 0.06999999999999999
    assert qty * 75.17 >= 5.0          # подняли до minNotional
