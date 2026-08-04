"""Разбор позиций/эквити из clearinghouseState. Чистые функции."""


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def account_value(ch_state):
    return f((ch_state or {}).get("marginSummary", {}).get("accountValue"))


STABLES = ("USDC", "USDT")


def spot_capital_usd(spot_state, coins=STABLES):
    """Весь стейбл-баланс спота в USD (USDC/USDT `total`, включая `hold`).

    Это ПОЛНЫЙ пул USDC цели в спот-леджере. Идёт в базу пропорции как
    `max(перп-эквити, spot_capital_usd)` — НЕ в сумму: спот-USDC у HL-трейдеров и есть
    перп-залог (одни деньги в двух видах; hold-спот == totalMarginUsed перпа), поэтому
    сумма = двойной счёт. max = общий баланс цели (подушка учтена), и плечо
    notional/max совпадает с Hyperdash (у него спот-холдинги = $0, весь USDC = капитал).
    """
    usd = 0.0
    for b in (spot_state or {}).get("balances", []):
        if b.get("coin") in coins:
            usd += f(b.get("total"))
    return usd


def net_positions(ch_state):
    """{coin: {szi, entryPx, lev, uPnl, posVal}}."""
    out = {}
    for ap in (ch_state or {}).get("assetPositions", []):
        p = ap.get("position", {})
        coin = p.get("coin")
        if not coin:
            continue
        out[coin] = {
            "szi": f(p.get("szi")),
            "entryPx": f(p.get("entryPx")),
            "lev": f(p.get("leverage", {}).get("value")),
            "uPnl": f(p.get("unrealizedPnl")),
            "posVal": f(p.get("positionValue")),
        }
    return out


def price_move_pct(side_sign, entry, mark):
    """% движения цены В ПОЛЬЗУ позиции от входа (насколько 'убежала' в плюс)."""
    if not entry:
        return 0.0
    if side_sign > 0:                       # long
        return (mark / entry - 1) * 100
    return (1 - mark / entry) * 100         # short
