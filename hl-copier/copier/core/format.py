"""Хелперы форматирования для вывода в консоль."""
from datetime import datetime, timezone


def fmt_usd(x):
    a = abs(x)
    if a >= 1e6:
        s = f"${a/1e6:.2f}M"
    elif a >= 1e3:
        s = f"${a/1e3:.1f}k"
    else:
        s = f"${a:.0f}"
    return ("-" if x < 0 else "") + s


def fmt_qty(x):
    return f"{x:,.4f}".rstrip("0").rstrip(".")


def hhmmss(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%H:%M:%S")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
