"""План копирования: плечо (fixed/mirror) + заморозка плюсовых на старте.

compute_plan мутирует copy_state (заморозка), возвращает желаемые позиции с плечом.
"""
from collections import defaultdict

from .positions import f, account_value, net_positions, price_move_pct


def resolve_leverage(target_lev, cfg):
    if cfg.get("leverage_mode") == "fixed":
        return float(cfg.get("fixed_leverage", 3))
    return min(f(target_lev), float(cfg.get("mirror_max_leverage", 10)))


def compute_plan(targets_state, mids, my_equity, cfg, copy_state):
    """targets_state: [{address,label,weight,state}].
    Возвращает (desired{coin:{...}}, frozen_report[], notes[])."""
    whitelist = set(cfg.get("coin_whitelist") or [])
    skip_builder = cfg.get("skip_builder_dexs", True)
    lev_cap = float(cfg.get("leverage_cap", 5))
    cap_coin = float(cfg.get("max_notional_per_coin_usd", 1e12))
    skip_mode = cfg.get("start_skip_open", "profitable")
    skip_pct = float(cfg.get("start_skip_profit_pct", 5))
    total_w = sum(f(t.get("weight", 0)) for t in targets_state) or 1.0

    notional = defaultdict(float)
    lev_for, contributors = {}, defaultdict(list)
    entry_acc, entry_wsum = defaultdict(float), defaultdict(float)  # взвешенный вход цели (для favorability-gate)
    frozen_report, notes = [], []

    for t in targets_state:
        addr, st = t["address"], t["state"]
        # база = ПОЛНЫЙ пул USDC цели = max(перп-эквити, спот-USDC). НЕ сумма: спот-USDC
        # backs перп → это одни деньги в двух видах, сумма = двойной счёт (раздувало капитал
        # цели вдвое). max = общий баланс (подушка учтена), плечо = notional/max совпадает с
        # Hyperdash. Пропорция от ОБЩЕГО баланса цели, а не от одного перп-счёта.
        tv = max(account_value(st), f(t.get("spot_usd", 0.0)))
        copy_state.setdefault(addr, {"baseline_done": False, "frozen": {}})
        tstate = copy_state[addr]
        positions = net_positions(st)

        if not tstate["baseline_done"]:
            for coin, p in positions.items():
                if skip_builder and ":" in coin:
                    continue
                sgn = 1 if p["szi"] > 0 else -1
                mark = mids.get(coin) or p["entryPx"]
                mv = price_move_pct(sgn, p["entryPx"], mark)
                if skip_mode == "all" or (skip_mode == "profitable" and mv >= skip_pct):
                    tstate["frozen"][coin] = {"reason": "open@start", "move_pct": round(mv, 1)}
            tstate["baseline_done"] = True

        for coin in list(tstate["frozen"].keys()):
            if coin not in positions:
                del tstate["frozen"][coin]
                notes.append(f"{t['label']}: {coin} unfrozen (lead closed it) — new entries are copied")

        if tv <= 0:
            continue
        sleeve = my_equity * (f(t.get("weight", 0)) / total_w)
        for coin, p in positions.items():
            if skip_builder and ":" in coin:
                continue
            if whitelist and coin not in whitelist:
                continue
            if coin in tstate["frozen"]:
                frozen_report.append((t["label"], coin, p, tstate["frozen"][coin]))
                continue
            mark = mids.get(coin)
            if not mark:
                continue
            contrib = p["szi"] * mark * (sleeve / tv)
            notional[coin] += contrib
            lev_for[coin] = max(lev_for.get(coin, 0), p["lev"])
            entry_acc[coin] += p["entryPx"] * abs(contrib)
            entry_wsum[coin] += abs(contrib)
            contributors[coin].append(t["label"])

    for coin, v in list(notional.items()):
        if abs(v) > cap_coin:
            notional[coin] = cap_coin if v > 0 else -cap_coin
            notes.append(f"{coin}: cap ${cap_coin:.0f}/coin")
    # множитель размера: масштабирует ПРОПОРЦИЮ лида ПЕРЕД gross-кэпом и маржин-буфером.
    # <=0 трактуем как 1.0 (не обнуляем/не инвертируем направление). cap остаётся потолком.
    mult = float(cfg.get("size_multiplier", 1.0))
    if mult != 1.0 and mult > 0:
        for c in notional:
            notional[c] *= mult
        notes.append(f"multiplier ×{mult:g}")
    # leverage_cap <= 0 → БЕЗ кэпа: полный миррор экспозиции лида (риск как у него).
    # >0 → потолок своей суммарной экспозиции (защита малого счёта от плеча лида).
    gross = sum(abs(v) for v in notional.values())
    if lev_cap > 0 and gross > my_equity * lev_cap and gross > 0:
        scale = my_equity * lev_cap / gross
        for c in notional:
            notional[c] *= scale
        notes.append(f"leverage cap {lev_cap}x: scaled x{scale:.2f}")

    desired = {}
    for coin, n in notional.items():
        if not mids.get(coin):
            continue
        desired[coin] = {
            "side": "LONG" if n > 0 else "SHORT",
            "notional": n, "size": n / mids[coin],
            "leverage": resolve_leverage(lev_for.get(coin), cfg),
            "target_leverage": lev_for.get(coin),
            "entry": (entry_acc[coin] / entry_wsum[coin]) if entry_wsum.get(coin) else None,
            "from": contributors[coin],
        }

    # маржинальный буфер: суммарная НАЧАЛЬНАЯ маржа не должна съедать весь счёт —
    # оставляем запас под комиссию/проскальзывание. Иначе, когда desired требует
    # ~100% equity (напр. exposure цели ≈ плечу), биржа отклоняет открытие
    # (-2019 Margin insufficient). Ужимаем desired, чтобы маржа ≤ equity*(1-buf).
    buf = min(max(f(cfg.get("margin_buffer_pct", 0.10)), 0.0), 0.9)
    req_margin = sum(abs(d["notional"]) / d["leverage"] for d in desired.values() if d.get("leverage"))
    cap_margin = my_equity * (1 - buf)
    if req_margin > cap_margin > 0:
        k = cap_margin / req_margin
        for d in desired.values():
            d["notional"] *= k
            d["size"] *= k
        notes.append(f"margin buffer {int(buf * 100)}%: scaled x{k:.2f}")
    return desired, frozen_report, notes
