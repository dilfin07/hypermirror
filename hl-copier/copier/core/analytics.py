"""Аналитика по закрытым сделкам — risk-adjusted метрики + разбивка по монете.

Всё считается ОТ БИРЖИ: вход — список закрытых позиций, реконструированных из
биржевых userTrades (realizedPnl, длительность, сторона). Никакого локального
учёта бота — чтобы метрики не показывали прибыль по «зомби-сделке», которой на
бирже не было. Чистая функция без состояния → тестируется изолированно.
"""
import math


def _coin(symbol):
    s = (symbol or "").upper()
    for suf in ("USDT", "USDC", "BUSD", "FDUSD"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def trade_analytics(closed):
    """closed: [{symbol, realizedPnl, duration_min, close_time, ...}] (из get_position_history).
    Возвращает агрегаты для карточки «качество копирования» и donut по монетам.

    Метрики:
    - winrate: доля прибыльных сделок;
    - profit_factor: суммарная прибыль / суммарный убыток (>1 — система в плюсе);
    - max_drawdown_usd: максимальная просадка кумулятивного PnL (peak→trough);
    - sharpe: mean(PnL сделки) / std(PnL сделки) — риск-скорректированность (по сделкам);
    - avg_holding_min, avg_pnl, best/worst, total_pnl;
    - by_coin: разбивка PnL/винрейт по монете (для donut и таблицы).
    """
    pnls = [float(c.get("realizedPnl") or 0) for c in closed]
    n = len(pnls)
    if n == 0:
        return {"trades": 0, "winrate": None, "profit_factor": None, "total_pnl": 0.0,
                "max_drawdown_usd": 0.0, "sharpe": None, "avg_holding_min": None,
                "avg_pnl": None, "best": None, "worst": None, "wins": 0, "losses": 0,
                "by_coin": []}

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)   # положительное число
    total = sum(pnls)

    # profit factor: прибыль / убыток. Нет убытков → None (не делим на ноль; «идеально»)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 1e-9 else None

    # max drawdown: по кумулятивной кривой PnL в хронологическом порядке
    chron = sorted(closed, key=lambda c: c.get("close_time") or 0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for c in chron:
        equity += float(c.get("realizedPnl") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # sharpe по сделкам: mean/std (безразмерный, «стабильность PnL от сделки к сделке»)
    mean = total / n
    if n > 1:
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        sd = math.sqrt(var)
        sharpe = round(mean / sd, 2) if sd > 1e-9 else None
    else:
        sharpe = None

    holds = [float(c.get("duration_min") or 0) for c in closed if c.get("duration_min") is not None]
    avg_hold = round(sum(holds) / len(holds)) if holds else None

    # разбивка по монете
    by = {}
    for c in closed:
        coin = _coin(c.get("symbol"))
        b = by.setdefault(coin, {"coin": coin, "pnl": 0.0, "trades": 0, "wins": 0})
        p = float(c.get("realizedPnl") or 0)
        b["pnl"] += p
        b["trades"] += 1
        if p > 0:
            b["wins"] += 1
    by_coin = []
    for b in by.values():
        b["pnl"] = round(b["pnl"], 2)
        b["winrate"] = round(b["wins"] / b["trades"], 3) if b["trades"] else None
        by_coin.append(b)
    by_coin.sort(key=lambda x: -abs(x["pnl"]))   # самые весомые монеты вперёд

    return {
        "trades": n, "wins": wins, "losses": losses,
        "winrate": round(wins / n, 3),
        "profit_factor": profit_factor,
        "total_pnl": round(total, 2),
        "max_drawdown_usd": round(max_dd, 2),
        "sharpe": sharpe,
        "avg_holding_min": avg_hold,
        "avg_pnl": round(mean, 2),
        "best": round(max(pnls), 2),
        "worst": round(min(pnls), 2),
        "by_coin": by_coin,
    }
