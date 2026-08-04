"""Read-only клиент Hyperliquid Info API через REST-поллинг (только stdlib).

Глобальный троттл + ретрай на 429: HL Info лимитирован по IP (~весовой бюджет в минуту).
Бёрсты (напр. подгрузка карточек аудита) забивали лимит и роняли обычные status-запросы
с HTTP 429. Все запросы идут через один HLInfo (controller.hl), поэтому пейсим их в одном
месте: не чаще _MIN_INTERVAL между отправками, а на 429 — экспоненциальный бэкофф с повтором.
"""
import json
import threading
import time
import urllib.request
import urllib.error

MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"

_MIN_INTERVAL = 0.15   # сек между отправками запросов (~6–7/сек, под лимитом HL ~600/мин)
_RETRIES = 4           # повторов на 429
_throttle_lock = threading.Lock()
_last_send = 0.0


def _pace():
    """Разносим отправки во времени (общий пейсер для всех запросов)."""
    global _last_send
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        _last_send = time.monotonic()


class HLInfo:
    def __init__(self, base=MAINNET, timeout=15):
        self.url = base + "/info"
        self.timeout = timeout

    def post(self, payload):
        data = json.dumps(payload).encode()
        for attempt in range(_RETRIES + 1):
            _pace()
            req = urllib.request.Request(
                self.url, data=data, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < _RETRIES:
                    time.sleep(0.5 * (2 ** attempt))   # 0.5 → 1 → 2 → 4 сек
                    continue
                raise RuntimeError(f"HL Info request failed: {e}") from e
            except urllib.error.URLError as e:
                raise RuntimeError(f"HL Info request failed: {e}") from e

    def meta(self):
        return self.post({"type": "meta"})

    def all_mids(self):
        return self.post({"type": "allMids"})

    def clearinghouse_state(self, user, dex=None):
        """dex=None → дефолтный перп-dex; dex='xyz'/… → builder-deployed перп-dex (HIP-3)."""
        payload = {"type": "clearinghouseState", "user": user}
        if dex:
            payload["dex"] = dex
        return self.post(payload)

    def perp_dexs(self):
        """Список builder-deployed перп-dexs (HIP-3). Первый элемент обычно None (дефолтный)."""
        return [d.get("name") for d in (self.post({"type": "perpDexs"}) or []) if d and d.get("name")]

    def spot_clearinghouse_state(self, user):
        return self.post({"type": "spotClearinghouseState", "user": user})

    def portfolio(self, user):
        return self.post({"type": "portfolio", "user": user})

    def user_fills(self, user):
        return self.post({"type": "userFills", "user": user})

    def open_orders(self, user):
        return self.post({"type": "frontendOpenOrders", "user": user})
