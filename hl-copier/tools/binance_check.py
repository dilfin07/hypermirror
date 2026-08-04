"""Проверка подключения к Binance: публичный ping + (если есть ключи) баланс/позиции.

    python3 tools/binance_check.py
Сеть берётся из config (binance.network). Ключи — из .env (BINANCE_API_KEY/SECRET).
"""
import _bootstrap  # noqa: F401

from copier.config import load_config
from copier.secrets import binance_keys
from copier.execution.binance import BinanceFutures, symbol_filters, SYMBOL_MAP


def main():
    cfg = load_config()
    net = (cfg.get("binance") or {}).get("network", "testnet")
    key, secret = binance_keys()
    cli = BinanceFutures(key, secret, network=net)

    print(f"Binance Futures: сеть = {net}  ({cli.base})")
    try:
        cli.ping()
        print("✅ ping ок (публичный доступ есть)")
    except Exception as e:
        print(f"❌ ping: {e}"); return

    try:
        info = cli.exchange_info()
        filt = symbol_filters(info)
        have = [s for s in SYMBOL_MAP.values() if s in filt]
        print(f"✅ exchangeInfo: {len(info.get('symbols', []))} символов; "
              f"наши доступны: {', '.join(have)}")
        if "BTCUSDT" in filt:
            f = filt["BTCUSDT"]
            print(f"   BTCUSDT: stepSize {f['stepSize']}, minQty {f['minQty']}, minNotional ${f['minNotional']:.0f}")
    except Exception as e:
        print(f"❌ exchangeInfo: {e}")

    if not key or not secret:
        print("\nℹ️  Ключи не заданы (.env пуст). Публичная часть работает; "
              "для баланса/позиций добавь BINANCE_API_KEY и BINANCE_API_SECRET в hl-copier/.env")
        return

    try:
        eq = cli.equity()
        print(f"\n✅ ПОДПИСАННЫЙ доступ ок. Эквити (totalMarginBalance): ${eq:,.2f}")
        pos = cli.positions()
        if pos:
            print("   Текущие позиции:")
            for s, a in pos.items():
                print(f"     {s}: {a:+g}")
        else:
            print("   Открытых позиций нет.")
    except Exception as e:
        print(f"❌ подписанный запрос: {e}")
        print("   Подсказки: проверь права ключа (Enable Futures), сеть (testnet/mainnet),")
        print("   и что ключ от той же сети. Ошибка -1021 = рассинхрон часов.")


if __name__ == "__main__":
    main()
