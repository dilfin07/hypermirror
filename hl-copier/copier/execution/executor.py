"""Реконсилятор: желаемые позиции (из core.plan) -> ордера на Binance.

Поддержаны оба режима аккаунта:
  • One-way  — build_orders        (net-позиция, positionSide=BOTH, reduceOnly)
  • Hedge    — build_orders_hedge  (нога LONG/SHORT, positionSide, без reduceOnly)
build_* — чистые функции (без сети). apply — отправляет план.
"""
import time

from .binance import to_symbol, round_step, round_price

EPS = 1e-12


def _favorable(side, mark, entry, tol_pct):
    """True, если входить СЕЙЧАС не хуже входа цели (с допуском tol_pct%).
    LONG — цена не выше входа цели; SHORT — не ниже. Нет entry/mark → не блокируем.
    Гасит «догон» при нашей задержке: не открываемся/не доливаем по уехавшей против нас цене."""
    if not entry or not mark:
        return True
    if side == "LONG":
        return mark <= entry * (1 + tol_pct / 100)
    return mark >= entry * (1 - tol_pct / 100)


def _resolve_qty(delta, mark, filt, closing, opening, roundup):
    """Размер ордера с учётом минимумов биржи. Возвращает (qty, skip_reason).
    qty<=0 + reason → пропустить (reason=None → молча).
    Логика под РЕКОНСИЛЯЦИЮ (идемпотентно сводим к цели):
      • полное закрытие — всегда (reduceOnly на бирже минимум не блокирует);
      • round-up: ОТКРЫТИЕ позиции с суб-минимальным размером поднимаем до minNotional
        (иначе мелкую позицию вообще не скопировать);
      • dead-band: прочие суб-минимальные правки НЕ дёргаем — иначе в реконсиляции
        возникает «дёрганье» (открыли по min → следующий тик срезал). Дельта копится
        в разнице цель↔наша и исполнится, когда перевалит минимум."""
    step = filt.get("stepSize", 0) or 0
    mn = filt.get("minNotional", 0) or 0
    mq = filt.get("minQty", 0) or 0
    qty = round_step(abs(delta), step)
    if closing:
        if qty <= EPS or qty < mq:
            return 0.0, ("qty < minQty/step" if abs(delta) > EPS else None)
        return qty, None
    if qty * mark < mn:
        if roundup and opening:
            q = round_step(mn / mark, step)
            if q * mark < mn:                 # round_step округлил вниз — добавим шаг
                # ВАЖНО: переокруглить к шагу. Иначе float-хвост (0.06+0.01=0.06999999999999999)
                # уходит в ордер как есть → Binance -1111 «Precision is over the maximum».
                q = round_step(q + (step or q), step)
            if q < mq or q <= EPS:
                return 0.0, "qty < minQty (round-up)"
            return q, None
        return 0.0, (f"dead-band: ${qty * mark:.0f} < min ${mn:.0f}" if abs(delta) > EPS else None)
    if qty <= EPS or qty < mq:
        return 0.0, ("qty < minQty/step" if abs(delta) > EPS else None)
    return qty, None


def build_orders(desired, mark_prices, filters, current_positions, fav=None, roundup=True):
    """ONE-WAY. current_positions: {symbol: signed qty}. fav={'on':bool,'tol':pct} — favorability-gate.
    roundup — поднимать суб-минимальное ОТКРЫТИЕ до minNotional (см. _resolve_qty)."""
    target, lev_for, entry_for, skipped = {}, {}, {}, []
    for coin, d in desired.items():
        sym = to_symbol(coin)
        if not sym or sym not in filters:
            skipped.append((coin, "symbol not on Binance")); continue
        mark = mark_prices.get(sym)
        if not mark:
            skipped.append((coin, f"no mark {sym}")); continue
        target[sym] = d["notional"] / mark
        lev_for[sym] = int(d["leverage"])
        entry_for[sym] = d.get("entry")

    orders, lev_sets = [], {}
    for sym in sorted(set(target) | set(current_positions)):
        cur, tgt = current_positions.get(sym, 0.0), target.get(sym, 0.0)
        delta = tgt - cur
        mark = mark_prices.get(sym)
        filt = filters.get(sym, {"stepSize": 0, "minQty": 0, "minNotional": 0})
        if not mark or abs(delta) <= EPS:
            continue
        closing = abs(tgt) < EPS
        opening = abs(cur) < EPS and abs(tgt) > EPS
        reducing_same = abs(cur) > EPS and abs(tgt) < abs(cur) and (cur > 0) == (tgt > 0)
        reduce_only = closing or reducing_same
        adding = abs(cur) > EPS and abs(tgt) > abs(cur) and (cur > 0) == (tgt > 0)
        # favorability-gate: при ОТКРЫТИИ/ДОЛИВЕ не входим по уехавшей против нас цене (выходы не трогаем)
        if fav and fav.get("on") and (opening or adding):
            side = "LONG" if tgt > 0 else "SHORT"
            if not _favorable(side, mark, entry_for.get(sym), fav.get("tol", 0.3)):
                skipped.append((sym, f"favorability: {mark:.6g} worse than lead entry {entry_for.get(sym) or 0:.6g}")); continue
        qty, reason = _resolve_qty(delta, mark, filt, closing, opening, roundup)
        if qty <= EPS:
            if reason:
                skipped.append((sym, reason))
            continue
        notional = qty * mark
        if abs(tgt) > abs(cur) and sym in lev_for:
            lev_sets[sym] = lev_for[sym]
        orders.append({"symbol": sym, "side": "BUY" if delta > 0 else "SELL", "qty": qty,
                       "notional": round(notional, 2), "reduce_only": reduce_only,
                       "position_side": "BOTH", "cur": cur, "target": tgt})
    return {"orders": orders, "leverage": list(lev_sets.items()), "skipped": skipped}


