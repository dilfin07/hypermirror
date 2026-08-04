"""MCP-сервер для HL→Binance Copier.

Тонкий клиент к REST бота (по умолчанию http://127.0.0.1:8787). Не импортирует код
бота — общается по HTTP, поэтому работает независимо и переживает рестарты бота.

Даёт AI-клиенту (Claude/ChatGPT) инструменты: смотреть состояние/позиции/аудит/монитор/
историю и (при желании) управлять — старт/стоп/паника/цель копирования.

Запуск (обычно дёргается Claude по конфигу): .venv/bin/python server.py
Переменные окружения: HLC_URL (адрес бота), HLC_PASSWORD (если включена авторизация UI).
"""
import json
import os
import urllib.request

from mcp.server.fastmcp import FastMCP


def _load_dotenv():
    """Подхватить .env рядом с этим файлом, не затирая уже заданные переменные."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

BASE = os.environ.get("HLC_URL", "http://127.0.0.1:8787").rstrip("/")
PASSWORD = os.environ.get("HLC_PASSWORD", "")
_token = None

mcp = FastMCP("hl-copier")


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


def _call(method, path, body=None):
    global _token
    try:
        st, j = _raw(method, path, body, _token)
        return j
    except urllib.error.HTTPError as e:  # 401 → перелогин и повтор
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


import urllib.error  # noqa: E402


# ---------- ВЕРИФИКАЦИЯ ЗАКРЫТИЙ (чистая логика, без сети) ----------
_STABLES = ("USDT", "USDC", "BUSD", "FDUSD")


def _coin_of(symbol):
    """BTCUSDT -> BTC (снять стейбл-суффикс)."""
    s = (symbol or "").upper()
    for suf in _STABLES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _reconcile_closes(status, logs_obj, size_tol_pct=15.0, verbose=False):
    """Сверка нашей стороны с desired (уже выведенным из лида): ловит «орфанов»
    (цель закрыла — мы держим), рассинхрон размера, свежие ошибки и close-события.

    Чистая функция — принимает ответы /api/status и /api/logs, возвращает сводку.
    verdict: attention (орфан/ошибка) | review (есть расхождения) | clean.
    """
    if not isinstance(status, dict) or status.get("error"):
        return {"error": (status or {}).get("error", "нет status")}

    ours = {}                                   # coin -> signed qty (наши позиции)
    for p in status.get("positions") or []:
        coin = _coin_of(p.get("symbol"))
        q = float(p.get("qty") or 0)
        ours[coin] = ours.get(coin, 0.0) + (q if p.get("side") == "LONG" else -q)

    want = {}                                   # coin -> signed size (desired = из лида)
    for d in status.get("desired") or []:
        coin = (d.get("coin") or "").upper()
        want[coin] = want.get(coin, 0.0) + float(d.get("size") or 0)

    skip_by = {}                                # coin -> [причины пропуска]
    for it in status.get("skipped") or []:
        key = it[0] if isinstance(it, (list, tuple)) and it else str(it)
        reason = it[1] if isinstance(it, (list, tuple)) and len(it) > 1 else ""
        coin = _coin_of(str(key).split("/")[0])
        skip_by.setdefault(coin, []).append(reason)

    # логи: свежие ошибки, close-события и флаг «догон отложен» (auto_sync off)
    events, errors, deferred = [], [], False
    for L in ((logs_obj or {}).get("logs") or [])[-150:]:
        msg, lvl = L.get("msg", ""), L.get("level", "")
        if lvl == "error":
            errors.append({"ts": L.get("ts"), "msg": msg})
        elif ("ЗАКРЫЛ" in msg or "СОКРАТИЛ" in msg) and lvl in ("monitor", "trade", "info"):
            events.append({"ts": L.get("ts"), "level": lvl, "msg": msg})
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
        if abs(w) < 1e-9:                        # цель закрыла → мы должны быть в нуле
            pend = _pending(reasons) or deferred
            checks.append({"coin": coin, "expected": "closed", "our_qty": round(have, 6),
                           "status": "PENDING (пыль/dead-band/sync)" if pend else "MISMATCH — держим, а цель закрыла",
                           "skip": reasons})
            if not pend:
                orphans.append(coin)            # ← реальный провал закрытия
        else:                                   # оба держат → проверка размера
            off = abs(have - w) / abs(w) * 100
            if off > size_tol_pct:
                over = abs(have) > abs(w)        # держим БОЛЬШЕ желаемого → надо сократить (близко к выходу)
                pend = _pending(reasons) or deferred or any("favorability" in r for r in reasons)
                if over and not pend:
                    kind = "OVER — не сократили (нужен REDUCE)"
                elif not over and not pend:
                    kind = "UNDER — недонабор (нужен долив)"
                else:
                    kind = "PENDING (гейт/накопление/sync)"
                checks.append({"coin": coin, "expected": "reduce" if over else "add",
                               "our_qty": round(have, 6), "want_size": round(w, 6),
                               "off_pct": round(off, 1), "status": kind, "skip": reasons})
                if over and not pend:
                    orphans.append(coin)        # перебор без причины = не отработавшее сокращение

    to_open = [c for c, w in want.items() if abs(w) > 1e-9 and abs(ours.get(c, 0.0)) < 1e-9]

    # известно-отложенные (PENDING) расхождения — норма (напр. недонабор при auto_sync off),
    # их не поднимаем в review. review — только реальные не-pending расхождения.
    hard = [c for c in checks if not str(c.get("status", "")).startswith("PENDING")]
    verdict = ("attention" if (orphans or errors)
               else "review" if hard
               else "pending" if checks
               else "clean")
    out = {
        "verdict": verdict,
        "active_account": status.get("active_account"),
        "account_type": status.get("account_type"),
        "copying": [t.get("label") for t in (status.get("targets") or [])],
        "orphans_should_be_closed": orphans,     # ГЛАВНЫЙ сигнал: должны были сократить/закрыть, но держим (не pending)
        "deferred_sync": deferred,               # auto_sync off → расхождения ждут ручного Sync (это норма)
        "checks": checks,
        "to_open": to_open,                      # desired есть, у нас нет (это вход, не выход)
        "recent_errors": errors[-10:],
        "hint": "orphans (не pending) → сокращение/закрытие НЕ отработало: смотри recent_errors и skip. "
                "deferred_sync=true → расхождения ждут ручного Sync (auto_sync off), это ожидаемо.",
    }
    # recent_close_events тяжёлые и для алертинга не нужны — по умолчанию отдаём только счётчик.
    # verbose=True → полный список (для ручного разбора).
    if verbose:
        out["recent_close_events"] = events[-15:]
    else:
        out["close_events_count"] = len(events)
    return out


def _classify_error(msg):
    """(тип, severity) по тексту ошибки. critical — денежное (ордер/сервис отвалились),
    warn — обычно ретраится (api/сеть/ws)."""
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
    if "http " in m:
        return "http", "warn"
    return "other", "warn"


def _scan_errors(status, logs_obj, limit=300):
    """Скан ошибок/деградаций: классификация + дедуп по типу + отвал сервисов из status.
    verdict: attention (critical-ошибка/сервис down) | review (есть warn-ошибки) | clean."""
    buckets = {}
    for L in ((logs_obj or {}).get("logs") or [])[-limit:]:
        msg, lvl = L.get("msg", "") or "", L.get("level", "")
        if lvl != "error" and "ERR" not in msg:
            continue
        if "GTX отклонён" in msg:               # нормальный maker-repost (переставляем), не ошибка
            continue
        typ, sev = _classify_error(msg)
        b = buckets.setdefault(typ, {"type": typ, "severity": sev, "count": 0, "last_ts": None, "sample": msg})
        b["count"] += 1
        b["last_ts"] = L.get("ts")
        b["sample"] = msg
    errors = sorted(buckets.values(), key=lambda x: (x["severity"] != "critical", -x["count"]))

    health = []                                 # деградации из status.services
    if isinstance(status, dict):
        for name, s in (status.get("services") or {}).items():
            st = (s or {}).get("state")
            if st and st != "ok":
                health.append({"service": name, "state": st, "note": (s or {}).get("note")})
        if status.get("ready") and status.get("running") is False and status.get("account_type") == "copy":
            health.append({"service": "copier", "state": "stopped", "note": "running=false"})

    # TG-pipeline health (из status.services.telegram) — доставка алертов
    tg = (status.get("services") or {}).get("telegram") if isinstance(status, dict) else None
    total_err = sum(e["count"] for e in errors)

    crit = any(e["severity"] == "critical" for e in errors)
    down = any(h.get("state") == "down" for h in health)      # сервис реально упал
    warn_svc = any(h.get("state") == "warn" for h in health)  # транзиентная деградация (напр. reset TG)
    verdict = ("attention" if (crit or down)
               else "review" if (errors or warn_svc)
               else "clean")
    return {
        "verdict": verdict,
        "errors": errors,                       # сгруппировано по типу: {type, severity, count, last_ts, sample}
        "errors_total_in_window": total_err,    # всего error-записей в окне логов
        "service_health": health,               # сервисы в состоянии != ok (вкл. telegram-доставку)
        "tg_pipeline": tg,                      # {state, queue, last_ok_sec, last_fail} — здоровье доставки в TG
        "hint": "critical = ордер/сервис отвалились (деньги) → разбирать. warn = api/ws/таймаут "
                "(обычно авто-ретрай) → тревога только если count растёт/повторяется. "
                "tg_pipeline.state=down/warn или queue растёт / last_ok_sec большой → алерты не доходят. "
                "error-логи помечены подсистемой: [mon]/[copy]/[tg]/[ws].",
    }


# ---------- READ-ONLY ----------
@mcp.tool()
def status() -> dict:
    """Состояние бота: эквити, открытые позиции (с ROI), режим LIVE/DRY, опрос/сокет, running, на связи."""
    return _call("GET", "/api/status")


@mcp.tool()
def account_stats() -> dict:
    """Статистика аккаунта Binance: нереализованный PnL, плечо аккаунта, использование маржи, PnL за год."""
    return _call("GET", "/api/account_stats")


@mcp.tool()
def monitors() -> dict:
    """Список наблюдаемых адресов с их позициями и флагом copying."""
    return _call("GET", "/api/monitors")


@mcp.tool()
def position_history() -> dict:
    """История закрытых позиций на Binance (вход/выход/длительность/чистый PnL)."""
    return _call("GET", "/api/position_history")


@mcp.tool()
def fills() -> dict:
    """Последние исполнения на Binance с пометкой бот/ручное."""
    return _call("GET", "/api/fills")


@mcp.tool()
def logs() -> dict:
    """Лог бота: действия (trade), пропуски (skip), ошибки, активность целей/мониторов, heartbeat."""
    return _call("GET", "/api/logs")


@mcp.tool()
def verify_close(verbose: bool = False) -> dict:
    """Проверка КОРРЕКТНОСТИ ЗАКРЫТИЙ/СОКРАЩЕНИЙ. Сверяет наши позиции с desired (уже
    выведенным из лида): ловит «орфанов» (цель закрыла — мы держим), рассинхрон размера,
    свежие ошибки и close-события. verdict: attention (орфан/ошибка) | review | clean.
    Дёргать после того, как лид сократил/закрыл позицию — чтобы убедиться, что бот отработал.
    verbose=False (по умолчанию) — лёгкий вывод: вместо списка close-событий только
    close_events_count (экономит токены для автоприсмотра). verbose=True — полный список."""
    status = _call("GET", "/api/status")
    if isinstance(status, dict) and status.get("error"):
        return {"error": status["error"]}
    return _reconcile_closes(status, _call("GET", "/api/logs"), verbose=verbose)


@mcp.tool()
def check_errors() -> dict:
    """Скан ОШИБОК и деградаций бота: классифицирует ошибки из лога по типу/severity
    (order_reject/api/ws/timeout…), дедупит с count+last_ts, ловит отвал сервисов из статуса.
    verdict: attention (critical/сервис down) | review (warn-ошибки) | clean.
    Общая проверка «а нет ли ошибок» — дёргать периодически или после сомнительного момента."""
    return _scan_errors(_call("GET", "/api/status"), _call("GET", "/api/logs"))


@mcp.tool()
def notify_tg(text: str) -> dict:
    """Отправить сообщение в Telegram бота (мой канал наружу). Использовать, чтобы
    прислать пользователю классифицированный вердикт: что за ошибка/сделка/закрытие,
    было ли что-то предпринято (авто-ретрай/восстановление), нужно ли вмешательство.
    Возвращает {ok} — ушло ли (telegram должен быть включён в настройках бота)."""
    return _call("POST", "/api/notify", {"text": text})


# ---------- CONTROL (двигают реальные деньги — использовать осознанно) ----------
@mcp.tool()
def start_copy(live: bool = False) -> dict:
    """Запустить копир. live=False — dry-run (без ордеров), live=True — БОЕВОЙ режим."""
    return _call("POST", "/api/start", {"live": bool(live), "mode": "ws"})


@mcp.tool()
def stop_copy() -> dict:
    """Остановить копир."""
    return _call("POST", "/api/stop", {})


@mcp.tool()
def panic() -> dict:
    """🚨 PANIC: закрыть ВСЕ позиции на Binance и остановить бота."""
    return _call("POST", "/api/panic", {})


@mcp.tool()
def set_copy_target(address: str) -> dict:
    """Сделать адрес единственной целью копирования (замыкает монитор↔копир)."""
    return _call("POST", "/api/copy_set", {"address": address})


if __name__ == "__main__":
    mcp.run()
