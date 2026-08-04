#!/usr/bin/env python3
"""Локальный сторож копира (заменяет AI-/loop присмотр — ноль токенов, всегда онлайн).

Крутится ПРЯМО НА Pi по systemd-таймеру (каждые ~15 мин), ходит в REST бота на
127.0.0.1:8787, применяет те же пороги, что делал AI-присмотр, и шлёт алерты в
Telegram через /api/notify бота. Логика детерминированная — модель не нужна.

ПОЛИТИКА: ТОЛЬКО АЛЕРТ. Скрипт НИКОГДА не трогает деньги/позиции — только читает
status/logs и постит текст в TG. Никаких start/stop/sync/panic.

Классификация (совпадает с прежним AI-лупом):
  RED    = есть орфаны (цель закрыла — мы держим); ИЛИ critical-ошибка;
           ИЛИ сервис down (для telegram — только если держится ≥2 прогонов подряд).
  YELLOW = есть check expected==reduce (держим больше лида, сокращение ждёт);
           ИЛИ warn-ошибка с count≥3.
  GREEN  = чисто.
Дедуп по сигнатуре в runtime/watchdog_state.json — шлём только на СМЕНУ состояния.

Переменные окружения (необязательные): HLC_URL (умолч. http://127.0.0.1:8787),
HLC_PASSWORD (если включена авторизация UI бота).
"""
import json
import os
import urllib.error
import urllib.request

def _bot_env(key):
    """Прочитать значение из локального .env бота (рядом, ~/hl-copier/.env).
    Секрет НЕ попадает в репозиторий/юнит — берём из уже стоящего на Pi .env."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _bot_chat_id():
    """chat_id живёт в боевом config/config.json (в .env его нет). Нужен для ПРЯМОЙ
    отправки в Telegram, когда сам бот не отвечает и /api/notify недоступен."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return str(((json.load(f) or {}).get("telegram") or {}).get("chat_id") or "")
    except Exception:
        return ""


BASE = os.environ.get("HLC_URL", "http://127.0.0.1:8787").rstrip("/")
# пароль UI: сперва явный HLC_PASSWORD, иначе UI_PASSWORD из .env бота (если авторизация включена)
PASSWORD = os.environ.get("HLC_PASSWORD") or _bot_env("UI_PASSWORD")
TG_API = os.environ.get("HLC_TG_API", "https://api.telegram.org")
BOT_DOWN_STREAK = 2   # гистерезис: рестарт сервиса (~10с) не должен рождать ложную тревогу
STATE_PATH = os.environ.get(
    "HLC_WATCH_STATE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime", "watchdog_state.json"),
)
SIZE_TOL_PCT = 15.0
_token = None


# ---------- HTTP к боту ----------
def _raw(method, path, body=None, tok=None):
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def _login():
    global _token
    if not PASSWORD:
        return None
    try:
        _, j = _raw("POST", "/api/login", {"password": PASSWORD})
        _token = j.get("token")
    except Exception:
        _token = None
    return _token


