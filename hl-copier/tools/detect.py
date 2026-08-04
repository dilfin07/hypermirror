"""Детектор изменений NET-позиции (для копира) → events.jsonl.

Сравнивает снимки позиций цели, эмитит OPEN/INCREASE/REDUCE/CLOSE/FLIP/LEVERAGE_CHANGE
с портируемыми величинами (exposure_pct). Только чтение.

    python3 tools/detect.py [--config config_test.json] [--loop]
"""
import _bootstrap  # noqa: F401
import json
import os
import sys

from copier.config import load_config, runtime_path
from copier.hl.rest import HLInfo, MAINNET, TESTNET
from copier.core.positions import account_value, net_positions
from copier.core.events import classify_net_change
from copier.core.format import now_iso

ICON = {"OPEN": "🟢", "INCREASE": "➕", "REDUCE": "➖", "CLOSE": "⚪",
        "FLIP": "🔄", "LEVERAGE_CHANGE": "⚙️", "SYNC": "📍"}


def snapshot(state_raw, mids, cfg):
    eq = account_value(state_raw)
    wl = set(cfg.get("coin_whitelist") or [])
    skip_builder = cfg.get("skip_builder_dexs", True)
    out = {}
    for coin, p in net_positions(state_raw).items():
        if p["szi"] == 0 or (skip_builder and ":" in coin) or (wl and coin not in wl):
            continue
        mark = mids.get(coin) or p["entryPx"]
        notional = abs(p["szi"]) * mark
        out[coin] = {"size": p["szi"], "side": "LONG" if p["szi"] > 0 else "SHORT",
                     "lev": p["lev"], "mark": mark, "entry": p["entryPx"],
                     "notional": notional, "exposure_pct": (notional / eq * 100) if eq else 0.0}
    return out, eq


def emit(target, coin, action, cur, prev, eq):
    e = {"ts": now_iso(), "target": target, "coin": coin, "action": action,
         "side": (cur or prev)["side"], "leverage": (cur or prev)["lev"],
         "mark": round((cur or prev)["mark"], 6), "target_equity": round(eq)}
    if cur:
        e.update(exposure_pct=round(cur["exposure_pct"], 1), notional=round(cur["notional"]), size=cur["size"])
    if prev:
        e.update(prev_exposure_pct=round(prev["exposure_pct"], 1), prev_size=prev["size"])
    if cur and prev:
        e["delta_exposure_pct"] = round(cur["exposure_pct"] - prev["exposure_pct"], 1)
    return e


def fmt(e):
    a = e["action"]
    base = f"{ICON.get(a,'•')} {a:15} {e['side']:5} {e['coin']:8}"
    if a in ("OPEN", "SYNC", "FLIP", "INCREASE", "REDUCE"):
        s = f"exp {e.get('exposure_pct',0):>6.1f}%  {e['leverage']:.0f}x  ~${e.get('notional',0):,}"
        if "delta_exposure_pct" in e:
            s += f"  (Δ {e['delta_exposure_pct']:+.1f}%)"
        return base + "  " + s
    if a == "CLOSE":
        return base + f"  было exp {e.get('prev_exposure_pct',0):.1f}%"
    if a == "LEVERAGE_CHANGE":
        return base + f"  плечо → {e['leverage']:.0f}x"
    return base


def main():
    cfg = load_config(sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else None)
    info = HLInfo(TESTNET if cfg.get("network") == "testnet" else MAINNET)
    sp = runtime_path(cfg.get("state_file", "state.json"))
    state = json.load(open(sp)) if os.path.exists(sp) else {}
    loop, first = "--loop" in sys.argv, True
    ev_path = runtime_path(cfg.get("events_file", "events.jsonl"))
    min_delta = float(cfg.get("min_event_delta_pct", 5))
    import time
    while True:
        print("=" * 78)
        print(f"HL DETECTOR  {now_iso()}  ({cfg.get('network')})")
        try:
            mids = {k: float(v) for k, v in info.all_mids().items()}
            all_real = []
            for t in cfg["targets"]:
                cur, eq = snapshot(info.clearinghouse_state(t["address"]), mids, cfg)
                prev = state.get(t["address"])
                evs = []
                if prev is None:
                    evs = [emit(t.get("label", t["address"][:10]), c, "SYNC", v, None, eq) for c, v in cur.items()]
                else:
                    for c in sorted(set(prev) | set(cur)):
                        for action, cc, pp in classify_net_change(prev.get(c), cur.get(c), min_delta):
                            evs.append(emit(t.get("label", t["address"][:10]), c, action, cc, pp, eq))
                state[t["address"]] = cur
                if evs:
                    print(f"\n🎯 {t.get('label', t['address'][:10])}  эквити ${eq:,.0f}")
                    for e in evs:
                        print("   " + fmt(e))
                all_real += [e for e in evs if e["action"] != "SYNC"]
            if all_real:
                with open(ev_path, "a") as fh:
                    for e in all_real:
                        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            json.dump(state, open(sp, "w"), indent=2)
            if first and not all_real:
                print("\n  ↑ базовый снимок (SYNC). События — со следующего опроса.")
            elif not all_real and not first:
                print("  (изменений нет)")
        except Exception as e:
            print(f"  !! ошибка: {e}")
        first = False
        if not loop:
            break
        time.sleep(int(cfg.get("poll_interval_sec", 30)))


if __name__ == "__main__":
    main()