def build_orders_hedge(desired, mark_prices, filters, current_legs, managed_symbols, fav=None, roundup=True):
    """HEDGE. current_legs: {(symbol, positionSide): signed amt}. fav={'on':bool,'tol':pct} — favorability-gate.
    roundup — поднимать суб-минимальное ОТКРЫТИЕ ноги до minNotional (см. _resolve_qty).
    Ведём ногу в направлении цели; противоположную ногу управляемых монет сводим к 0."""
    target_legs, lev_for, entry_for, skipped = {}, {}, {}, []
    for coin, d in desired.items():
        sym = to_symbol(coin)
        if not sym or sym not in filters:
            skipped.append((coin, "symbol not on Binance")); continue
        mark = mark_prices.get(sym)
        if not mark:
            skipped.append((coin, f"no mark {sym}")); continue
        ps = d["side"]                                   # LONG | SHORT
        target_legs[(sym, ps)] = abs(d["notional"]) / mark
        lev_for[sym] = int(d["leverage"])
        entry_for[sym] = d.get("entry")

    keys = set(target_legs) | {k for k in current_legs if k[0] in managed_symbols}
    orders, lev_sets = [], {}
    for (sym, ps) in sorted(keys):
        mark = mark_prices.get(sym)
        filt = filters.get(sym, {"stepSize": 0, "minQty": 0, "minNotional": 0})
        if not mark:
            continue
        desired_q = target_legs.get((sym, ps), 0.0)
        cur_q = abs(current_legs.get((sym, ps), 0.0))
        delta = desired_q - cur_q
        if abs(delta) <= EPS:
            continue
        increasing = delta > 0
        closing = desired_q < EPS                    # сводим ногу к нулю
        opening = cur_q < EPS and desired_q > EPS
        # favorability-gate: открываем/доливаем ногу только если цена не хуже входа цели
        if fav and fav.get("on") and increasing:
            if not _favorable(ps, mark, entry_for.get(sym), fav.get("tol", 0.3)):
                skipped.append((f"{sym}/{ps}", f"favorability: {mark:.6g} worse than lead entry {entry_for.get(sym) or 0:.6g}")); continue
        qty, reason = _resolve_qty(delta, mark, filt, closing, opening, roundup)
        if qty <= EPS:
            if reason:
                skipped.append((f"{sym}/{ps}", reason))
            continue
        notional = qty * mark
        side = ("SELL" if increasing else "BUY") if ps == "SHORT" else ("BUY" if increasing else "SELL")
        if increasing and sym in lev_for:
            lev_sets[sym] = lev_for[sym]
        sgn = 1 if ps == "LONG" else -1
        orders.append({"symbol": sym, "side": side, "qty": qty, "notional": round(notional, 2),
                       "reduce_only": False, "position_side": ps,
                       "cur": sgn * cur_q, "target": sgn * desired_q})
    return {"orders": orders, "leverage": list(lev_sets.items()), "skipped": skipped}


def render(plan):
    lines = [f"   ⚙️  leverage {sym} → {lev}x" for sym, lev in plan["leverage"]]
    for o in plan["orders"]:
        tag = f" [{o['position_side']}]" if o.get("position_side") not in (None, "BOTH") else (
            " reduce-only" if o.get("reduce_only") else "")
        lines.append(f"   {o['side']:4} {o['symbol']:10} qty {o['qty']:<12g} ~${o['notional']:,.0f}"
                     f"  ({o['cur']:+.4g} → {o['target']:+.4g}){tag}")
    for sym, why in plan["skipped"]:
        lines.append(f"   ⏭️  {sym}: {why}")
    if not plan["orders"] and not plan["leverage"]:
        lines.append("   (positions already match — nothing to do)")
    return "\n".join(lines)


