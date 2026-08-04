"""Наблюдение за филлами цели вживую (read-only).

REST-поллинг (по умолчанию, stdlib) или WebSocket push (--ws, нужен .venv/SDK).
Печатает каждое действие: ОТКРЫЛ/ДОЛИВ/СОКРАТИЛ/ЗАКРЫЛ/РАЗВОРОТ, «было→стало», %.

    python3 tools/watch_fills.py <addr> [<addr> ...] [--poll 5] [--coin BTC]
    .venv/bin/python tools/watch_fills.py <addr> --ws        # мгновенный push
"""
import _bootstrap  # noqa: F401
import sys
import time

from copier.hl.rest import HLInfo, MAINNET
from copier.core.events import classify_fill
from copier.core.format import fmt_usd, fmt_qty, hhmmss

ACT = {"OPEN": ("🟢", "ОТКРЫЛ"), "INCREASE": ("➕", "ДОЛИВ"), "REDUCE": ("➖", "СОКРАТИЛ"),
       "CLOSE": ("⚪", "ЗАКРЫЛ ПОЛНОСТЬЮ"), "FLIP": ("🔄", "РАЗВОРОТ")}


def render(addr, fill):
    e = classify_fill(fill)
    icon, label = ACT.get(e["action"], ("•", e["action"]))
    dot = "🔴" if e["side"] == "SHORT" else "🟢"
    cp = e["closedPnl"]
    cps = ""
    if cp not in (None, "0.0", "0") and e["action"] in ("REDUCE", "CLOSE", "FLIP"):
        cps = f"  PnL {float(cp):+.2f}"
    return (f"{icon} {hhmmss(e['time'])}  {addr[:10]}  {dot} {e['coin']}  {e['side']} · {label}\n"
            f"     кол-во: {fmt_qty(e['before'])} → {fmt_qty(e['after'])}  ({e['pct']:+.2f}%)\n"
            f"     объём: {fmt_usd(e['value'])} @ ${e['px']:,.4g}  · {'maker' if e['maker'] else 'taker'}{cps}")


def main():
    poll, coin_filter, use_ws = 5, None, False
    argv, args, i = sys.argv[1:], [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--poll":
            poll = int(argv[i + 1]); i += 2; continue
        if a == "--coin":
            coin_filter = argv[i + 1].upper(); i += 2; continue
        if a == "--ws":
            use_ws = True; i += 1; continue
        if a.startswith("--"):
            i += 1; continue
        args.append(a); i += 1
    if not args:
        print("usage: watch_fills.py <addr> [<addr> ...] [--poll N] [--coin BTC] [--ws]")
        return

    def emit(addr, fill):
        if coin_filter and fill["coin"].upper() != coin_filter:
            return
        print(render(addr, fill))

    if use_ws:
        from copier.hl.ws import stream_fills
        print(f"👀 WebSocket: слежу за {len(args)} адресами (push). Ctrl-C для выхода\n")
        stream_fills(args, emit, MAINNET)
        return

    info = HLInfo(MAINNET)
    seen = {a: set() for a in args}
    for a in args:
        try:
            for fl in info.user_fills(a):
                seen[a].add(fl.get("tid"))
        except Exception as e:
            print(f"init err {a[:10]}: {e}")
    flt = f" (только {coin_filter})" if coin_filter else ""
    print(f"👀 REST-поллинг {poll}с: слежу за {len(args)} адресами{flt}. Ctrl-C для выхода\n")
    while True:
        for a in args:
            try:
                fills = info.user_fills(a)
            except Exception as e:
                print(f"!! {a[:10]}: {e}"); continue
            new = sorted((fl for fl in fills if fl.get("tid") not in seen[a]), key=lambda f: f["time"])
            for fl in new:
                seen[a].add(fl.get("tid"))
                emit(a, fl)
        time.sleep(poll)


if __name__ == "__main__":
    main()
