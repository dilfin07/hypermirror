"""Классификация действий цели. Чистые функции (без I/O).

Два уровня:
  classify_fill        — по одному филлу (через startPosition): что именно сделал.
  classify_net_change  — по изменению NET-позиции между снимками (для копира).
"""
EPS = 1e-9


def classify_fill(fill):
    """Один филл -> dict с действием OPEN/INCREASE/REDUCE/CLOSE/FLIP."""
    before = float(fill["startPosition"])
    sz = float(fill["sz"])
    signed = sz if fill["side"] == "B" else -sz
    after = before + signed
    ref = after if abs(after) > EPS else before
    side = "SHORT" if ref < 0 else "LONG"
    if abs(before) < EPS:
        action = "OPEN"
    elif abs(after) < EPS:
        action = "CLOSE"
    elif (before > 0) != (after > 0):
        action = "FLIP"
    elif abs(after) > abs(before):
        action = "INCREASE"
    else:
        action = "REDUCE"
    pct = ((abs(after) - abs(before)) / abs(before) * 100) if abs(before) > EPS else 100.0
    px = float(fill["px"])
    return {
        "coin": fill["coin"], "action": action, "side": side,
        "before": before, "after": after, "pct": pct,
        "px": px, "sz": sz, "value": sz * px,
        "maker": not fill.get("crossed"),
        "closedPnl": fill.get("closedPnl"), "time": fill["time"],
    }


def classify_net_change(prev, cur, min_delta_pct):
    """prev/cur — снимок позиции (dict с 'size','lev','exposure_pct') или None.
    Возвращает list[(action, cur, prev)]."""
    evs = []
    if prev is None and cur is not None:
        return [("OPEN", cur, None)]
    if prev is not None and cur is None:
        return [("CLOSE", prev, None)]
    if prev is None and cur is None:
        return evs
    sp = 1 if prev["size"] > 0 else -1
    sc = 1 if cur["size"] > 0 else -1
    if sp != sc:
        return [("FLIP", cur, prev)]
    da = abs(cur["size"]) - abs(prev["size"])
    rel = abs(da) / abs(prev["size"]) * 100 if prev["size"] else 100
    if rel >= min_delta_pct:
        evs.append(("INCREASE" if da > 0 else "REDUCE", cur, prev))
    if cur["lev"] != prev["lev"]:
        evs.append(("LEVERAGE_CHANGE", cur, prev))
    return evs
