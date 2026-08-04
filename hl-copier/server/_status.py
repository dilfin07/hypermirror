"""Status/UI-данные (mixin для Controller): статус бота, здоровье сервисов,
read-эндпоинты для UI (ордера/исполнения/история/свечи) и статистика аккаунта.

Состояние (self.bn, self.cfg, self.status, self.filters, self.have_keys, ...) живёт
в Controller. Здесь только методы. Подмешивается через наследование.
"""
import time

from copier.execution.binance import to_symbol


class StatusMixin:
    def klines(self, symbol, interval="15m", limit=300):
        try:
            return self.bn.klines(symbol, interval, limit)
        except Exception as e:
            return {"error": str(e)}

    # ---------- история (ордера / исполнения / позиции) ----------
    def _traded_symbols(self):
        syms = set()
        try:
            for d in self.bn.positions_detail():
                syms.add(d["symbol"])
        except Exception:
            pass
        for c in (self.cfg.get("coin_whitelist") or []):
            s = to_symbol(c)
            if s and (not self.filters or s in self.filters):
                syms.add(s)
        return syms or {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def _cached(self, key, ttl, fn):
        c = getattr(self, "_hist_cache", None)
        if c is None:
            c = self._hist_cache = {}
        ent = c.get(key)
        if ent and time.time() - ent[0] < ttl:
            return ent[1]
        val = fn()
        c[key] = (time.time(), val)
        return val

    def get_orders(self):
        if not self.have_keys:
            return {"orders": []}
        try:
            oo = self.bn.open_orders_all()
        except Exception as e:
            return {"error": str(e)}
        out = [{"symbol": o["symbol"], "side": o["side"], "type": o.get("type"),
                "qty": float(o.get("origQty", 0) or 0), "price": float(o.get("price", 0) or 0),
                "value": float(o.get("price", 0) or 0) * float(o.get("origQty", 0) or 0),
                "positionSide": o.get("positionSide"), "reduceOnly": o.get("reduceOnly"),
                "trigger": float(o.get("stopPrice", 0) or 0), "time": o.get("time")} for o in oo]
        return {"orders": out}

    def get_fills(self):
        if not self.have_keys:
            return {"fills": []}

        def build():
            fills = []
            for s in self._traded_symbols():
                try:
                    for t in self.bn.user_trades(s, limit=100):
                        fills.append({"symbol": s, "side": t["side"], "qty": float(t["qty"]),
                                      "price": float(t["price"]), "realizedPnl": float(t.get("realizedPnl", 0) or 0),
                                      "commission": float(t.get("commission", 0) or 0),
                                      "maker": t.get("maker"), "time": t["time"],
                                      "bot": str(t.get("orderId")) in self._bot_orders})
                except Exception:
                    pass
            fills.sort(key=lambda x: -x["time"])
            return {"fills": fills[:150]}
        return self._cached("fills", 25, build)

    def get_position_history(self):
        if not self.have_keys:
            return {"positions": []}

        def build():
            closed = []
            for s in self._traded_symbols():
                try:
                    trades = sorted(self.bn.user_trades(s, limit=500), key=lambda t: t["time"])
                except Exception:
                    continue
                pos = en_q = en_not = rpnl = comm = max_q = 0.0
                open_t = side = last_t = None
                bot_open = False                          # открыта ли позиция бот-ордером
                for t in trades:
                    q = float(t["qty"]); price = float(t["price"])
                    signed = q if t["side"] == "BUY" else -q
                    rp = float(t.get("realizedPnl", 0) or 0); cm = float(t.get("commission", 0) or 0)
                    last_t = t["time"]
                    if abs(pos) < 1e-12:
                        open_t = t["time"]; side = "LONG" if signed > 0 else "SHORT"
                        en_q, en_not, rpnl, comm, pos = q, q * price, rp, cm, signed
                        max_q = abs(pos)
                        bot_open = str(t.get("orderId")) in self._bot_orders
                    else:
                        rpnl += rp; comm += cm
                        if (pos > 0) == (signed > 0):
                            en_q += q; en_not += q * price
                        pos += signed
                        max_q = max(max_q, abs(pos))
                        if abs(pos) < 1e-9:
                            closed.append({"symbol": s, "side": side, "status": "closed",
                                           "entry": round(en_not / en_q, 5) if en_q else 0,
                                           "exit": round(price, 5), "qty": round(en_q, 6),
                                           "max_qty": round(max_q, 6),
                                           "realizedPnl": round(rpnl, 2), "commission": round(comm, 4),
                                           "open_time": open_t, "close_time": t["time"],
                                           "duration_min": round((t["time"] - open_t) / 60000),
                                           "bot": bot_open})
                            pos = en_q = en_not = rpnl = comm = max_q = 0.0; bot_open = False
                # позиция ещё ОТКРЫТА, но по ней уже был реализованный PnL → частично закрыта
                if abs(pos) > 1e-9 and abs(rpnl) > 1e-9:
                    closed.append({"symbol": s, "side": side, "status": "partial",
                                   "entry": round(en_not / en_q, 5) if en_q else 0,
                                   "exit": None, "qty": round(abs(pos), 6), "max_qty": round(max_q, 6),
                                   "realizedPnl": round(rpnl, 2), "commission": round(comm, 4),
                                   "open_time": open_t, "close_time": None,
                                   "duration_min": round((last_t - open_t) / 60000) if last_t else None,
                                   "bot": bot_open})
            closed.sort(key=lambda x: -(x.get("close_time") or x.get("open_time") or 0))
            from copier.core.analytics import trade_analytics
            # метрики — только по ПОЛНОСТЬЮ закрытым (partial ещё не финализирован)
            fully = [c for c in closed if c.get("status") != "partial"]
            return {"positions": closed[:100], "analytics": trade_analytics(fully)}
        return self._cached("poshist", 30, build)

    def user_trades(self, symbol):
        if not self.have_keys:
            return []
        try:
            return self.bn.user_trades(symbol)
        except Exception as e:
            return {"error": str(e)}

    # ---------- статус бота + здоровье сервисов ----------
    def get_status(self, max_age=2.5, stale_recompute=20.0):
        """Статус для UI. НЕ блокируем HTTP на медленный _compute (на testnet он ~7с:
        Binance testnet отвечает ~2с на запрос, а их несколько). Отдаём последний
        кэш — его держит свежим копир-цикл, а tick_age_sec показывает возраст.

        Синхронный пересчёт делаем только если: кэша нет совсем (первый запрос) ИЛИ
        он совсем протух (> stale_recompute) — значит копир-цикл давно не тикал
        (остановлен/тихий рынок), и обновить статус больше некому. max_age оставлен
        для обратной совместимости вызовов, что просят «посвежее»."""
        with self.lock:
            age = (time.time() - self._status_ts) if self._status_ts else 1e9
            has_cache = bool(self.status.get("ready"))
            st = dict(self.status) if has_cache else None
        if st is None or age > max(max_age, stale_recompute):
            try:
                st = self._compute(do_apply=False)
            except Exception as e:
                self.log(f"status error: {e}", "error")
                with self.lock:
                    st = dict(self.status)
        st = dict(st)
        st["tick_age_sec"] = round(time.time() - self._status_ts) if self._status_ts else None
        return st

    def _services_health(self, st):
        """Здоровье 4 сервисов для статус-бара: hyperliquid / binance / copier / monitoring.
        state: ok (зелёный) · warn (жёлтый) · down (красный) · off (серый, выключен/не настроен)."""
        now = time.time()

        def age(ts):
            return None if not ts else round(now - ts, 1)

        mon_ws = bool(self._fill_stream and getattr(self._fill_stream, "connected", False))
        cop_ws = bool(self._copier_fs and self._copier_fs.connected)
        hl_age = age(self._hl_ok_ts)
        bn_age = age(self._bn_ok_ts)
        mon_age = age(self._last_mon_event_ts)
        mons = self.cfg.get("monitors") or []
        poll_iv = int(self.cfg.get("poll_interval_sec", 30))

        def freshness(a, warn=45, down=120):
            if a is None:
                return "down"
            return "ok" if a < warn else ("warn" if a < down else "down")

        # Hyperliquid: ок если недавно был REST-ответ ИЛИ любой WS подключён
        hl_state = "ok" if (mon_ws or cop_ws or freshness(hl_age) == "ok") else freshness(hl_age)
        hyperliquid = {"state": hl_state, "ws_streams": int(mon_ws) + int(cop_ws),
                       "transport": "ws" if (mon_ws or cop_ws) else "rest",
                       "rest_age_sec": hl_age}

        # Binance
        if not self.have_keys:
            binance = {"state": "off", "note": "keys not set"}
        else:
            binance = {"state": freshness(bn_age), "equity": st.get("equity"),
                       "margin_ratio": st.get("margin_ratio"),
                       "network": (self.cfg.get("binance") or {}).get("network"),
                       "age_sec": bn_age}

        # Copier
        if not self.running:
            copier = {"state": "off", "note": "stopped"}
        else:
            copier = {"state": freshness(bn_age, warn=poll_iv * 2, down=poll_iv * 4)
                      if self.have_keys else "ok"}
        copier.update({"running": self.running, "live": self.live, "mode": self.data_mode,
                       "ws": cop_ws if (self.running and self.data_mode == "ws") else None,
                       "positions": len(st.get("positions") or [])})

        # Monitoring
        if not mons:
            monitoring = {"state": "off", "note": "no addresses"}
        else:
            monitoring = {"state": "ok" if mon_ws else "warn", "count": len(mons),
                          "ws": mon_ws, "last_event_sec": mon_age}

        # Telegram (health пайплайна доставки алертов) — очередь + давность успешной отправки
        import time as _t
        tg_cfg = self.cfg.get("telegram") or {}
        if not (tg_cfg.get("enabled") and self._tg_token and tg_cfg.get("chat_id")):
            telegram = {"state": "off", "note": "not configured/disabled"}
        else:
            qd = self._tg_queue.qsize()
            last_ok = round(_t.time() - self._tg_ok_ts) if self._tg_ok_ts else None
            fail = self._tg_fail
            # Тишина на рынке ≠ отказ: last_ok растёт только на фактической отправке (heartbeat нет),
            # поэтому ПУСТАЯ очередь не может дать down — слать просто нечего (ложный down 6 июля).
            # Реальный отказ: сообщения копятся и давно не уходило; очередь распухла; свежий фейл
            # при давнем последнем успехе.
            stale = last_ok is not None and last_ok > 600             # давно не было успешной отправки
            recent_fail = bool(fail) and (_t.time() - fail.get("ts", 0) < 120)
            state = "ok"
            if qd > 200 or (qd > 0 and stale) or (recent_fail and stale):
                state = "down"
            elif recent_fail:                                         # недавний фейл отправки
                state = "warn"
            telegram = {"state": state, "queue": qd, "last_ok_sec": last_ok, "last_fail": fail}

        return {"hyperliquid": hyperliquid, "binance": binance, "copier": copier,
                "monitoring": monitoring, "telegram": telegram}

    # ---------- статистика аккаунта Binance (для дашборда) ----------
    def _income_daily(self):
        import datetime
        now = time.time()
        if now - getattr(self, "_income_ts", 0) < 300 and getattr(self, "_income_cache", None) is not None:
            return self._income_cache
        start_ms = int((now - 365 * 86400) * 1000)
        try:
            rows = self.bn.income(start_ms)
        except Exception as e:
            self.log(f"income error: {e}", "error")
            return ({}, 0.0)
        from collections import defaultdict
        # переводы/депозиты/выводы — движение капитала, НЕ торговый PnL (иначе вывод красит день в минус)
        SKIP = {"TRANSFER", "INTERNAL_TRANSFER", "CROSS_COLLATERAL_TRANSFER", "COIN_SWAP_DEPOSIT", "COIN_SWAP_WITHDRAW"}
        daily, total = defaultdict(float), 0.0
        for r in rows:
            if r.get("incomeType") in SKIP:
                continue
            v = float(r.get("income", 0) or 0)
            total += v
            d = datetime.datetime.fromtimestamp(r["time"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
            daily[d] += v
        res = ({k: round(v, 2) for k, v in daily.items()}, total)
        self._income_cache, self._income_ts = res, now
        return res

    def get_account_stats(self):
        if not self.have_keys:
            return {"have_keys": False}
        try:
            acct = self.bn.account()
            details = self.bn.positions_detail()
            equity = float(acct.get("totalMarginBalance", 0) or 0)
            uPnl = float(acct.get("totalUnrealizedProfit", 0) or 0)
            init_margin = float(acct.get("totalPositionInitialMargin", 0) or 0)
            notional = sum(abs(d["amt"]) * d["mark"] for d in details)
            daily, realized = self._income_daily()
            return {
                "have_keys": True,
                "equity": round(equity, 2),
                "uPnl": round(uPnl, 2),
                "leverage": round(notional / equity, 2) if equity else 0,
                "margin_usage": round(init_margin / equity * 100, 2) if equity else 0,
                "realized_total": round(realized, 2),
                "daily": daily,
            }
        except Exception as e:
            return {"have_keys": True, "error": str(e)}
