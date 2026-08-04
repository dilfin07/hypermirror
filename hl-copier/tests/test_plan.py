"""Юнит-тесты compute_plan: маржинальный буфер (не съедать 100% equity → нет -2019)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.core.plan import compute_plan


def _target(coin, szi, entry, lev, account_value, spot_usd=0.0):
    return {
        "address": "0xlead", "label": "lead", "weight": 1.0, "spot_usd": spot_usd,
        "state": {
            "marginSummary": {"accountValue": str(account_value)},
            "assetPositions": [{"position": {
                "coin": coin, "szi": str(szi), "entryPx": str(entry),
                "leverage": {"value": str(lev)}, "unrealizedPnl": "0", "positionValue": str(abs(szi) * entry),
            }}],
        },
    }


CFG = {"leverage_mode": "mirror", "mirror_max_leverage": 10, "leverage_cap": 3,
       "margin_buffer_pct": 0.10, "start_skip_open": "none", "skip_builder_dexs": True}


def test_margin_buffer_caps_full_margin_position():
    """Цель exposure = плечу (3x) → desired требует 100% маржи → буфер ужимает до 90%."""
    tgt = _target("ZZZ", -30, 100, 3, account_value=1000)   # notional -3000 = 3x от $1000
    desired, _, notes = compute_plan([tgt], {"ZZZ": 100.0}, 1000.0, CFG, {})
    d = desired["ZZZ"]
    margin = abs(d["notional"]) / d["leverage"]
    assert margin <= 1000 * 0.90 + 1e-6                     # маржа ≤ 90% equity
    assert abs(d["notional"] - (-2700)) < 1.0               # ужато x0.9
    assert any("margin buffer" in n for n in notes)


def test_no_scaling_when_margin_fits():
    """Небольшая позиция (маржа < буфера) не масштабируется."""
    tgt = _target("ZZZ", -15, 100, 3, account_value=1000)   # notional -1500 → маржа 500
    desired, _, notes = compute_plan([tgt], {"ZZZ": 100.0}, 1000.0, CFG, {})
    assert abs(desired["ZZZ"]["notional"] - (-1500)) < 1.0
    assert not any("margin buffer" in n for n in notes)


def test_basis_uses_max_of_perp_and_spot():
    """База = max(перп, спот), НЕ сумма. Спот $2000 > перп $1000 → база $2000 (полный пул,
    подушка учтена), не $3000 (двойной счёт). notional -3000 → плечо 1.5x → desired -1500."""
    tgt = _target("ETH", -30, 100, 3, account_value=1000, spot_usd=2000)
    desired, _, notes = compute_plan([tgt], {"ETH": 100.0}, 1000.0, CFG, {})
    d = desired["ETH"]
    assert abs(d["notional"] - (-1500)) < 5          # basis=max(1000,2000)=2000 → 1.5x
    assert not any("margin buffer" in n for n in notes)  # маржа 500 < 900, буфер не нужен


def test_leverage_cap_zero_is_full_mirror():
    """leverage_cap=0 → БЕЗ кэпа: полная экспозиция лида. >0 → ужимает до потолка.
    Лид в 7x (notional -7000 при банке 1000), плечо 10 → маржа 700 < буфера, буфер не мешает."""
    tgt = _target("ZZZ", -70, 100, 10, account_value=1000)
    # cap=3 → ужимает 7x до 3x
    d3, _, n3 = compute_plan([tgt], {"ZZZ": 100.0}, 1000.0, {**CFG, "leverage_cap": 3}, {})
    assert abs(d3["ZZZ"]["notional"] - (-3000)) < 5, "cap=3 ужимает до 3x"
    assert any("leverage cap" in n for n in n3)
    # cap=0 → полный миррор, экспозиция лида (7x) сохранена
    d0, _, n0 = compute_plan([tgt], {"ZZZ": 100.0}, 1000.0, {**CFG, "leverage_cap": 0}, {})
    assert abs(d0["ZZZ"]["notional"] - (-7000)) < 50, "cap=0 = полная экспозиция лида"
    assert not any("leverage cap" in n for n in n0), "при cap=0 кэп не срабатывает"


def test_size_multiplier():
    """Множитель масштабирует пропорцию лида ПЕРЕД leverage_cap и маржин-буфером.
    Мелкая позиция лида (notional -500 при банке 1000, плечо 10 → маржа 50) —
    буфер и cap не мешают, изолируем чистый множитель."""
    tgt = _target("ZZZ", -5, 100, 10, account_value=1000)   # notional -500
    mids = {"ZZZ": 100.0}
    # база: mult=1.0 → честная пропорция X = -500
    d1, _, n1 = compute_plan([tgt], mids, 1000.0, {**CFG, "size_multiplier": 1.0}, {})
    assert abs(d1["ZZZ"]["notional"] - (-500)) < 1.0
    assert not any("multiplier" in n for n in n1)            # ×1.0 — без пометки
    # ×0.5 → половина X
    d05, _, n05 = compute_plan([tgt], mids, 1000.0, {**CFG, "size_multiplier": 0.5}, {})
    assert abs(d05["ZZZ"]["notional"] - (-250)) < 1.0
    assert any("multiplier ×0.5" in n for n in n05)
    # ×2.0 → удвоение X (gross 1000 < cap 3x=3000, маржа 100 < буфера → чистое ×2)
    d2, _, n2 = compute_plan([tgt], mids, 1000.0, {**CFG, "size_multiplier": 2.0}, {})
    assert abs(d2["ZZZ"]["notional"] - (-1000)) < 1.0
    assert any("multiplier ×2" in n for n in n2)
    assert not any("leverage cap" in n for n in n2), "×2 на мелкой позиции не упирается в cap"
    # <=0 трактуется как 1.0 (не обнуляет, не инвертирует направление)
    d0, _, _ = compute_plan([tgt], mids, 1000.0, {**CFG, "size_multiplier": 0.0}, {})
    assert abs(d0["ZZZ"]["notional"] - (-500)) < 1.0
    dneg, _, _ = compute_plan([tgt], mids, 1000.0, {**CFG, "size_multiplier": -3.0}, {})
    assert abs(dneg["ZZZ"]["notional"] - (-500)) < 1.0, "отрицательный множитель → 1.0, направление SHORT"
    assert dneg["ZZZ"]["side"] == "SHORT"


def test_size_multiplier_capped_by_leverage():
    """×2 на КРУПНОЙ позиции лида упирается в leverage_cap (cap — потолок поверх множителя).
    Лид notional -2000 (2x), ×2 → -4000, но cap=3 → gross ≤ 3000."""
    tgt = _target("ZZZ", -20, 100, 10, account_value=1000)  # notional -2000
    d, _, n = compute_plan([tgt], {"ZZZ": 100.0}, 1000.0, {**CFG, "size_multiplier": 2.0}, {})
    assert abs(d["ZZZ"]["notional"] - (-3000)) < 5, "×2 (=-4000) ужато cap 3x до -3000"
    assert any("multiplier ×2" in n for n in n), "множитель применён"
    assert any("leverage cap" in n for n in n), "cap сработал поверх множителя"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
