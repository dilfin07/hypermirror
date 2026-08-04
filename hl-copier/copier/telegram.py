"""Telegram Bot API (stdlib): отправка алертов + приём команд (long-poll)."""
import json
import urllib.error
import urllib.parse
import urllib.request


def get_updates(token, offset=None, timeout=25):
    """Long-poll getUpdates. Возвращает список апдейтов.

    Ошибки НЕ глотает — сеть/битый JSON летят исключением, ответ ok=false поднимает
    RuntimeError. Иначе плохой токен/оборванная сеть неотличимы от «нет апдейтов»,
    и командный канал (в т.ч. PANIC с телефона) умирает молча. Логирует вызывающий
    (у этого stdlib-клиента логгера нет намеренно)."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout + 10) as r:
        d = json.loads(r.read().decode())
    if not d.get("ok"):
        raise RuntimeError(f"getUpdates ok=false: {str(d)[:200]}")
    return d.get("result", [])


def _post(url, payload):
    """POST в Bot API. На 4xx Telegram кладёт причину в ТЕЛО ответа — читаем его,
    иначе HTTPError превращается в бесполезное «HTTP Error 400: Bad Request»."""
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        # сеть/таймаут: не исключение наружу — вызывающий ждёт (ok, info), как раньше
        return {"ok": False, "description": str(e)}


def _is_parse_error(j):
    d = str((j or {}).get("description") or "").lower()
    return "parse" in d or "entities" in d or "tag" in d


def send_message(token, chat_id, text, reply_markup=None):
    """Шлём с parse_mode=HTML (сводки монитора используют <b>/<code>).

    Но в текст попадает и содержимое исключений — например «<urlopen error ...>».
    Telegram видит незакрытый тег, отвечает 400 и НЕ доставляет ничего. Раньше такое
    сообщение молча терялось. Теперь при ошибке разметки повторяем как обычный текст:
    лучше алерт без форматирования, чем недоставленный алерт."""
    if not token or not chat_id:
        return False, "нет токена или chat_id"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)

    j = _post(url, payload)
    if j.get("ok"):
        return True, j
    if _is_parse_error(j):
        payload.pop("parse_mode", None)
        j2 = _post(url, payload)
        return bool(j2.get("ok")), j2
    return False, j


def answer_callback_query(token, callback_query_id, text=""):
    """Подтвердить нажатие inline-кнопки (убрать «часики» у пользователя)."""
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    data = urllib.parse.urlencode({"callback_query_id": callback_query_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10).read()
    except Exception:
        pass
