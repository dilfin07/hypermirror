"""Telegram: отправка алертов + двусторонние команды управления (mixin для Controller).

Состояние (self.cfg, self._tg_token, self.lock, self.have_keys) живёт в Controller;
здесь только методы. Подмешивается в Controller через наследование.
"""
import json
import os
import queue
import threading
import time

from copier.config import CONFIG_DIR
from copier.secrets import write_env
from copier.telegram import send_message, get_updates, answer_callback_query


class TelegramMixin:
    TG_HELP = ("<b>hypermirror commands</b>\n"
               "/menu — control panel (buttons)\n"
               "/status — state (equity, positions, mode)\n"
               "/sync — 🔧 synchronize the position with the lead\n"
               "/live — start the copier (LIVE)\n"
               "/dry — start in dry-run (no orders)\n"
               "/stop — stop the copier\n"
               "/panic — 🚨 close everything and stop\n"
               "/restart — restart the server\n"
               "/help — command list")

    # inline-вариант (кнопки на сообщении) — оставлен для совместимости
    CONTROL_KB = {"inline_keyboard": [
        [{"text": "🔧 Synchronize", "callback_data": "sync"}],
        [{"text": "▶️ Start (LIVE)", "callback_data": "start_live"},
         {"text": "⏹ Stop", "callback_data": "stop"}],
    ]}
    # ОСНОВНОЙ пульт: постоянная reply-клавиатура над полем ввода (нажатие шлёт текст-команду)
    REPLY_KB = {"keyboard": [
        [{"text": "🔧 Synchronize"}],
        [{"text": "▶️ Start (LIVE)"}, {"text": "⏹ Stop"}],
        [{"text": "📊 Status"}, {"text": "🚨 PANIC"}],
    ], "resize_keyboard": True, "is_persistent": True}

    def _tg_send(self, text, reply_markup=None, kind="copy", ttl=None):
        """Кладёт сообщение в приоритетную очередь отправки (НЕ шлёт напрямую) — чтобы на
        бёрстах не ловить 429 и не терять важное. Реальная отправка — в _tg_sender_worker.

        kind="copy" (по умолчанию: копи-алерты/управление/статус) — приоритет, без TTL, не дропается.
        kind="monitor" (наблюдение за чужими) — после копи; с ttl сек дропается, если протух в очереди
        (мозги копира сходятся к цели независимо от монитор-алертов, поэтому стейл можно выбросить)."""
        tg = self.cfg.get("telegram") or {}
        if not tg.get("enabled") or not self._tg_token or not tg.get("chat_id"):
            return
        prio = 1 if kind == "monitor" else 0   # 0 = копи/управление вперёд, 1 = монитор после
        item = (prio, next(self._tg_seq), text, reply_markup, ttl, time.time())
        try:
            self._tg_queue.put_nowait(item)
        except queue.Full:
            self.log(f"TG DROP on enqueue (FULL={self._tg_queue.qsize()}) p{prio}: {text[:50]}", "info", tg=False)

    def notify_tg(self, text, kind="copy"):
        """Отправить произвольное сообщение в Telegram (канал для внешних ассистентов/адона).
        Уважает enabled/token; префикс instance_name если задан.
        Возвращает {ok, ...} — чтобы вызывающий (MCP) знал, ушло ли."""
        tg = self.cfg.get("telegram") or {}
        if not (tg.get("enabled") and self._tg_token and tg.get("chat_id")):
            return {"ok": False, "reason": "telegram not configured/disabled"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "reason": "empty text"}
        name = self.cfg.get("instance_name")
        if name:
            text = f"[{name}] {text}"
        self._tg_send(text[:3900], kind=("monitor" if kind == "monitor" else "copy"))
        return {"ok": True, "queued": True}

    def _tg_sender_worker(self):
        """Единый отправитель: лимит ~1 сообщение/сек на чат + ретрай на 429 (Retry-After).
        Приоритет: копи/управление вперёд монитора. Протухший монитор-алерт (ttl истёк в
        очереди) выбрасывается без отправки — чтобы не доставлять стейл и не копить хвост.

        ЖИВУЧЕСТЬ: это ЕДИНСТВЕННЫЙ поток доставки, рестартера нет — поэтому тело итерации
        целиком под try. Любое исключение (битый item, конфиг, арифметика TTL) теряет одно
        сообщение, но НЕ убивает поток (уже случалось: float(None) в TTL → бот торговал,
        а в TG была тишина до рестарта). task_done() — ровно один на каждый get()."""
        import re
        import traceback
        while True:
            try:
                item = self._tg_queue.get()
            except Exception:                          # практически невозможно, но поток должен жить
                time.sleep(1.0)
                continue
            try:
                prio, seq, text, markup, ttl, enq_ts = item
                tg = self.cfg.get("telegram") or {}
                chat = tg.get("chat_id")
                if not (self._tg_token and chat):
                    self.log("TG: no token/chat_id → message NOT sent", "info", tg=False)
                    continue
                if ttl and (time.time() - enq_ts) > ttl:   # протухло в очереди → дроп (не шлём, не ждём 1.1с)
                    self.log(f"TG: dropped by TTL ({ttl:g}s, waited {time.time()-enq_ts:.0f}s): {text[:60]}", "info", tg=False)
                    continue
                ok, info = False, ""
                for attempt in range(4):
                    try:
                        ok, info = send_message(self._tg_token, chat, text, reply_markup=markup)
                    except Exception as e:
                        ok, info = False, str(e)
                    if ok:
                        break
                    wait = 2.0 * (attempt + 1)
                    mt = re.search(r"retry_after\D+(\d+)", str(info))   # Telegram 429: respect Retry-After
                    if mt:
                        wait = int(mt.group(1)) + 1
                    time.sleep(min(wait, 30))
                if ok:
                    self._tg_ok_ts = time.time()          # health: последняя успешная отправка
                else:                                     # лог только на неудаче (код ошибки Telegram)
                    self._tg_fail = {"ts": time.time(), "err": str(info)[:120]}
                    self.log(f"TG send FAIL p{prio} (queue {self._tg_queue.qsize()}): {str(info)[:180]}", "info", tg=False)
                time.sleep(1.1)            # базовый интервал (лимит Telegram ~1/сек на чат)
            except Exception:
                try:                       # tg=False: не пытаться слать через сломанный же пайплайн
                    self.log(f"[tg] sender: iteration crashed (message lost, thread alive): "
                             f"{traceback.format_exc()[-400:]}", "error", tg=False)
                except Exception:
                    pass                   # даже сбой логгера не должен убить доставку
                time.sleep(1.0)            # не крутиться в горячем цикле при систематическом сбое
            finally:
                self._tg_queue.task_done()

    def _tg_status_text(self):
        s = self.get_status()
        pos = ", ".join(f"{p['symbol']} {p['side']} ({p['roi']}%)" for p in s.get("positions", [])) or "none"
        sync = "on" if self.cfg.get("auto_sync", False) else "off (manual via button)"
        return (f"<b>Status</b>\nmode: {'🔴 LIVE' if s.get('live') else '🟢 DRY'} · "
                f"{'RUNNING' if s.get('running') else 'STOPPED'} · {s.get('data_mode')}\n"
                f"auto-sync: {sync}\nequity: ${s.get('equity')}\npositions: {pos}")

    # подтверждение синхры (inline, на сообщении-превью)
    SYNC_CONFIRM_KB = {"inline_keyboard": [[
        {"text": "✅ Apply", "callback_data": "sync_go"},
        {"text": "✖️ Cancel", "callback_data": "sync_cancel"}]]}

    def _tg_panel(self):
        """Пульт управления: статус + постоянная reply-клавиатура."""
        self._tg_send(self._tg_status_text(), reply_markup=self.REPLY_KB)

    def _tg_sync_preview(self):
        """Показать, что сделает синхра, с кнопками ✅ Apply / ✖️ Cancel."""
        r = self.sync_preview()
        if r.get("error"):
            self._tg_send(f"⚠️ {r['error']}")
            return
        items = r.get("items") or []
        if not items:
            extra = f" · catch-ups cut: {r['fav_skipped']}" if r.get("fav_skipped") else ""
            self._tg_send(f"✅ Position already synced with the lead{extra}")
            return
        # ключи = значения _order_action (Opened/Added/Reduced/Closed)
        ACT = {"Opened": "Open", "Added": "➕ Add", "Reduced": "➖ Reduce", "Closed": "Close"}
        lines = ["🔧 <b>Sync preview</b>", "Will converge the position to the lead:"]
        for it in items[:12]:
            dev = it.get("dev_pct")
            ds = f" · price vs entry {dev:+.2f}%" if dev is not None else ""
            lines.append(f"• {ACT.get(it['action'], it['action'])} {it['symbol']} {it['side']} "
                         f"{it['qty']:g} (~${it['notional']:,.0f}){ds}")
        if len(items) > 12:
            lines.append(f"…and {len(items) - 12} more")
        if r.get("fav_skipped"):
            lines.append(f"🛡 cut by favorability: {r['fav_skipped']} catch-ups (price worse than lead entry)")
        lines.append("\nApply?")
        self._tg_send("\n".join(lines), reply_markup=self.SYNC_CONFIRM_KB)

    # ---------- управление ботом из Telegram (long-poll команд) ----------
    TG_CMD_ALARM_STREAK = 8       # столько подряд-фейлов getUpdates → тревога владельцу
    TG_CMD_ERR_LOG_SEC = 300      # троттл error-логов канала команд (цикл ходит каждые ~25с)

    def _telegram_command_worker(self):
        offset = None
        fail_streak = 0      # подряд-фейлы getUpdates: если канал мёртв — PANIC с телефона не работает
        err_log_ts = 0.0     # троттл: не спамить лог на каждом 25-секундном цикле
        while True:
            tg = self.cfg.get("telegram") or {}
            if not (tg.get("enabled") and self._tg_token and tg.get("chat_id")):
                time.sleep(5)
                continue
            try:
                updates = get_updates(self._tg_token, offset, timeout=25)
            except Exception as e:
                fail_streak += 1
                if time.time() - err_log_ts > self.TG_CMD_ERR_LOG_SEC:
                    err_log_ts = time.time()
                    self.log(f"[tg] command channel: getUpdates failed ×{fail_streak}: "
                             f"{type(e).__name__}: {e}", "error", tg=False)
                if fail_streak == self.TG_CMD_ALARM_STREAK:
                    # тревога через канал ОТПРАВКИ: он независим от getUpdates и может быть жив
                    self._tg_send("⚠️ Telegram command channel is not responding: phone buttons and "
                                  "/panic may not work. Use the web UI to control the bot.")
                time.sleep(3)
                continue
            if fail_streak >= self.TG_CMD_ALARM_STREAK:   # канал ожил после тревоги — сказать об этом
                self._tg_send("✅ Telegram command channel is working again")
            fail_streak = 0
            for u in updates:
                if not isinstance(u, dict) or u.get("update_id") is None:
                    continue                              # битый апдейт без id: offset не сдвинуть — пропуск
                offset = u["update_id"] + 1
                cq = u.get("callback_query")
                if cq:                                   # нажата inline-кнопка пульта
                    chat = str(((cq.get("message") or {}).get("chat") or {}).get("id"))
                    if chat != str(tg.get("chat_id")):
                        continue
                    try:
                        toast = self._handle_tg_callback(cq.get("data") or "")
                    except Exception as e:
                        toast = f"error: {e}"
                    answer_callback_query(self._tg_token, cq["id"], str(toast)[:180])
                    continue
                msg = u.get("message") or {}
                chat = str((msg.get("chat") or {}).get("id"))
                text = (msg.get("text") or "").strip()
                if chat != str(tg.get("chat_id")) or not text:
                    continue   # только авторизованный чат
                try:
                    self._handle_tg_command(text)
                except Exception as e:
                    self._tg_send(f"❌ command error: {e}")

    def _handle_tg_callback(self, data):
        """Действие по нажатию inline-кнопки. Возвращает короткий текст для всплывашки."""
        if data == "sync":                      # из inline-пульта → показать превью
            self._tg_sync_preview()
            return "🔧 Preview"
        if data == "sync_go":                   # подтверждение применения синхры
            r = self.sync_now()
            txt = "🔧 Sync started" if r.get("ok") else f"⚠️ {r.get('error')}"
            self._tg_send(txt)
            return txt
        if data == "sync_cancel":
            self._tg_send("✖️ Sync cancelled")
            return "cancelled"
        if data == "start_live":
            self.start(True, self.data_mode)
            self._tg_send("🔴 Copier started (LIVE)")
            return "started"
        if data == "stop":
            self.stop()
            self._tg_send("⏹ Copier stopped")
            return "stopped"
        return "unknown button"

    def _handle_tg_command(self, text):
        low = text.lower()
        # нажатия reply-клавиатуры (подпись = присланный текст) → команда по ключевому слову.
        # Матчим АНГЛИЙСКИЕ подписи кнопок; слэш-команды падают в else и разбираются ниже.
        if "synchron" in low or "sync" in low:
            cmd = "sync"
        elif "start" in low:
            cmd = "live"
        elif "stop" in low:
            cmd = "stop"
        elif "panic" in low:
            cmd = "panic"
        elif "status" in low:
            cmd = "status"
        elif "menu" in low:
            cmd = "menu"
        else:
            cmd = low.split()[0].lstrip("/")
        if cmd in ("menu", "panel", "start"):
            self._tg_panel()
        elif cmd in ("status",):
            self._tg_send(self._tg_status_text(), reply_markup=self.REPLY_KB)
        elif cmd in ("sync",):
            self._tg_sync_preview()
        elif cmd in ("live", "copier"):
            self.start(True, self.data_mode)
            self._tg_send("🔴 Copier started (LIVE)")
        elif cmd == "dry":
            self.start(False, self.data_mode)
            self._tg_send("🟢 Copier started (DRY-RUN)")
        elif cmd in ("stop",):
            self.stop()
            self._tg_send("⏹ Copier stopped")
        elif cmd == "panic":
            r = self.panic()
            self._tg_send(f"🚨 PANIC: closed {len(r.get('closed', []))}, bot stopped")
        elif cmd in ("restart",):
            self._tg_send("♻️ Restarting the server…")
            threading.Thread(target=self._restart, daemon=True).start()
        else:
            self._tg_send(self.TG_HELP)

    def _restart(self):
        import sys
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ---------- настройки Telegram ----------
    def set_telegram(self, token, chat_id, enabled):
        if token:
            write_env({"TELEGRAM_BOT_TOKEN": token})
        with self.lock:
            self._set_global("telegram", {"enabled": bool(enabled), "chat_id": (chat_id or "").strip()})
        self._reload()
        self.log("Telegram settings updated", "info")
        return {"telegram": {"enabled": (self.cfg.get("telegram") or {}).get("enabled"),
                             "chat_id": (self.cfg.get("telegram") or {}).get("chat_id"),
                             "has_token": bool(self._tg_token)}}

    def test_telegram(self):
        tg = self.cfg.get("telegram") or {}
        ok, info = send_message(self._tg_token, tg.get("chat_id"),
                                "✅ hypermirror test: alerts connected")
        if not ok:
            self.log(f"[tg] test failed: {info}", "error")
        return {"ok": ok, "info": str(info)[:200]}
