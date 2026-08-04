"""Журнал копирования (mixin для Controller): сессии копирования как сущность —
кого копировали, когда, в каком режиме (LIVE / бумажный DRY) и что вышло.

Сессия открывается на start() при наличии цели, закрывается на stop/clear/panic/смене цели.
- LIVE: realized PnL атрибутируется из bn.income за окно сессии (счёт-уровневый — раз
  копируем одну цель за раз, окно ≈ результат сессии; ручные сделки помечаются отдельно).
- DRY (бумажный): симулятор mark-to-market по НАМЕРЕННЫМ позициям (_paper_tick) — без
  реальных ордеров, цены берём из HL mids, поэтому работает и без ключей Binance.
- Ф0: при пустом журнале реконструируем прошлые сессии из runtime/log.jsonl (best-effort).

Состояние (self._sessions, self._cur_session) живёт в Controller. См. docs/MONITOR-AUDIT.md.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

from copier.config import runtime_path, atomic_write_json
from copier.core.format import now_iso


def _ms_now():
    return int(time.time() * 1000)


def _iso_ms(ts):
    try:
        return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return 0


class JournalMixin:
    # ---------- персист ----------
    def _journal_path(self):
        return runtime_path("copy_sessions.json")

    def _load_sessions(self):
        self._sessions = []
        self._cur_session = None
        self._paper_save_ts = 0
        p = self._journal_path()
        if os.path.exists(p):
            try:
                self._sessions = json.load(open(p))
            except Exception:
                self._sessions = []
        # подобрать висящую открытую сессию (например после рестарта процесса)
        for s in self._sessions:
            if not s.get("ended"):
                self._cur_session = s
        if not self._sessions:
            try:
                rec = self._reconstruct_sessions()
                if rec:
                    self._sessions = rec
                    self.log(f"📒 journal: restored {len(rec)} past sessions from logs", "info", tg=False)
                    self._save_sessions()
            except Exception as e:
                self.log(f"journal: reconstruction failed: {e}", "error", tg=False)

    def _save_sessions(self):
        try:
            atomic_write_json(self._journal_path(), self._sessions, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ---------- жизненный цикл ----------
    def _journal_on_start(self):
        """Вызывается из start() при переходе not-running -> running."""
        tgt = (self.cfg.get("targets") or [])
        if not tgt:
            return
        t = tgt[0]
        name = t.get("label") or t["address"][:10]
        mode = "live" if self.live else "dry"
        cur = self._cur_session
        # уже идёт сессия по той же цели — не плодим (например toggle dry->live делает _journal_on_toggle)
        if cur and not cur.get("ended") and cur.get("target") == t["address"]:
            return
        self._open_session(t["address"], name, mode)

    def _journal_on_toggle(self):
        """Вызывается из start() когда running уже True и меняется LIVE/DRY."""
        s = self._cur_session
        if not s or s.get("ended"):
            return
        new = "live" if self.live else "dry"
        if s.get("mode") != new:
            s["mode"] = "mixed"
            s["paper"] = False           # тронули live — больше не «чистый бумажный»
            self._save_sessions()

    def _open_session(self, target, name, mode):
        if self._cur_session and not self._cur_session.get("ended"):
            self._close_session("superseded")
        eq = None
        if self.have_keys:
            try:
                eq = float(self.bn.account().get("totalMarginBalance", 0) or 0)
            except Exception:
                eq = None
        if eq is None:
            eq = float(self.cfg.get("paper_equity_usd", 1000))
        s = {
            "id": _ms_now(), "target": target, "name": name,
            "mode": mode, "paper": (mode == "dry"), "data_mode": self.data_mode,
            "started": now_iso(), "started_ms": _ms_now(),
            "ended": None, "ended_ms": None, "end_reason": None,
            "start_equity": round(eq, 2),
            "realized": None, "funding": 0.0, "commission": 0.0, "net": None,
            "trades": 0, "coins": [],
            # бумажные поля
            "paper_book": {}, "paper_realized": 0.0, "paper_upnl": 0.0,
            "paper_equity": round(eq, 2), "paper_roi": 0.0,
        }
        self._cur_session = s
        self._sessions.append(s)
        self._save_sessions()
        self.log(f"📒 copier session opened: {name} ({mode.upper()})", "info", tg=False)

    def _close_session(self, reason):
        s = self._cur_session
        if not s or s.get("ended"):
            return
        s["ended"] = now_iso()
        s["ended_ms"] = _ms_now()
        s["end_reason"] = reason
        if s.get("mode") == "dry":
            s["realized"] = round(s.get("paper_realized", 0.0), 4)
            s["net"] = round(s.get("paper_realized", 0.0) + s.get("paper_upnl", 0.0), 4)
        else:
            self._fill_live_pnl(s)
        self._save_sessions()
        self._cur_session = None
        self.log(f"📕 copier session closed: {s['name']} ({reason})", "info", tg=False)

    def _restamp_last_reason(self, reason):
        """Переименовать причину последней закрытой сессии (для clear/panic, которые зовут stop())."""
        if self._sessions and self._sessions[-1].get("ended"):
            self._sessions[-1]["end_reason"] = reason
            self._save_sessions()

    # ---------- LIVE: атрибуция realized из bn.income ----------
    def _income_window(self, start_ms, end_ms=None):
        real = fund = comm = 0.0
        coins, trades = set(), 0
        rows = self.bn.income(start_ms)
        for r in rows:
            t = int(r.get("time", 0) or 0)
            if t < start_ms or (end_ms and t > end_ms):
                continue
            v = float(r.get("income", 0) or 0)
            it = r.get("incomeType")
            if it == "REALIZED_PNL":
                real += v
                trades += 1
            elif it == "FUNDING_FEE":
                fund += v
            elif it == "COMMISSION":
                comm += v
            if r.get("symbol"):
                coins.add(r["symbol"])
        return {"realized": round(real, 4), "funding": round(fund, 4),
                "commission": round(comm, 4), "net": round(real + fund + comm, 4),
                "trades": trades, "coins": sorted(coins)}

    def _bot_window(self, coins, start_ms, end_ms=None):
        """Realized/комиссия по userTrades, разбитые на БОТ vs РУЧНОЕ (по orderId ∈ _bot_orders).
        Так «реализованный PnL сессии» = только сделки копира на мастере, ручной оверлей — отдельно."""
        bot = {"realized": 0.0, "commission": 0.0, "trades": 0, "coins": set()}
        man = {"realized": 0.0, "commission": 0.0, "trades": 0, "coins": set()}
        botids = self._bot_orders
        for sym in coins:
            try:
                trades = self.bn.user_trades(sym, limit=1000)
            except Exception:
                continue
            for t in trades:
                ts = int(t.get("time", 0) or 0)
                if ts < start_ms or (end_ms and ts > end_ms):
                    continue
                dst = bot if str(t.get("orderId")) in botids else man
                dst["realized"] += float(t.get("realizedPnl", 0) or 0)
                dst["commission"] += float(t.get("commission", 0) or 0)
                dst["trades"] += 1
                dst["coins"].add(sym)
        for d in (bot, man):
            d["realized"] = round(d["realized"], 4)
            d["commission"] = round(d["commission"], 4)
            d["coins"] = sorted(d["coins"])
        return bot, man

    def _fill_live_pnl(self, s):
        if not self.have_keys:
            return
        try:
            w = self._income_window(s["started_ms"], s.get("ended_ms"))
        except Exception:
            return
        s.update(w)                                    # счёт-уровневые тоталы (funding не атрибутируется)
        try:                                           # bot-атрибуция: realized = только сделки бота
            bot, man = self._bot_window(w["coins"], s["started_ms"], s.get("ended_ms"))
            s["realized"] = bot["realized"]
            s["commission"] = bot["commission"]
            s["trades"] = bot["trades"]
            s["coins"] = bot["coins"] or w["coins"]
            s["realized_manual"] = man["realized"]
            s["trades_manual"] = man["trades"]
            s["net"] = round(bot["realized"] + (w.get("funding") or 0) + bot["commission"], 4)
        except Exception:
            pass

    # ---------- DRY: бумажный симулятор (mark-to-market) ----------
    def _paper_tick(self, desired, mids):
        s = self._cur_session
        if not s or s.get("ended") or not s.get("paper"):
            return
        book = s["paper_book"]
        realized = s.get("paper_realized", 0.0)
        for coin in set(desired) | set(book):
            price = mids.get(coin)
            if not price:
                continue
            tgt = float((desired.get(coin) or {}).get("size", 0.0))
            b = book.get(coin) or {"qty": 0.0, "entry": 0.0}
            cur, entry = b["qty"], b["entry"]
            if abs(tgt - cur) < 1e-12:
                continue
            same_side = cur == 0 or (cur > 0) == (tgt > 0)
            if same_side and abs(tgt) >= abs(cur):           # открытие / долив
                added = abs(tgt) - abs(cur)
                entry = (abs(cur) * entry + added * price) / abs(tgt) if tgt else price
                b = {"qty": tgt, "entry": entry}
            elif same_side:                                  # частичное сокращение
                reduced = abs(cur) - abs(tgt)
                realized += (price - entry) * reduced * (1 if cur > 0 else -1)
                b = {"qty": tgt, "entry": entry}
            else:                                            # флип / полное закрытие
                realized += (price - entry) * abs(cur) * (1 if cur > 0 else -1)
                b = {"qty": tgt, "entry": price} if abs(tgt) > 1e-12 else {"qty": 0.0, "entry": 0.0}
            if abs(b["qty"]) < 1e-12:
                book.pop(coin, None)
            else:
                book[coin] = b
        upnl = sum(b["qty"] * ((mids.get(c) or b["entry"]) - b["entry"]) for c, b in book.items())
        s["paper_realized"] = round(realized, 4)
        s["paper_upnl"] = round(upnl, 4)
        s["paper_equity"] = round(s["start_equity"] + realized + upnl, 2)
        s["paper_roi"] = round((realized + upnl) / s["start_equity"] * 100, 2) if s["start_equity"] else 0.0
        s["coins"] = sorted(book)
        if time.time() - self._paper_save_ts > 10:
            self._paper_save_ts = time.time()
            self._save_sessions()

    # ---------- Ф0: реконструкция из логов ----------
    def _reconstruct_sessions(self):
        p = runtime_path("log.jsonl")
        if not os.path.exists(p):
            return []
        events = []
        for x in open(p, encoding="utf-8", errors="replace").read().splitlines():
            try:
                events.append(json.loads(x))
            except Exception:
                pass
        name2addr = {m["name"]: m["address"] for m in (self.cfg.get("monitors") or []) if m.get("name")}
        out, cur, pending = [], None, None
        for e in events:
            msg, ts = e.get("msg", ""), e.get("ts", "")
            mt = re.match(r"copier: target → (.+?)(?: \(| —|$)", msg)
            if mt:
                pending = mt.group(1).strip()
                continue
            sm = re.match(r"START \((LIVE|DRY-RUN), (\w+)\)", msg)
            if sm:
                if cur:
                    cur.update(ended=ts, ended_ms=_iso_ms(ts), end_reason="superseded")
                    out.append(cur)
                mode = "live" if sm.group(1) == "LIVE" else "dry"
                nm = pending or next((t.get("label") for t in (self.cfg.get("targets") or [])), "lead")
                cur = {"id": _iso_ms(ts) or len(out), "target": name2addr.get(nm, ""), "name": nm,
                       "mode": mode, "paper": mode == "dry", "data_mode": sm.group(2),
                       "started": ts, "started_ms": _iso_ms(ts),
                       "ended": None, "ended_ms": None, "end_reason": None,
                       "start_equity": None, "realized": None, "funding": 0.0, "commission": 0.0,
                       "net": None, "trades": 0, "coins": [], "reconstructed": True,
                       "paper_book": {}, "paper_realized": 0.0, "paper_upnl": 0.0}
                continue
            if cur and (msg == "STOP" or msg.startswith("🚨 PANIC") or "target cleared" in msg):
                reason = "panic" if msg.startswith("🚨") else ("cleared" if "target cleared" in msg else "stopped")
                cur.update(ended=ts, ended_ms=_iso_ms(ts), end_reason=reason)
                if cur["mode"] != "dry":
                    try:
                        self._fill_live_pnl(cur)
                    except Exception:
                        pass
                out.append(cur)
                cur = None
        if cur:                       # последняя осталась открытой — закрываем как «прервано»
            cur.update(ended=now_iso(), ended_ms=_ms_now(), end_reason="interrupted (reconstr.)")
            out.append(cur)
        return out

    # ---------- чтение для API ----------
    def _session_view(self, s, live_interim=False):
        v = {k: s.get(k) for k in ("id", "target", "name", "mode", "paper", "data_mode",
             "started", "ended", "end_reason", "start_equity", "realized", "funding",
             "commission", "net", "trades", "coins", "reconstructed",
             "realized_manual", "trades_manual",
             "paper_realized", "paper_upnl", "paper_equity", "paper_roi")}
        if s.get("paper"):
            v["positions"] = [{"coin": c, "side": "LONG" if b["qty"] > 0 else "SHORT",
                               "qty": abs(b["qty"]), "entry": round(b["entry"], 6)}
                              for c, b in (s.get("paper_book") or {}).items()]
        if live_interim and not s.get("paper") and self.have_keys:
            try:
                w = self._income_window(s["started_ms"])               # счёт-уровневые тоталы (funding)
                bot, man = self._bot_window(w["coins"], s["started_ms"])  # bot-атрибуция realized
                v.update(realized=bot["realized"], commission=bot["commission"], trades=bot["trades"],
                         realized_manual=man["realized"], trades_manual=man["trades"],
                         funding=w["funding"], coins=bot["coins"] or w["coins"],
                         net=round(bot["realized"] + (w.get("funding") or 0) + bot["commission"], 4))
            except Exception:
                pass
            try:
                v["positions"] = [{"coin": d["symbol"].replace("USDT", ""),
                                   "side": "LONG" if d["amt"] > 0 else "SHORT",
                                   "qty": abs(d["amt"]), "entry": d["entry"],
                                   "uPnl": round(d["uPnl"], 2)}
                                  for d in self.bn.positions_detail()]
                v["upnl"] = round(sum(p["uPnl"] for p in v["positions"]), 2)
            except Exception:
                pass
        return v

    def _maybe_backfill(self, s):
        """Ленивая до-загрузка realized для LIVE-сессии, у которой PnL не посчитался
        (например закрылась во время обрыва Binance). Только в пределах окна income (~80д)."""
        if s.get("paper") or s.get("mode") == "dry" or s.get("realized") is not None:
            return False
        if not self.have_keys:
            return False
        started = s.get("started_ms") or 0
        if started and (_ms_now() - started) > 80 * 86400 * 1000:
            return False
        try:
            self._fill_live_pnl(s)
        except Exception:
            return False
        return s.get("realized") is not None

    def get_copy_sessions(self):
        with self.lock:
            sessions = list(self._sessions)
        if [s for s in sessions if s.get("ended") and self._maybe_backfill(s)]:
            self._save_sessions()
        active, paper, closed = [], [], []
        for s in sessions:
            if s.get("ended"):
                closed.append(self._session_view(s))
            elif s.get("paper"):
                paper.append(self._session_view(s))
            else:
                active.append(self._session_view(s, live_interim=True))
        closed.sort(key=lambda x: -(x.get("id") or 0))

        def _sum(rows, key):
            return round(sum((r.get(key) or 0) for r in rows), 2)
        totals = {
            "active": len(active), "paper": len(paper), "closed": len(closed),
            "live_realized": _sum([r for r in closed if not r.get("paper")], "realized"),
            "paper_realized": _sum([r for r in closed if r.get("paper")], "paper_realized"),
        }
        return {"active": active, "paper": paper, "closed": closed, "totals": totals}
