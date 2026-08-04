"""Планировщик копирования (dry-run): плечо + заморозка → желаемые позиции.

«Мозг» копира. Binance-исполнитель (Ф3) будет потреблять его выход.

    python3 tools/plan.py [--config config.json] [--loop]
"""
import _bootstrap  # noqa: F401
import json
import os
import sys
import time

from copier.config import load_config, runtime_path
from copier.hl.rest import HLInfo, MAINNET, TESTNET
from copier.core.positions import account_value
from copier.core.plan import compute_plan
from copier.core.format import fmt_usd


def run_once(cfg, info, cs):
    mids = {k: float(v) for k, v in info.all_mids().items()}
    ts = [{**t, "state": info.clearinghouse_state(t["address"])} for t in cfg["targets"]]
    addr = (cfg.get("account_address") or "").strip()
    my_equity = account_value(info.clearinghouse_state(addr)) if addr else float(cfg.get("paper_equity_usd", 1000))

    desired, frozen, notes = compute_plan(ts, mids, my_equity, cfg, cs)

    mode = cfg.get("leverage_mode")
    lev_txt = f"fixed({cfg.get('fixed_leverage')}x)" if mode == "fixed" else f"mirror (потолок {cfg.get('mirror_max_leverage')}x)"
    print(f"\n💰 эквити: {fmt_usd(my_equity)}   плечо: {lev_txt}   "
          f"старт-скип: {cfg.get('start_skip_open')} >= {cfg.get('start_skip_profit_pct')}%")

    if frozen:
        print("\n❄️  ЗАМОРОЖЕНЫ на старте (НЕ копируем — цена убежала в плюс):")
        for label, coin, p, fr in frozen:
            print(f"   {coin:8} {('SHORT' if p['szi']<0 else 'LONG'):5} у {label}  "
                  f"+{fr.get('move_pct','?')}% от входа (entry {p['entryPx']:.4g})")
        print("   → копируем монету только после ПОЛНОГО закрытия её целью")

    print("\n🪞 ЖЕЛАЕМЫЕ позиции (копируем):")
    if not desired:
        print("   (пока ничего — активное заморожено; ждём новых входов)")
    for coin, d in sorted(desired.items(), key=lambda kv: -abs(kv[1]["notional"])):
        tl = f" (их {d['target_leverage']:.0f}x)" if d["target_leverage"] else ""
        print(f"   {d['side']:5} {coin:8} {abs(d['size']):>12.4g}  {fmt_usd(d['notional']):>9}  "
              f"плечо {d['leverage']:.0f}x{tl}  ← {','.join(d['from'])}")
    for n in notes:
        print(f"   • {n}")


def main():
    cfg = load_config(sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else None)
    info = HLInfo(TESTNET if cfg.get("network") == "testnet" else MAINNET)
    csp = runtime_path(cfg.get("copy_state_file", "copy_state.json"))
    cs = json.load(open(csp)) if os.path.exists(csp) else {}
    loop = "--loop" in sys.argv
    while True:
        print("=" * 78)
        print("COPY PLAN (dry-run)")
        try:
            run_once(cfg, info, cs)
            json.dump(cs, open(csp, "w"), indent=2)
        except Exception as e:
            print(f"!! ошибка: {e}")
        if not loop:
            break
        time.sleep(int(cfg.get("poll_interval_sec", 30)))


if __name__ == "__main__":
    main()
