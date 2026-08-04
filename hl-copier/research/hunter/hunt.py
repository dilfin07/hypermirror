#!/usr/bin/env python3
"""hunt.py — самостоятельный охотник за трейдерами Hyperliquid.

Не зависит от Hyperdash и его фильтров: seed-вселенную берём из сырого лидерборда HL,
метрики считаем сами по userFills (PnL/ROI лидерборда искажены вводами/выводами — мусор).

Стадии (каждая пишет артефакт в data/, читается следующей — можно смотреть улов между шагами):
  seed     скачать сырой лидерборд HL            -> data/00_leaderboard.json
  active   нормализовать + отсеять активных      -> data/01_active.json
  profile  глубокий профиль по userFills (N)     -> data/02_profiles.jsonl  (резюмируемо)
  classify классификация на группы + скоринг     -> data/03_classified.json + отчёт

Чистое чтение HL — Binance/ключи/домашняя сеть не нужны.

Пример:
  .venv/bin/python research/hunter/hunt.py seed
  .venv/bin/python research/hunter/hunt.py active --min-acct 30000 --max-acct 3000000
  .venv/bin/python research/hunter/hunt.py profile --limit 50
  .venv/bin/python research/hunter/hunt.py classify
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))   # hl-copier/
sys.path.insert(0, ROOT)
from copier.hl.rest import HLInfo  # noqa: E402

DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
LB_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
LATENCY_SEC = 5.7   # наша задержка event->ордер; удержание сильно меньше = копировать нельзя


def P(*a):
    return os.path.join(DATA, *a)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ---------- stage: seed ----------
def cmd_seed(args):
    out = P("00_leaderboard.json")
    if os.path.exists(out) and not args.force:
        n = len(json.load(open(out))["leaderboardRows"])
        print(f"seed: уже есть {out} ({os.path.getsize(out)//1024//1024} МБ, {n} адресов) — --force чтобы перекачать")
        return
    import urllib.request
    print("seed: качаю лидерборд…")
    req = urllib.request.Request(LB_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    open(out, "wb").write(data)
    n = len(json.loads(data)["leaderboardRows"])
    print(f"seed: {n} адресов -> {out} ({len(data)//1024//1024} МБ)")


# ---------- stage: active ----------
def cmd_active(args):
    rows = json.load(open(P("00_leaderboard.json")))["leaderboardRows"]
    out = []
    for r in rows:
        av = _f(r["accountValue"])
        w = {k: v for k, v in r["windowPerformances"]}

        def win(name):
            d = w.get(name, {})
            return {"pnl": _f(d.get("pnl")), "roi": _f(d.get("roi")), "vlm": _f(d.get("vlm"))}
        day, week, month, allt = win("day"), win("week"), win("month"), win("allTime")
        if week["vlm"] <= 0:                       # активность: торговал за последнюю неделю
            continue
        if not (args.min_acct <= av <= args.max_acct):
            continue
        out.append({"address": r["ethAddress"], "acct": round(av, 2),
                    "day": day, "week": week, "month": month, "allTime": allt})
    out.sort(key=lambda x: -x["week"]["vlm"])
    json.dump(out, open(P("01_active.json"), "w"), indent=1)
    print(f"active: из {len(rows)} -> {len(out)} активных "
          f"(торговали за неделю, размер ${args.min_acct:,.0f}–${args.max_acct:,.0f})")
    if out:
        accts = sorted(x["acct"] for x in out)
        med = accts[len(accts)//2]
        print(f"  медианный размер ${med:,.0f}; топ-3 по недельному обороту:")
        for x in out[:3]:
            print(f"    {x['address']}  acct=${x['acct']:,.0f}  week_vlm=${x['week']['vlm']:,.0f}")


# ---------- stage: profile ----------
def profile_address(hl, addr):
    fills = hl.user_fills(addr) or []
    n = len(fills)
    res = {"address": addr, "n_fills": n}
    if n == 0:
        res["style"] = "no-fills"
        return res
    fills = sorted(fills, key=lambda f: f.get("time", 0))
    t0, t1 = fills[0]["time"], fills[-1]["time"]
    span_days = max((t1 - t0) / 86400000.0, 1e-9)
    res["span_days"] = round(span_days, 1)
    res["fills_per_day"] = round(n / span_days, 2)
    res["taker_ratio"] = round(sum(1 for f in fills if f.get("crossed")) / n, 3)
    res["fees"] = round(sum(_f(f.get("fee")) for f in fills), 2)
    res["coins"] = len(set(f.get("coin") for f in fills))

    # реализованный PnL по закрытиям (чистый, без вводов/выводов)
    closes = [f for f in fills if "Close" in (f.get("dir") or "") or _f(f.get("closedPnl")) != 0]
    pnls = [_f(f.get("closedPnl")) for f in closes]
    res["n_closes"] = len(closes)
    res["realized"] = round(sum(pnls), 2)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    res["win_rate"] = round(len(wins) / len(pnls) * 100, 1) if pnls else None
    aw = (sum(wins) / len(wins)) if wins else 0.0
    al = (-sum(losses) / len(losses)) if losses else 0.0
    res["payoff"] = round(aw / al, 2) if al else None
    gp, gl = sum(wins), -sum(losses)
    res["profit_factor"] = round(gp / gl, 2) if gl else None
    tot_abs = sum(abs(p) for p in pnls) or 1.0
    res["top_trade_share"] = round(max((abs(p) for p in pnls), default=0) / tot_abs, 2)

    # время удержания: FIFO по монете через dir Open/Close (минуты)
    holds = []
    book = defaultdict(deque)
    for f in fills:
        coin, d, sz, tm = f.get("coin"), (f.get("dir") or ""), _f(f.get("sz")), f.get("time")
        if "Open" in d:
            book[coin].append([tm, sz])
        elif "Close" in d:
            rem = sz
            while rem > 1e-12 and book[coin]:
                otm, osz = book[coin][0]
                take = min(rem, osz)
                holds.append((tm - otm) / 60000.0)
                rem -= take
                if osz - take <= 1e-12:
                    book[coin].popleft()
                else:
                    book[coin][0][1] = osz - take
    if holds:
        holds.sort()
        res["median_hold_min"] = round(holds[len(holds)//2], 1)
        res["n_round_trips"] = len(holds)
    else:
        res["median_hold_min"] = None
        res["n_round_trips"] = 0

    # снапшот текущих позиций + нереализованный убыток (детектор бэгхолдера)
    try:
        st = hl.clearinghouse_state(addr)
        ms = st.get("marginSummary") or {}
        res["acct_value"] = round(_f(ms.get("accountValue")), 2)
        upnls = []
        max_lev = 0
        for ap in st.get("assetPositions", []):
            p = ap.get("position") or {}
            if _f(p.get("szi")) == 0:
                continue
            upnls.append(_f(p.get("unrealizedPnl")))
            max_lev = max(max_lev, _f((p.get("leverage") or {}).get("value")))
        res["open_positions"] = len(upnls)
        res["max_lev"] = max_lev
        res["open_upnl"] = round(sum(upnls), 2)
        res["worst_pos_upnl"] = round(min(upnls), 2) if upnls else 0.0
    except Exception as e:
        res["snap_err"] = str(e)[:80]

    # чистая кривая PnL (pnlHistory — без вводов/выводов) + просадка
    try:
        pf = dict(hl.portfolio(addr))
        chosen = pf.get("allTime") or pf.get("month") or pf.get("week") or {}
        hist = chosen.get("pnlHistory") or []
        curve = [[int(t), round(_f(v), 2)] for t, v in hist]
        if curve:
            res["curve"] = curve[-400:]            # для рисования
            res["curve_pts"] = len(curve)
            peak = curve[0][1]
            maxdd = 0.0
            for _, v in curve:
                peak = max(peak, v)
                maxdd = max(maxdd, peak - v)
            peak_all = max(v for _, v in curve)
            last = curve[-1][1]
            res["pnl_last"] = last
            res["pnl_peak"] = round(peak_all, 2)
            res["max_dd_abs"] = round(maxdd, 2)
            res["cur_dd_abs"] = round(peak_all - last, 2)     # насколько ниже пика сейчас
            denom = max(abs(peak_all), abs(last), 1.0)
            res["max_dd_pct"] = round(maxdd / denom * 100, 1)
            res["cur_dd_pct"] = round((peak_all - last) / denom * 100, 1)
            res["underwater"] = bool((peak_all - last) > 0.10 * denom)  # >10% ниже пика
    except Exception as e:
        res["pf_err"] = str(e)[:80]

    res["copyable"] = bool(res["median_hold_min"] is not None
                           and res["median_hold_min"] * 60 >= LATENCY_SEC * 20)  # >=~2 мин запас
    res["style"] = classify(res)
    res["flags"] = flags(res)
    return res


def flags(r):
    """Пометки на ручной разбор (НЕ автоотсев)."""
    out = []
    wr = r.get("win_rate") or 0
    po = r.get("payoff")
    pf_ = r.get("profit_factor") or 0
    cur = r.get("cur_dd_pct") or 0
    mdd = r.get("max_dd_pct") or 0
    upnl = r.get("open_upnl") or 0
    acct = max(abs(r.get("acct_value") or 0), 1.0)
    if po is not None and po < 1 and wr > 80:
        out.append("мартингейл?")           # копейки часто + редкий крупный лось
    if wr > 95 or pf_ > 50:
        out.append("слишком-идеально")       # вероятно грид/бот
    if mdd > 70:
        out.append(f"обнулялся({mdd:.0f}%)")  # был около-обнуления — теперь отыгрывается
    if cur > 40:
        out.append(f"под-водой -{cur:.0f}%")  # глубоко ниже пика сейчас (вытаскивает счёт)
    if (r.get("pnl_last") or 0) < 0:
        out.append("суммарно −")             # чистый PnL за всё время отрицательный
    if upnl < 0 and abs(upnl) > 0.15 * acct:
        out.append("бэгхолдер")              # держит крупный нереализ. убыток
    return out


def classify(r):
    n = r.get("n_fills") or 0
    nc = r.get("n_closes") or 0
    fpd = r.get("fills_per_day") or 0
    mh = r.get("median_hold_min")
    maker = 1 - (r.get("taker_ratio") or 0)
    if n < 10 or nc < 5:
        return "thin"
    if (r.get("top_trade_share") or 0) > 0.6:
        return "one-hit"
    if maker > 0.75 and fpd > 30:
        return "MM"
    if fpd > 100:
        return "bot/HFT"
    if mh is None:
        return "unknown"
    if mh < 5:
        return "scalper"
    if mh <= 60:
        return "intraday"
    if mh <= 4320:          # <= 3 дней
        return "swing"
    return "position"        # > 3 дней


def cmd_profile(args):
    cand = json.load(open(P("01_active.json")))
    done = set()
    out_path = P("02_profiles.jsonl")
    if os.path.exists(out_path) and not args.force:
        for line in open(out_path):
            try:
                done.add(json.loads(line)["address"])
            except Exception:
                pass
    elif args.force and os.path.exists(out_path):
        os.remove(out_path)

    pool = cand[args.offset::args.every] if args.every > 1 else cand[args.offset:]
    todo = [c for c in pool if c["address"] not in done][:args.limit]
    print(f"profile: кандидатов {len(cand)}, уже профилировано {len(done)}, в этот заход {len(todo)}")
    hl = HLInfo()
    fh = open(out_path, "a")
    t_start = time.time()
    for i, c in enumerate(todo, 1):
        addr = c["address"]
        try:
            r = profile_address(hl, addr)
        except Exception as e:
            r = {"address": addr, "style": "error", "err": str(e)[:120]}
        r["seed_acct"] = c["acct"]
        r["week_vlm"] = c["week"]["vlm"]
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush()
        if i % 10 == 0 or i == len(todo):
            rate = i / max(time.time() - t_start, 1e-9)
            print(f"  {i}/{len(todo)}  ({rate:.1f} адр/с)  последний: {r.get('style')} {addr[:10]}")
    fh.close()
    print(f"profile: готово, всего профилей {len(done)+len(todo)} -> {out_path}")


# ---------- stage: classify ----------
def score(r):
    if r.get("style") not in ("intraday", "swing", "position"):
        return None
    pf = min(r.get("profit_factor") or 0, 5)     # клампим, чтобы PF=599 не доминировал
    po = min(r.get("payoff") or 0, 5)
    wr = r.get("win_rate") or 0
    rz = r.get("realized") or 0
    ths = r.get("top_trade_share") or 1
    mdd = r.get("max_dd_pct")
    s = 0.0
    s += pf * 2.0                  # прибыльность (profit factor)
    s += po * 1.0                  # асимметрия (режет лоси / тянет профит)
    s += wr * 0.03                 # винрейт
    s += (1 - ths) * 3.0           # не one-hit (диверсификация результата)
    s += 2.0 if rz > 0 else -3.0   # реально в плюсе по реализованному
    if mdd is not None:            # риск-дисциплина: штраф за просадку
        s -= min(mdd, 100) * 0.05
    s -= len(r.get("flags") or []) * 1.5   # каждый красный флаг — минус
    return round(s, 2)


def _spark(curve, w=260, h=56):
    """SVG-кривая cumulative PnL с нулевой базой."""
    if not curve or len(curve) < 2:
        return '<svg width="%d" height="%d"></svg>' % (w, h)
    ys = [v for _, v in curve]
    lo, hi = min(ys + [0]), max(ys + [0])
    rng = (hi - lo) or 1.0
    n = len(curve)
    def X(i):
        return i * (w - 2) / (n - 1) + 1
    def Y(v):
        return h - 2 - (v - lo) / rng * (h - 4)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(curve))
    zero = Y(0)
    up = ys[-1] >= 0
    col = "#3fb950" if up else "#f85149"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<line x1="0" y1="{zero:.1f}" x2="{w}" y2="{zero:.1f}" stroke="#30363d" stroke-width="1"/>'
            f'<polyline fill="none" stroke="{col}" stroke-width="1.5" points="{pts}"/></svg>')


def _hold_str(mh):
    if not mh:
        return "—"
    return f"{mh/1440:.1f}д" if mh >= 1440 else (f"{mh/60:.1f}ч" if mh >= 60 else f"{mh:.0f}м")


def render_html(rows, path):
    css = ("body{background:#0d1117;color:#c9d1d9;font:13px/1.4 -apple-system,Segoe UI,sans-serif;margin:16px}"
           "h1{font-size:18px}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px}"
           ".c{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}"
           ".c.bad{border-color:#7d3a3a}.a{color:#58a6ff;text-decoration:none;font-family:monospace;font-size:12px}"
           ".m{color:#8b949e;font-size:12px;margin:4px 0}.v{color:#c9d1d9}"
           ".tag{display:inline-block;background:#21262d;border-radius:4px;padding:1px 6px;margin:1px;font-size:11px}"
           ".fl{color:#f0883e;font-size:11px;margin-top:4px}.pos{color:#3fb950}.neg{color:#f85149}")
    cards = []
    for i, r in enumerate(rows, 1):
        a = r["address"]
        rz = r.get("realized") or 0
        dd = r.get("max_dd_pct")
        cur = r.get("cur_dd_pct")
        fl = r.get("flags") or []
        cls = "c bad" if fl else "c"
        rzc = "pos" if rz >= 0 else "neg"
        cards.append(
            f'<div class="{cls}">'
            f'<div><b>#{i}</b> score {r.get("score","—")} '
            f'<span class="tag">{r.get("style")}</span> '
            f'<span class="tag">{_hold_str(r.get("median_hold_min"))}</span></div>'
            f'{_spark(r.get("curve") or [])}'
            f'<div class="m">PnL(чистый): <span class="{rzc}">${r.get("pnl_last", rz):,.0f}</span> · '
            f'maxDD {dd if dd is not None else "—"}% · сейчас -{cur if cur is not None else 0}%</div>'
            f'<div class="m">сделок {r.get("n_round_trips",0)} · WR {r.get("win_rate") or "—"}% · '
            f'PF {r.get("profit_factor") or "—"} · payoff {r.get("payoff") or "—"} · монет {r.get("coins","—")}</div>'
            f'<div class="m">acct ${r.get("acct_value") or r.get("seed_acct") or 0:,.0f} · '
            f'плечо {r.get("max_lev",0):g}x · откр.поз {r.get("open_positions",0)} '
            f'(uPnL ${r.get("open_upnl",0):,.0f})</div>'
            + (f'<div class="fl">⚠ {" · ".join(fl)}</div>' if fl else "")
            + f'<div style="margin-top:6px">'
            f'<a class="a" href="https://hyperdash.info/trader/{a}" target="_blank">Hyperdash↗</a> · '
            f'<a class="a" href="https://app.hyperliquid.xyz/explorer/address/{a}" target="_blank">{a[:14]}…↗</a>'
            f'</div></div>')
    html = (f"<!doctype html><meta charset=utf-8><title>HL hunter</title><style>{css}</style>"
            f"<h1>Кривые трейдеров — улов {len(rows)} (чистые кандидаты вверху, ⚠ помечены на ручной разбор)</h1>"
            f'<div class="g">{"".join(cards)}</div>')
    open(path, "w").write(html)


def cmd_classify(args):
    profs = [json.loads(l) for l in open(P("02_profiles.jsonl"))]
    groups = defaultdict(list)
    for r in profs:
        groups[r.get("style", "unknown")].append(r)
    print(f"classify: всего профилей {len(profs)}")
    print("  группы:")
    for g in sorted(groups, key=lambda k: -len(groups[k])):
        print(f"    {g:12s} {len(groups[g]):4d}")

    # все копируемые стили с кривой — для визуального просмотра (флаги НЕ отсев)
    gallery = []
    for r in profs:
        sc = score(r)
        if sc is None or not r.get("curve"):
            continue
        r["score"] = sc
        gallery.append(r)
    gallery.sort(key=lambda r: -r["score"])
    clean = [r for r in gallery if not r.get("flags")]
    flagged = [r for r in gallery if r.get("flags")]
    ordered = clean + flagged                       # чистые сверху, флаги — ниже
    json.dump({"groups": {g: len(v) for g, v in groups.items()},
               "clean": len(clean), "flagged": len(flagged),
               "rows": ordered}, open(P("03_classified.json"), "w"),
              indent=1, ensure_ascii=False)
    html_path = P("report.html")
    render_html(ordered[:args.top], html_path)
    print(f"\n  кривые: {len(gallery)} копируемых ({len(clean)} чистых, {len(flagged)} с флагами)")
    print(f"  HTML-галерея (топ-{min(args.top,len(ordered))}): {html_path}")
    print(f"\n  Топ-{min(15,len(clean))} ЧИСТЫХ (без флагов):")
    print(f"  {'#':>2} {'score':>5} {'style':9} {'hold':>7} {'WR%':>5} {'PF':>5} {'payoff':>6} {'maxDD%':>6} {'realized':>11}  address")
    for i, r in enumerate(clean[:15], 1):
        print(f"  {i:>2} {r['score']:>5} {r['style']:9} {_hold_str(r.get('median_hold_min')):>7} "
              f"{(r.get('win_rate') or 0):>5} {(r.get('profit_factor') or 0):>5} {(r.get('payoff') or 0):>6} "
              f"{(r.get('max_dd_pct') or 0):>6} ${(r.get('realized') or 0):>10,.0f}  {r['address']}")


def main():
    ap = argparse.ArgumentParser(description="Охотник за трейдерами Hyperliquid")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed");    s.add_argument("--force", action="store_true")
    a = sub.add_parser("active")
    a.add_argument("--min-acct", type=float, default=30000)
    a.add_argument("--max-acct", type=float, default=3000000)
    p = sub.add_parser("profile")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--every", type=int, default=1, help="брать каждый N-й (выборка по всему списку, не только топ-оборот)")
    p.add_argument("--force", action="store_true")
    c = sub.add_parser("classify")
    c.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    {"seed": cmd_seed, "active": cmd_active, "profile": cmd_profile, "classify": cmd_classify}[args.cmd](args)


if __name__ == "__main__":
    main()