def _direct_tg(text):
    """Резервный канал: пишем в Telegram НАПРЯМУЮ, минуя бота.

    C-4: единственным каналом сторожа был сам бот (/api/notify). Если процесс лёг —
    самая страшная авария, «позиция без управления», — сторож не мог ни прочитать
    статус, ни позвать на помощь. Наблюдатель, который умирает вместе с наблюдаемым,
    бесполезен. Токен берём из .env бота, chat_id — из его config.json."""
    # env-переопределения — чтобы тесты/стенды не читали боевой .env
    token = os.environ.get("HLC_TG_TOKEN") or _bot_env("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("HLC_TG_CHAT") or _bot_chat_id()
    if not token or not chat:
        print("watchdog: нет TELEGRAM_BOT_TOKEN/chat_id — прямой канал недоступен")
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(f"{TG_API}/bot{token}/sendMessage", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception as e:
        print(f"watchdog: прямой TG не прошёл: {e}")
        return False


def _call(method, path, body=None):
    global _token
    try:
        _, j = _raw(method, path, body, _token)
        return j
    except urllib.error.HTTPError as e:
        if e.code == 401 and PASSWORD:
            if _login():
                try:
                    _, j = _raw(method, path, body, _token)
                    return j
                except Exception as e2:
                    return {"error": str(e2)}
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ---------- Чистая логика (дословно из hl-copier-mcp/server.py, чтобы совпадало) ----------
_STABLES = ("USDT", "USDC", "BUSD", "FDUSD")


def _coin_of(symbol):
    s = (symbol or "").upper()
    for suf in _STABLES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _reconcile_closes(status, logs_obj, size_tol_pct=SIZE_TOL_PCT):
    if not isinstance(status, dict) or status.get("error"):
        return {"error": (status or {}).get("error", "нет status")}

    ours = {}
    for p in status.get("positions") or []:
        coin = _coin_of(p.get("symbol"))
        q = float(p.get("qty") or 0)
        ours[coin] = ours.get(coin, 0.0) + (q if p.get("side") == "LONG" else -q)

    want = {}
    for d in status.get("desired") or []:
        coin = (d.get("coin") or "").upper()
        want[coin] = want.get(coin, 0.0) + float(d.get("size") or 0)

    skip_by = {}
    for it in status.get("skipped") or []:
        key = it[0] if isinstance(it, (list, tuple)) and it else str(it)
        reason = it[1] if isinstance(it, (list, tuple)) and len(it) > 1 else ""
        coin = _coin_of(str(key).split("/")[0])
        skip_by.setdefault(coin, []).append(reason)

    deferred = False
    for L in ((logs_obj or {}).get("logs") or [])[-150:]:
        msg = L.get("msg", "")
        if ("правок отложено" in msg) or ("auto_sync off" in msg) or ("Синхронизировать" in msg):
            deferred = True

    def _pending(reasons):
        return any(("dead-band" in r) or ("minQty" in r) or ("qty <" in r) for r in reasons)

    checks, orphans = [], []
    for coin, have in ours.items():
        if abs(have) < 1e-9:
            continue
        w = want.get(coin, 0.0)
        reasons = skip_by.get(coin, [])
        if abs(w) < 1e-9:
            pend = _pending(reasons) or deferred
            checks.append({"coin": coin, "expected": "closed", "our_qty": round(have, 6),
                           "status": "PENDING" if pend else "MISMATCH"})
            if not pend:
                orphans.append(coin)
        else:
            off = abs(have - w) / abs(w) * 100
            if off > size_tol_pct:
                over = abs(have) > abs(w)
                pend = _pending(reasons) or deferred or any("favorability" in r for r in reasons)
                checks.append({"coin": coin, "expected": "reduce" if over else "add",
                               "our_qty": round(have, 6), "want_size": round(w, 6),
                               "off_pct": round(off, 1),
                               "status": "PENDING" if pend else ("OVER" if over else "UNDER")})
                if over and not pend:
                    orphans.append(coin)
    return {"orphans_should_be_closed": orphans, "checks": checks, "deferred_sync": deferred}


def _classify_error(msg):
    m = (msg or "").lower()
    if any(c in msg for c in ("-2019", "-2018")) or "insufficient" in m or "недостаточно марж" in m:
        return "order_reject:margin", "critical"
    if any(c in msg for c in ("-1111", "-4164", "-4003")) or "minnotional" in m or "precision" in m:
        return "order_reject:filter", "critical"
    if "-2022" in msg or "reduceonly" in m or "reduce-only" in m:
        return "order_reject:reduceonly", "critical"
    if "-4061" in msg or "position side" in m or "positionside" in m:
        return "order_reject:posside", "critical"
    if "rejected" in m or ("отклон" in m and "gtx" not in m):
        return "order_reject", "critical"
    if "-1021" in msg or "recvwindow" in m or "timestamp" in m:
        return "api:timestamp", "warn"
    if "429" in msg or "rate limit" in m or "too many" in m:
        return "api:ratelimit", "warn"
    if "timeout" in m or "timed out" in m or "таймаут" in m:
        return "api:timeout", "warn"
    if "обрыв" in m or "websocket" in m or "переподключ" in m:
        return "ws_drop", "warn"
    if "exchangeinfo" in m:
        return "exchange_info", "warn"
    return "other", "warn"


def _scan_errors(status, logs_obj, limit=300):
    buckets = {}
    for L in ((logs_obj or {}).get("logs") or [])[-limit:]:
        msg, lvl = L.get("msg", "") or "", L.get("level", "")
        if lvl != "error" and "ERR" not in msg:
            continue
        if "GTX отклонён" in msg:
            continue
        typ, sev = _classify_error(msg)
        b = buckets.setdefault(typ, {"type": typ, "severity": sev, "count": 0, "sample": msg})
        b["count"] += 1
        b["sample"] = msg
    errors = sorted(buckets.values(), key=lambda x: (x["severity"] != "critical", -x["count"]))

    health = []
    if isinstance(status, dict):
        for name, s in (status.get("services") or {}).items():
            st = (s or {}).get("state")
            if st and st != "ok":
                health.append({"service": name, "state": st, "note": (s or {}).get("note")})
        if status.get("ready") and status.get("running") is False and status.get("account_type") == "copy":
            health.append({"service": "copier", "state": "stopped", "note": "running=false"})
    return {"errors": errors, "service_health": health}


# ---------- Присмотр: классификация + дедуп + алерт ----------
# Сервисы, у которых state="off" означает «не настроен осознанно», а НЕ деградацию:
# binance — не заданы ключи, monitoring — нет адресов, telegram — выключен в конфиге.
# Для copier же "off"/"stopped" = «копир стоит, позиции без управления» — это авария.
_OFF_IS_CONFIG = ("binance", "monitoring", "telegram")


def _svc_is_down(name, state):
    """Упавшим считаем ЛЮБОЙ state вне ("ok","warn") — down/off/stopped/…, а не только "down"
    (остановленный копир приходит как "off" из /api/status и "stopped" из _scan_errors —
    старый фильтр == "down" пропускал оба и рапортовал GREEN). Исключение — "off" у
    сервисов из _OFF_IS_CONFIG: там это выключено конфигом, алертить не о чем."""
    if state in ("ok", "warn"):
        return False
    if state == "off" and name in _OFF_IS_CONFIG:
        return False
    return True


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        print(f"watchdog: не смог записать state: {e}")


def _push(text):
    """Через бота, а если он молчит — напрямую в Telegram. Возвращает признак доставки."""
    r = _call("POST", "/api/notify", {"text": text})
    if isinstance(r, dict) and (r.get("ok") or r.get("queued")):
        print("watch: notify ok")
        return True
    print(f"watch: notify через бота FAIL: {str(r)[:100]} → пробую прямой TG")
    ok = _direct_tg(text)
    print(f"watch: прямой TG {'ok' if ok else 'FAIL'}")
    return ok


def _next_state(delivered, sig, level, prev_sig, prev_level, streak):
    """Что записать в state после прогона.

    Подпись двигаем ТОЛЬКО когда алерт дошёл. Иначе оставляем прежнюю: на следующем
    прогоне sig снова окажется «изменившейся» и сторож повторит попытку. Иначе упавшая
    отправка навсегда прятала бы аварию — молчание сторожа неотличимо от «всё чисто».

    tg_down_streak сохраняем всегда: это гистерезис телеграма, к доставке отношения не имеет."""
    if delivered:
        return {"sig": sig, "level": level, "tg_down_streak": streak}
    return {"sig": prev_sig, "level": prev_level, "tg_down_streak": streak}


def main():
    status = _call("GET", "/api/status")
    logs = _call("GET", "/api/logs")
    prev = _load_state()

    # ---- C-4: бот не отвечает. Раньше здесь был тихий return — авария «позиция без
    # управления» уходила в журнал, который никто не читает. Теперь зовём напрямую в TG.
    if (isinstance(status, dict) and status.get("error")) or (isinstance(logs, dict) and logs.get("error")):
        err = (status or {}).get("error") or (logs or {}).get("error")
        bstreak = int(prev.get("bot_down_streak") or 0) + 1
        alerted = bool(prev.get("bot_alerted"))
        st = dict(prev)
        st["bot_down_streak"] = bstreak
        if bstreak >= BOT_DOWN_STREAK and not alerted:
            ok = _direct_tg(
                f"🔴 Сторож: БОТ НЕ ОТВЕЧАЕТ ({BASE}) уже {bstreak} прогона подряд. "
                f"Последняя ошибка: {str(err)[:120]}. Позиции могут остаться без управления — "
                f"проверь сервис: systemctl --user status hl-copier. Сам ничего не трогаю."
            )
            st["bot_alerted"] = ok      # не доставили → на следующем прогоне попробуем снова
        _save_state(st)
        print(f"watch: BOT-DOWN streak={bstreak} ({str(err)[:60]})")
        return

    # бот отвечает: если раньше алертили о его смерти — сообщаем, что ожил
    if prev.get("bot_alerted"):
        if _push("✅ Сторож: бот снова отвечает — REST жив, продолжаю присмотр."):
            prev["bot_alerted"] = False
    prev["bot_down_streak"] = 0

    rec = _reconcile_closes(status, logs)
    if rec.get("error"):
        _save_state(prev)          # бот жив: зафиксировать сброшенный bot_down_streak
        print(f"watch: skip ({rec['error']})")
        return
    scan = _scan_errors(status, logs)

    prev_sig = sorted(prev.get("sig") or [])
    prev_level = prev.get("level", "GREEN")
    prev_streak = int(prev.get("tg_down_streak") or 0)

    orphans = rec.get("orphans_should_be_closed") or []
    reduces = [c["coin"] for c in (rec.get("checks") or []) if c.get("expected") == "reduce"]
    errors = scan.get("errors") or []
    health = scan.get("service_health") or []
    crit = [e for e in errors if e.get("severity") == "critical"]
    warns3 = [e for e in errors if e.get("severity") == "warn" and e.get("count", 0) >= 3]

    # гистерезис telegram: down учитываем только если держится ≥2 прогонов подряд
    tg_down_now = any(h.get("service") == "telegram" and _svc_is_down("telegram", h.get("state"))
                      for h in health)
    streak = prev_streak + 1 if tg_down_now else 0
    tg_effective_down = streak >= 2
    # set: «copier остановлен» может прийти дважды (off из services + stopped из _scan_errors)
    down_services = sorted({h["service"] for h in health
                            if _svc_is_down(h.get("service"), h.get("state"))
                            and (h["service"] != "telegram" or tg_effective_down)})

    # уровень
    if orphans or crit or down_services:
        level = "RED"
    elif reduces or warns3:
        level = "YELLOW"
    else:
        level = "GREEN"

    # сигнатура
    sig = sorted(
        [f"orph:{c}" for c in orphans]
        + [f"red:{c}" for c in reduces]
        + [f"err:{e['type']}" for e in crit]
        + [f"down:{s}" for s in down_services]
        + [f"warn:{e['type']}" for e in warns3]
    )

    changed = sig != prev_sig
    sub = {"order_reject": "[copy]", "api": "[copy]", "ws_drop": "[ws]", "exchange_info": "[copy]"}

    delivered = True   # слать нечего — значит и терять нечего

    if changed and level in ("RED", "YELLOW"):
        pref = "🔴" if level == "RED" else "🟡"
        parts = []
        if orphans:
            parts.append("орфаны (не закрыли): " + ", ".join(orphans))
        for e in crit:
            tag = next((v for k, v in sub.items() if e["type"].startswith(k)), "[copy]")
            parts.append(f"{tag} critical {e['type']} ×{e['count']}: {str(e.get('sample',''))[:80]}")
        if down_services:
            parts.append("сервис down: " + ", ".join(down_services))
        if reduces:
            parts.append("ждёт сокращения: " + ", ".join(reduces))
        for e in warns3:
            tag = next((v for k, v in sub.items() if e["type"].startswith(k)), "[copy]")
            parts.append(f"{tag} повтор warn {e['type']} ×{e['count']}")
        delivered = _push(f"{pref} Сторож: " + "; ".join(parts) + ". Позиции не трогаю — только сигнал.")
    elif level == "GREEN" and prev_level in ("RED", "YELLOW"):
        delivered = _push("✅ Решено: сторож — состояние снова чистое (орфанов/critical/down нет).")

    st = _next_state(delivered, sig, level, prev_sig, prev_level, streak)
    st["bot_down_streak"] = 0
    st["bot_alerted"] = bool(prev.get("bot_alerted"))   # «ожил» не доставлен → напомним позже
    _save_state(st)
    tail = "" if delivered else "  (алерт НЕ доставлен — повторим на следующем прогоне)"
    print(f"watch: {level} " + (" ".join(sig) if sig else "ok") + tail)


if __name__ == "__main__":
    main()
