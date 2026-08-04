"""Аналитика закрытых сделок: winrate, profit factor, max drawdown, разбивка по монете.

Всё — от биржевых закрытых позиций (realizedPnl/duration), без локального учёта.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.core.analytics import trade_analytics  # noqa: E402


def _c(symbol, pnl, dur=60, close_time=0):
    return {"symbol": symbol, "realizedPnl": pnl, "duration_min": dur, "close_time": close_time}


def test_пусто():
    a = trade_analytics([])
    assert a["trades"] == 0 and a["winrate"] is None and a["total_pnl"] == 0.0


def test_winrate_и_profit_factor():
    closed = [_c("ETHUSDT", 100), _c("ETHUSDT", -40), _c("BTCUSDT", 60), _c("BTCUSDT", -20)]
    a = trade_analytics(closed)
    assert a["trades"] == 4 and a["wins"] == 2 and a["losses"] == 2
    assert a["winrate"] == 0.5
    # profit factor = (100+60) / (40+20) = 160/60 ≈ 2.67
    assert abs(a["profit_factor"] - 2.67) < 0.01
    assert a["total_pnl"] == 100.0


def test_max_drawdown():
    # кривая PnL: +100 → +50 (−50 просадка) → +150 → +30 (−120 просадка) → пик 150
    closed = [_c("X", 100, close_time=1), _c("X", -50, close_time=2),
              _c("X", 100, close_time=3), _c("X", -120, close_time=4)]
    a = trade_analytics(closed)
    assert a["max_drawdown_usd"] == 120.0, "макс просадка кумулятивной кривой"


def test_profit_factor_без_убытков():
    a = trade_analytics([_c("X", 50), _c("X", 30)])
    assert a["profit_factor"] is None, "нет убытков → PF не делим на ноль"
    assert a["winrate"] == 1.0


def test_разбивка_по_монете():
    closed = [_c("ETHUSDT", 100), _c("ETHUSDT", -30), _c("BTCUSDT", 200)]
    a = trade_analytics(closed)
    by = {b["coin"]: b for b in a["by_coin"]}
    assert by["ETH"]["pnl"] == 70.0 and by["ETH"]["trades"] == 2 and by["ETH"]["wins"] == 1
    assert by["ETH"]["winrate"] == 0.5
    assert by["BTC"]["pnl"] == 200.0 and by["BTC"]["winrate"] == 1.0
    # сортировка: BTC (|200|) весомее ETH (|70|)
    assert a["by_coin"][0]["coin"] == "BTC"


def test_avg_holding_и_best_worst():
    a = trade_analytics([_c("X", 100, dur=120), _c("X", -40, dur=60)])
    assert a["avg_holding_min"] == 90
    assert a["best"] == 100.0 and a["worst"] == -40.0
