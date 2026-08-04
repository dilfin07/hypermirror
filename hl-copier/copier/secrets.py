"""Чтение секретов из .env (или переменных окружения). Ключи НИКОГДА не в config."""
import os

from .config import PROJECT_ROOT, atomic_write


def _read_env_file():
    path = os.environ.get("HLC_ENV_FILE") or os.path.join(PROJECT_ROOT, ".env")
    vals = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def get(name, default=""):
    return os.environ.get(name) or _read_env_file().get(name, default)


def write_env(updates):
    """Обновить .env, СОХРАНЯЯ существующие ключи (не затирать)."""
    path = os.environ.get("HLC_ENV_FILE") or os.path.join(PROJECT_ROOT, ".env")
    cur = _read_env_file()
    for k, v in updates.items():
        if v is not None:
            cur[k] = v
    atomic_write(path, "".join(f"{k}={v}\n" for k, v in cur.items()))


def binance_keys(prefix="BINANCE"):
    """Ключи Binance по префиксу профиля счёта. main=BINANCE_API_KEY/SECRET;
    копи-портфель/доп.счёт — напр. BINANCE_COPY_X_API_KEY/SECRET. Только в .env."""
    p = prefix or "BINANCE"
    return get(f"{p}_API_KEY"), get(f"{p}_API_SECRET")


def telegram_token():
    return get("TELEGRAM_BOT_TOKEN")
