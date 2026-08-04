"""Сетка лимитных ордеров цели в стакане (frontendOpenOrders, публично).

    python3 tools/show_orders.py <addr> [--coin BTC]
"""
import _bootstrap  # noqa: F401
import sys
from collections import defaultdict

from copier.hl.rest import HLInfo, MAINNET


def main():
    coin_filter = None
    argv, args, i = sys.argv[1:], [], 0
    while i < len(argv):
        if argv[i] == "--coin":
            coin_filter = argv[i + 1].upper(); i += 2; continue
        if argv[i].startswith("--"):
            i += 1; continue
        args.append(argv[i]); i += 1
    if not args:
        print("usage: show_orders.py <addr> [--coin BTC]")
        return
    addr = args[0]
    orders = HLInfo(MAINNET).open_orders(addr)

    by_coin = defaultdict(lambda: {"buy": [], "sell": []})
    for o in orders:
        coin = o["coin"]
        if coin_filter and coin.upper() != coin_filter:
            continue
        side = "buy" if o["side"] == "B" else "sell"
        by_coin[coin][side].append({"px": float(o["limitPx"]), "sz": float(o["sz"]),
                                    "reduce": o.get("reduceOnly", False), "tif": o.get("tif", "")})

    print(f"📋 Сетка ордеров {addr[:12]}…  всего {len(orders)} ордеров\n")
    for coin in sorted(by_coin):
        b = sorted(by_coin[coin]["buy"], key=lambda x: -x["px"])
        s = sorted(by_coin[coin]["sell"], key=lambda x: x["px"])
        bn = sum(x["px"] * x["sz"] for x in b)
        sn = sum(x["px"] * x["sz"] for x in s)
        print(f"━━ {coin}  |  BUY x{len(b)} (${bn:,.0f})   SELL x{len(s)} (${sn:,.0f})")
        if s:
            print(f"   SELL лесенка: {s[0]['px']:.6g} … {s[-1]['px']:.6g}")
            for o in s[:6]:
                print(f"     🔴 SELL {o['sz']:>10.4g} @ {o['px']:<10.6g} {o['tif']}{' R' if o['reduce'] else ''}")
        if b:
            print(f"   BUY лесенка:  {b[0]['px']:.6g} … {b[-1]['px']:.6g}")
            for o in b[:6]:
                print(f"     🟢 BUY  {o['sz']:>10.4g} @ {o['px']:<10.6g} {o['tif']}{' R' if o['reduce'] else ''}")
        print()


if __name__ == "__main__":
    main()
