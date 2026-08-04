"""Сайзинг: масштаб экспозиции цели под наш эквити + diff-ордера. Чистые функции."""
from collections import defaultdict

from .positions import f, account_value, net_positions


def desired_mirror(targets, mids, my_equity, cfg):
    """Желаемые net-позиции (без учёта заморозки — это делает plan.compute_plan).
    Возвращает (notional{coin:$}, size{coin:coins}, notes[])."""
    whitelist = set(cfg.get("coin_whitelist") or [])
    skip_builder = cfg.get("skip_builder_dexs", True)
    lev_cap = f(cfg.get("leverage_cap"), 5)
    cap_coin = f(cfg.get("max_notional_per_coin_usd"), 1e12)
    total_w = sum(f(t.get("weight"), 0) for t in targets) or 1.0

    notional = defaultdict(float)
    notes = []
    for t in targets:
        tv = account_value(t["state"])
        if tv <= 0:
            continue
        sleeve = my_equity * (f(t.get("weight"), 0) / total_w)
        for coin, p in net_positions(t["state"]).items():
            if skip_builder and ":" in coin:
                continue
            if whitelist and coin not in whitelist:
                continue
            mark = mids.get(coin)
            if not mark:
                continue
            notional[coin] += p["szi"] * mark * (sleeve / tv)

    for coin, v in list(notional.items()):
        if abs(v) > cap_coin:
            notional[coin] = cap_coin if v > 0 else -cap_coin
            notes.append(f"{coin}: кэп ${cap_coin:.0f}/монета")
    # множитель размера: масштабирует ПРОПОРЦИЮ лида ПЕРЕД gross-кэпом. <=0 → 1.0 (не инвертируем).
    mult = float(cfg.get("size_multiplier", 1.0))
    if mult != 1.0 and mult > 0:
        for coin in notional:
            notional[coin] *= mult
        notes.append(f"множитель ×{mult:g}")
    # lev_cap <= 0 → БЕЗ кэпа: полный миррор экспозиции лида (риск как у него)
    gross = sum(abs(v) for v in notional.values())
    if lev_cap > 0 and gross > my_equity * lev_cap and gross > 0:
        scale = my_equity * lev_cap / gross
        for coin in notional:
            notional[coin] *= scale
        notes.append(f"кэп плеча {lev_cap}x: ужал x{scale:.2f}")

    size = {c: notional[c] / mids[c] for c in notional if mids.get(c)}
    return dict(notional), size, notes


def diff_orders(desired_size, my_state, mids, min_notional=10.0):
    """Ордера, чтобы свести мои позиции к desired_size.
    list[{coin, side, size, notional, reduce_only}]."""
    cur = {c: p["szi"] for c, p in net_positions(my_state).items()}
    orders = []
    for coin in sorted(set(desired_size) | set(cur)):
        want = desired_size.get(coin, 0.0)
        have = cur.get(coin, 0.0)
        delta = want - have
        mark = mids.get(coin)
        if not mark or abs(delta * mark) < min_notional:
            continue
        reduce_only = (have != 0) and (abs(want) < abs(have)) and ((want >= 0) == (have >= 0))
        orders.append({
            "coin": coin, "side": "buy" if delta > 0 else "sell",
            "size": round(abs(delta), 6), "notional": round(abs(delta) * mark, 2),
            "reduce_only": reduce_only,
        })
    return orders
