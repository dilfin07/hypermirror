"""Юнит-тесты чистой логики капитала/позиций (без сети).

Ключевое: база пропорции = max(перп-эквити, спот-USDC) — ОДИН пул USDC (спот backs перп),
не сумма (сумма = двойной счёт, раздувало капитал цели). Совпадает с Hyperdash.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.core.positions import account_value, spot_capital_usd, net_positions


# Реальный снимок pension-usdt (HL API, 2026-07-05): перп accountValue $13.9M, спот-USDC
# $21.05M (весь hold = перп-залог). Hyperdash: спот-холдинги $0, капитал $21.03M, плечо 4.27x
# → это ОДИН пул USDC, база = max(перп, спот) = $21.05M, а НЕ сумма $35M (двойной счёт).
PENSION_SPOT = {
    "balances": [
        {"coin": "USDC", "total": "21053299.88", "hold": "21053299.88"},
        {"coin": "HYPE", "total": "0.0", "hold": "0.0"},          # не стейбл → игнор
    ]
}
PENSION_PERP = {"marginSummary": {"accountValue": "13914533.0"}}
PENSION_ETH_NOTIONAL = 89_750_000.0


def test_spot_capital_counts_held():
    """Весь стейбл-баланс (включая hold), а не только free."""
    assert abs(spot_capital_usd(PENSION_SPOT) - 21053299.88) < 1e-2


def test_basis_is_max_not_sum():
    """База = max(перп, спот) = $21.05M (полный пул), НЕ сумма $35M (двойной счёт)."""
    perp = account_value(PENSION_PERP)               # $13.9M
    spot = spot_capital_usd(PENSION_SPOT)            # $21.05M
    basis = max(perp, spot)
    assert abs(basis - spot) < 1e-2                  # спот > перп → база = спот
    assert basis < 22_000_000                        # не сумма $35M


def test_real_leverage_matches_hyperdash():
    """Плечо цели = notional / max(перп,спот) ≈ 4.26x (= Hyperdash 4.27x), а не 6.45x
    к перп-эквити и не 2.56x к раздутой сумме."""
    basis = max(account_value(PENSION_PERP), spot_capital_usd(PENSION_SPOT))
    assert abs(PENSION_ETH_NOTIONAL / basis - 4.26) < 0.05


def test_spot_capital_only_stables():
    """Волатильные токены в стейбл-капитал не считаем."""
    st = {"balances": [
        {"coin": "USDC", "total": "1000", "hold": "300"},
        {"coin": "HYPE", "total": "500", "hold": "0"},
    ]}
    assert spot_capital_usd(st) == 1000.0            # 1000 total USDC, HYPE игнор


def test_usdt_counted_total():
    st = {"balances": [{"coin": "USDT", "total": "2000", "hold": "500"}]}
    assert spot_capital_usd(st) == 2000.0            # весь total, не total−hold


def test_spot_capital_empty_and_none():
    assert spot_capital_usd({}) == 0.0
    assert spot_capital_usd(None) == 0.0
    assert spot_capital_usd({"balances": []}) == 0.0


def test_account_value_and_net_positions_basic():
    """Фиксируем поведение базовых парсеров (защитная сеть)."""
    assert account_value({}) == 0.0
    assert account_value(None) == 0.0
    st = {"assetPositions": [
        {"position": {"coin": "ETH", "szi": "-50000", "entryPx": "1700.06",
                      "leverage": {"value": "3"}, "unrealizedPnl": "453349", "positionValue": "84550000"}}
    ]}
    np = net_positions(st)
    assert np["ETH"]["szi"] == -50000.0
    assert np["ETH"]["lev"] == 3.0


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
