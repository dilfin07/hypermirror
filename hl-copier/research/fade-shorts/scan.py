#!/usr/bin/env python3
"""fade-shorts/scan.py — сканер сетапа трейдера day-trade (0x92bbd811).

Воспроизводит его entry-логику: ШОРТ перегретого альта (памп +X% за N дней) с
ПОЛОЖИТЕЛЬНЫМ фандингом (лонги перегружены → платят шортам). Чистое чтение
публичного Binance API (ключи не нужны).

Стратегия (реверс-инжиниринг по его сделкам):
  setup  : альт пампанул +20-25% за ~5-7д, фандинг положительный (часто высокий)
  entry  : пассивный post-only шорт у локального топа, набор лимитками за часы
  hold   : 1-14 дней, ловим mean-reversion вниз + собираем фандинг (carry)
  winner : держать пока реверсия идёт (большие винеры −40…−70%)
  loser  : если сквиз против — РЕЗАТЬ быстро (4-5ч), не усредняться (его лоси так и закрыты)
  risk   : асимметрия (мелкие быстрые лоси / крупные медленные вины), кэш-буфер держит плечо ~0.7x

Запуск: .venv/bin/python research/fade-shorts/scan.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
from copier.execution.binance import BinanceFutures  # noqa: E402

PUMP_MIN = 10.0          # минимальный памп за 7д для кандидата, %
TOP_FUNDING = 45         # сколько монет с топ-фандингом просеивать


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def main():
    bn = BinanceFutures()                                    # публичные эндпоинты
    info = bn.exchange_info()
    perps = [s["symbol"] for s in info["symbols"]
             if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
             and s.get("status") == "TRADING"]
    prem = bn._request("GET", "/fapi/v1/premiumIndex")
    fund = {d["symbol"]: _f(d.get("lastFundingRate")) for d in prem}
    top = sorted([s for s in perps if fund.get(s, 0) > 0], key=lambda s: -fund.get(s, 0))[:TOP_FUNDING]

    rows = []
    for sym in top:
        try:
            kl = bn.klines(sym, "1d", 9)
        except Exception:
            continue
        if len(kl) < 8:
            continue
        cl = [_f(k[4]) for k in kl]
        hi = [_f(k[2]) for k in kl]
        c7, last, hi7 = cl[-8], cl[-1], max(hi[-8:])
        if c7 <= 0:
            continue
        rows.append({"s": sym.replace("USDT", ""), "pump7": (last / c7 - 1) * 100,
                     "fapr": fund[sym] * 3 * 365 * 100, "f8h": fund[sym] * 100,
                     "disthi": (last / hi7 - 1) * 100})

    cand = sorted([r for r in rows if r["pump7"] > PUMP_MIN],
                  key=lambda r: -(r["pump7"] * r["f8h"]))
    print(f"=== ШОРТ-КАНДИДАТЫ (памп >{PUMP_MIN:.0f}% за 7д + положит. фандинг) ===")
    print("  %-9s %8s %12s %9s %7s" % ("монета", "памп7д", "фандинг(APR)", "фанд/8ч", "от хая"))
    for r in cand[:15]:
        print("  %-9s %+7.0f%% %+10.0f%% %+7.3f%% %+6.0f%%"
              % (r["s"], r["pump7"], r["fapr"], r["f8h"], r["disthi"]))
    print("\n=== топ по фандингу (лонги платят шортам) ===")
    for r in sorted(rows, key=lambda r: -r["f8h"])[:8]:
        print("  %-9s фанд/8ч %+.3f%% (APR %+.0f%%) памп7д %+.0f%%" % (r["s"], r["f8h"], r["fapr"], r["pump7"]))


if __name__ == "__main__":
    main()