def _maker_first(client, o, execu):
    """Синхронный maker-first → taker-fallback для ОДНОГО ордера (Ф1 MVP, без трекера/WS).
    Ставит post-only (GTX) у лучшей цены, ждёт филл до maker_wait_sec, при неуспехе —
    отменяет, при необходимости переставляет (chase), затем добивает рынком остаток.
    Полное закрытие (target≈0) сюда не попадает — оно идёт тейкером (см. apply)."""
    sym, side = o["symbol"], o["side"]
    ro, ps = o.get("reduce_only", False), o.get("position_side")
    filt = (execu.get("filters") or {}).get(sym, {})
    tick, step = filt.get("tickSize", 0), filt.get("stepSize", 0)
    wait = float(execu.get("maker_wait_sec", 5))
    chases = int(execu.get("maker_max_chases", 1))
    fallback = bool(execu.get("maker_fallback_taker", True))
    log = execu.get("log") or (lambda *a, **k: None)
    qty = o["qty"]
    last = {"orderId": None}

    for attempt in range(chases + 1):
        if qty <= EPS:
            return last
        try:
            bt = client.book_ticker(sym)
        except Exception:
            break                                       # нет стакана — уходим в фолбэк
        px = bt["bid"] if side == "BUY" else bt["ask"]
        if not px or px <= 0:
            break
        if tick:
            px = round_price(px, tick, side, maker=True)  # пассивная сторона, не пересечь
        try:
            r = client.limit_order(sym, side, qty, px, post_only=True,
                                   reduce_only=ro, position_side=ps,
                                   client_order_id=execu.get("client_order_id"))
        except RuntimeError as e:
            if "-5022" in str(e):                       # пересекло бы стакан → переставить
                log(f"🪙 {sym} {side}: GTX rejected (would cross), re-pricing", "skip", tg=False)
                continue
            raise
        oid = r.get("orderId"); last = r
        log(f"🪙 {sym} {side} maker {qty:g} @ {px:g} (waiting {wait:g}s)", "trade", tg=False)
        deadline = time.time() + wait
        filled = False
        while time.time() < deadline:
            time.sleep(min(1.5, max(0.2, wait)))
            try:
                st = client.get_order(sym, order_id=oid)
            except Exception:
                continue
            status = st.get("status")
            if status == "FILLED":
                return r
            if status in ("CANCELED", "EXPIRED", "REJECTED"):
                filled = False
                break
        # окно вышло (или ордер ушёл) — отменить и пересчитать остаток
        try:
            client.cancel_order(sym, order_id=oid)
        except RuntimeError:
            pass                                        # мог исполниться между проверкой и отменой
        try:
            st = client.get_order(sym, order_id=oid)
            done = float(st.get("executedQty", 0) or 0)
            if st.get("status") == "FILLED" or done >= qty - EPS:
                return r
            qty = round_step(qty - done, step) if step else (qty - done)
        except Exception:
            pass
        if filled:
            return r

    # мейкером полностью не добрали → тейкер на остаток
    if fallback and qty > EPS:
        log(f"🪙 {sym} {side}: taker fallback for remainder {qty:g}", "trade", tg=False)
        return client.market_order(sym, side, qty, ro, ps)
    return last


def apply(client, plan, execu=None):
    """execu=None → тейкер (market_order, прежнее поведение). execu={'mode':'maker',...}
    → maker-first/taker-fallback для не-закрывающих ордеров (полное закрытие всегда тейкер)."""
    maker = bool(execu and execu.get("mode") == "maker")
    results = []
    for sym, lev in plan["leverage"]:
        try:
            client.set_leverage(sym, lev); results.append(("leverage", sym, lev, "ok"))
        except Exception as e:
            results.append(("leverage", sym, lev, f"ERR {e}"))
    for o in plan["orders"]:
        try:
            closing = abs(o.get("target", 0)) < EPS     # полное закрытие → тейкер (гарантия выхода)
            if maker and not closing:
                r = _maker_first(client, o, execu)
            else:
                r = client.market_order(o["symbol"], o["side"], o["qty"],
                                        o.get("reduce_only", False), o.get("position_side"))
            results.append(("order", o["symbol"], o["side"], (r or {}).get("orderId", "ok")))
        except Exception as e:
            results.append(("order", o["symbol"], o["side"], f"ERR {e}"))
    return results
