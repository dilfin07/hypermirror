"""Главный цикл копира: HL (план) -> Binance (исполнение).

DRY-RUN по умолчанию — считает и печатает ордера, НЕ отправляет.
Реальная торговля только с флагом --live (и заданными ключами в .env).

    python3 tools/run_copier.py                 # один проход, dry-run
    python3 tools/run_copier.py --loop          # цикл, dry-run
    python3 tools/run_copier.py --live --loop   # БОЕВОЙ режим (осторожно!)
"""
import _bootstrap  # noqa: F401
import json
import os
import sys
import time

from copier.config import load_config, runtime_path
from copier.secrets import binance_keys
from copier.hl.rest import HLInfo, MAINNET as HL_MAINNET, TESTNET as HL_TESTNET
from copier.core.positions import account_value
from copier.core.plan import compute_plan
from copier.core.format import fmt_usd
from copier.execution.binance import BinanceFutures, symbol_filters, to_symbol
from copier.execution import executor


def run_once(cfg, hl, bn, filters, cs, live):
    mids = {k: float(v) for k, v in hl.all_mids().items()}
    ts = [{**t, "state": hl.clearinghouse_state(t["address"])} for t in cfg["targets"]]

    # наш эквити = баланс Binance (если ключи есть), иначе paper
    have_keys = bool(bn.key and bn.secret)
    hedge = False
    current_legs = {}
    if have_keys:
        my_equity = bn.equity()
        current_legs = bn.positions()
        try:
            hedge = bn.position_mode()
        except Exception:
            hedge = False
        eq_src = "Binance"
    else:
        my_equity = float(cfg.get("paper_equity_usd", 1000))
        eq_src = "paper (нет ключей Binance)"

    desired, frozen, notes = compute_plan(ts, mids, my_equity, cfg, cs)

    acct_mode = "Hedge" if hedge else "One-way"
    print(f"\n💰 эквити: {fmt_usd(my_equity)} ({eq_src})   режим: {'🔴 LIVE' if live else '🟢 DRY-RUN'}   аккаунт: {acct_mode}")
    if frozen:
        print(f"❄️  заморожено на старте: " +
              ", ".join(f"{c}@{l}(+{fr.get('move_pct')}%)" for l, c, p, fr in frozen))
    if desired:
        print("🪞 желаемые позиции:")
        for coin, d in sorted(desired.items(), key=lambda kv: -abs(kv[1]["notional"])):
            print(f"   {d['side']:5} {coin:8} {fmt_usd(d['notional']):>9}  плечо {d['leverage']:.0f}x")
    for n in notes:
        print(f"   • {n}")

    # mark-цены Binance для перевода нотионала в qty
    bn_marks = bn.mark_prices()
    if hedge:
        managed = {to_symbol(c) for c in (cfg.get("coin_whitelist") or []) if to_symbol(c)}
        plan = executor.build_orders_hedge(desired, bn_marks, filters, current_legs, managed)
    else:
        current = {sym: amt for (sym, ps), amt in current_legs.items()}
        plan = executor.build_orders(desired, bn_marks, filters, current)
    print("\n📋 ордера на Binance:")
    print(executor.render(plan))

    if live:
        if not have_keys:
            print("\n❌ --live, но нет ключей в .env. Останов.")
            return
        print("\n🚀 ОТПРАВКА на Binance...")
        for kind, sym, a, res in executor.apply(bn, plan):
            print(f"   {kind} {sym} {a}: {res}")


def main():
    cfg = load_config(sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else None)
    live = "--live" in sys.argv
    loop = "--loop" in sys.argv

    hl = HLInfo(HL_TESTNET if cfg.get("network") == "testnet" else HL_MAINNET)
    net = (cfg.get("binance") or {}).get("network", "testnet")
    key, secret = binance_keys()
    bn = BinanceFutures(key, secret, network=net)

    print(f"HL источник: {cfg.get('network')}  |  Binance: {net}  |  целей: {len(cfg['targets'])}")
    try:
        filters = symbol_filters(bn.exchange_info())
    except Exception as e:
        print(f"!! не получил exchangeInfo Binance: {e}")
        return

    csp = runtime_path(cfg.get("copy_state_file", "copy_state.json"))
    cs = json.load(open(csp)) if os.path.exists(csp) else {}

    while True:
        print("=" * 78)
        try:
            run_once(cfg, hl, bn, filters, cs, live)
            json.dump(cs, open(csp, "w"), indent=2)
        except Exception as e:
            print(f"!! ошибка цикла: {e}")
        if not loop:
            break
        time.sleep(int(cfg.get("poll_interval_sec", 30)))


if __name__ == "__main__":
    main()
