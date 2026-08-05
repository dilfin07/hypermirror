"""Ядро копира (mixin для Controller): реконсиляция _compute, циклы poll/ws,
старт/стоп, действия (close/panic), лента активности целей и heartbeat.

Единственное место, которое размещает ордера на Binance. Состояние (self.cfg, self.hl,
self.bn, self.copy_state, self.filters, self.running/live/data_mode, self._wake, ...)
живёт в Controller. Логика копира описана в docs/COPIER-CORE.md.
"""
import threading
import time

from copier.core.plan import compute_plan
from copier.core.positions import spot_capital_usd
from copier.core.format import now_iso
from copier.execution.binance import positions_from_account, round_step, to_symbol
from copier.execution import executor
from copier.hl.rest import MAINNET as HL_MAIN, TESTNET as HL_TEST


def advance_prev_tgt(cur_tgt, prev_tgt, failed_symbols):
    """Новый baseline позиций цели после торгового тика.

    `_prev_tgt_pos` отвечает на вопрос «двинулся ли лид с прошлого раза»: если да —
    ордер порождён движением цели и проходит даже при auto_sync=off; если нет — это
    правка расхождения (sync), и она откладывается до ручной кнопки.

    M-1: baseline двигался безусловно, даже когда биржа ордер ОТКЛОНИЛА. Движение лида
    засчитывалось как отработанное, и на следующем тике тот же ордер выглядел уже как
    «sync» — при auto_sync=off он откладывался навсегда. Отклонённое ЗАКРЫТИЕ означало
    позицию, которую копир больше никогда не попробует закрыть.

    Поэтому по символам с неудавшимися ордерами baseline НЕ двигаем: лид по ним считается
    ещё не отработанным, и следующий тик повторит попытку (размер пересчитается от
    фактической позиции, так что дублей не будет)."""
    new_prev = dict(cur_tgt)
    for sym in failed_symbols:
        if sym in prev_tgt:
            new_prev[sym] = prev_tgt[sym]
        else:
            new_prev.pop(sym, None)   # цели по символу не было — пусть и не появится
    return new_prev


class EngineMixin:
    # ---------- лента активности / heartbeat ----------
    _ACT = {"OPEN": "Opened", "INCREASE": "Added", "REDUCE": "Reduced",
            "CLOSE": "Closed", "FLIP": "Flipped"}

    def _poll_target_activity(self):
        if time.time() - self._act_ts < 2.5:
            return
        self._act_ts = time.time()
        from copier.core.events import classify_fill
        for tg in self.cfg["targets"]:
            addr = tg["address"]
            seen = self._seen_fills.setdefault(addr, set())
            try:
                fills = self.hl.user_fills(addr)
            except Exception:
                continue
            new = [f for f in fills if f.get("tid") not in seen]
            for f in fills:
                seen.add(f.get("tid"))
            if len(seen) > 4000:
                self._seen_fills[addr] = set(list(seen)[-2000:])
            if addr not in self._fills_seeded:     # первый раз — не спамим историей
                self._fills_seeded.add(addr)
                continue
            wl = set(self.cfg.get("coin_whitelist") or [])
            for f in sorted(new, key=lambda x: x["time"]):
                try:
                    e = classify_fill(f)
                except Exception:
                    continue
                if ":" in e["coin"] or (wl and e["coin"] not in wl):
                    continue   # показываем только релевантные нам монеты
                act = self._ACT.get(e["action"], e["action"])
                cp = e.get("closedPnl")
                cps = ""
                if cp not in (None, "0.0", "0") and e["action"] in ("REDUCE", "CLOSE", "FLIP"):
                    cps = f"  PnL {float(cp):+.2f}"
                px = e["px"]
                pxs = f"${px:,.2f}" if px >= 1 else f"${px:.6f}"
                self.log(f"🎯 {e['coin']} {e['side']} {act} {e['sz']:g} @ {pxs}{cps}", "target")

    def _maybe_log_skips(self, skipped):
        # дедуп по (символ + ТИП пропуска), без меняющейся цены в причине —
        # иначе favorability/dead-band спамят каждый тик (цена в тексте всё время разная)
        def _k(s, w):
            return f"{s}:{str(w).split(':', 1)[0]}"
        keys = {_k(s, w) for s, w in skipped}
        for s, w in skipped:
            if _k(s, w) not in self._last_skips:
                self.log(f"⏭️ skip {s}: {w}", "skip")
        self._last_skips = keys

    def _maybe_heartbeat(self, status):
        import time as _t
        if not self.running or _t.time() - self._hb_ts < 60:
            return
        self._hb_ts = _t.time()
        self.log(f"💓 heartbeat: {'LIVE' if self.live else 'DRY'} · {self.data_mode} · "
                 f"equity ${status['equity']} · positions {len(status['positions'])} · RUNNING", "hb")

    def _activity_worker(self):
        """Фоновый опрос ленты активности целей (каждые 3с), независимо от реконсиляции."""
        while True:
            try:
                self._poll_target_activity()
            except Exception:
                pass
            time.sleep(3)

    @staticmethod
    def _order_action(o):
        cur, tgt = o.get("cur", 0), o.get("target", 0)
        if abs(tgt) < 1e-9:
            return "Closed"
        if abs(cur) < 1e-9:
            return "Opened"
        return "Added" if abs(tgt) > abs(cur) else "Reduced"

    def _fmt_copy_alert(self, o, mark, label, equity, source="target"):
        """Развёрнутый Telegram-алерт по скопированной сделке (в стиле монитор-алерта).
        source: 'target' — повтор сделки трейдера; 'sync' — реконсиляция (бот свёл позицию к цели:
        поддержание кэпа/откат ручной правки/догон), трейдер при этом не двигал позицию."""
        ACT = {"Opened": "Opened", "Added": "➕ Added",
               "Reduced": "➖ Reduced", "Closed": "Closed"}
        SRC = {"target": "🎯 Source: lead trade",
               "sync": "🔄 Source: reconciliation (bot synchronized the position)"}
        cur, tgt = o.get("cur", 0.0), o.get("target", 0.0)
        side = "SHORT" if (tgt or cur) < 0 else "LONG"
        dot = "🔴" if side == "SHORT" else "🟢"
        coin = o["symbol"].replace("USDT", "")
        act = self._order_action(o)
        pct = ((abs(tgt) - abs(cur)) / abs(cur) * 100) if abs(cur) > 1e-9 else 100.0
        pos_ntl = abs(tgt) * mark if mark else 0
        lines = [
            f"📋 <b>Copied</b> · {label}",
            f"{dot} <b>{coin}</b> {side} · {ACT.get(act, act)}",
            f"• Size: {cur:g} → {tgt:g} ({pct:+.1f}%)",
            f"• Order: {o['side']} {o['qty']:g} (~${o['notional']:,.0f})" + (f" @ ${mark:,.6g}" if mark else ""),
        ]
        if equity:
            lines.append(f"• Our position: ~${pos_ntl:,.0f} ({pos_ntl / equity:.2f}× equity)")
        if o.get("position_side") and o["position_side"] != "BOTH":
            lines.append(f"• Leg: {o['position_side']}")
        lines.append(SRC.get(source, SRC["target"]))
        return "\n".join(lines)

    def _target_spot_usd(self, addr):
        """Спот-капитал цели (USDC/USDT total, вкл. held) для честной пропорции.
        Кэш 60с — меняется редко. Спот backs перп → это часть капитала цели."""
        now = time.time()
        c = self._spot_cache.get(addr)
        if c and now - c[0] < 60:
            return c[1]
        usd = c[1] if c else 0.0
        try:
            sp = self.hl.spot_clearinghouse_state(addr)
            usd = spot_capital_usd(sp)
        except Exception:
            pass                       # на ошибке оставляем прошлое значение
        self._spot_cache[addr] = (now, usd)
        return usd

    def _bot_legs(self, real_legs):
        """Классификатор bot-vs-manual: вернуть позиции, которыми ВПРАВЕ управлять бот.
        Seed при первом включении = текущие реальные позиции (всё считаем ботовым на enable);
        дальше ручные добавки в _bot_pos НЕ попадают (он растёт только на ордерах бота).
        Repair: клампим к реальности — бот не «держит» больше, чем есть (ручное закрытие/сокращение/флип)."""
        if not self._bot_pos_seeded:
            self._bot_pos = dict(real_legs)
            self._bot_pos_seeded = True
            self._save_bot_pos()
            self.log(f"🔖 bot/manual classifier: seed {len(self._bot_pos)} positions (all current = bot-owned)", "info", tg=False)
        repaired = {}
        for key, bq in self._bot_pos.items():
            rq = real_legs.get(key, 0.0)
            if rq == 0 or (rq > 0) != (bq > 0):
                continue                                # реально закрыто/перевёрнуто вручную → бот тут пусто
            repaired[key] = bq if abs(bq) <= abs(rq) else rq   # не больше реального
        if repaired != self._bot_pos:
            self._bot_pos = repaired
            self._save_bot_pos()
        return dict(self._bot_pos)

    # ---------- основной расчёт/исполнение ----------
    def _merge_builder_state(self, addr, state, mids):
        """Влить позиции/эквити builder-deployed перп-дексов (HIP-3: TradFi-акции/индексы)
        в state цели + их mark-цены в mids. Coin остаётся namespaced ('xyz:SPCX') —
        to_symbol() снимет префикс → SPCXUSDT, executor отсеет несуществующие на Binance.
        Эквити дексов суммируется в accountValue (честная пропорция к ОБЩЕМУ капиталу цели)."""
        try:
            if self._builder_dexs is None:
                self._builder_dexs = self.hl.perp_dexs()
        except Exception:
            return state
        aps = list(state.get("assetPositions", []))
        add_eq = 0.0
        for dx in (self._builder_dexs or []):
            try:
                bst = self.hl.clearinghouse_state(addr, dex=dx)
            except Exception:
                continue
            for ap in bst.get("assetPositions", []):
                p = ap.get("position", {})
                coin = p.get("coin")
                try:
                    szi = float(p.get("szi") or 0)
                except Exception:
                    szi = 0.0
                if not coin or szi == 0:
                    continue
                aps.append(ap)
                try:
                    mids[coin] = abs(float(p["positionValue"]) / szi)   # mark = ноционал/размер
                except Exception:
                    pass
            try:
                add_eq += float(bst.get("marginSummary", {}).get("accountValue") or 0)
            except Exception:
                pass
        merged = dict(state)
        merged["assetPositions"] = aps
        ms = dict(state.get("marginSummary", {}))
        try:
            ms["accountValue"] = float(ms.get("accountValue") or 0) + add_eq
        except Exception:
            pass
        merged["marginSummary"] = ms
        return merged

    def _compute(self, do_apply):
        cfg = self.cfg
        self._stamp_active()                 # счёт активен (троттлится; аудит last_active)
        # фильтры могли не загрузиться на старте (сеть после ребута) — добираем; без них
        # размеры/округления ордеров считать НЕЛЬЗЯ (шаг лота, minNotional), поэтому не применяем
        if not self.ensure_filters():
            do_apply = False
        mids = {k: float(v) for k, v in self.hl.all_mids().items()}
        include_spot = bool(cfg.get("proportion_include_spot", True))   # честная пропорция: + спот-кэш цели
        copy_builder = not cfg.get("skip_builder_dexs", True)           # опт-ин: копировать builder-dex (TradFi)
        ts = []
        for t in cfg["targets"]:
            st = self.hl.clearinghouse_state(t["address"])
            if copy_builder:
                st = self._merge_builder_state(t["address"], st, mids)
            item = {**t, "state": st}
            item["spot_usd"] = self._target_spot_usd(t["address"]) if include_spot else 0.0
            ts.append(item)
        self._hl_ok_ts = time.time()
        # текущая нетто-позиция цели по символам (для определения источника алерта)
        from copier.core.positions import net_positions as _net_positions
        cur_tgt = {}
        for t in ts:
            for coin, p in _net_positions(t["state"]).items():
                s = to_symbol(coin) or coin
                cur_tgt[s] = cur_tgt.get(s, 0.0) + p["szi"]

        hedge = False
        legs = {}
        details = []
        margin_ratio = 0
        funding = {}
        if self.have_keys:
            acct = self.bn.account()
            equity = float(acct.get("totalMarginBalance", 0) or 0)
            maint = float(acct.get("totalMaintMargin", 0) or 0)
            margin_ratio = round(maint / equity * 100, 2) if equity else 0
            # Позиции берём из ТОГО ЖЕ снимка account(), что уже запрошен ради equity:
            # один момент времени вместо двух чтений, и на один тяжёлый запрос меньше
            # (positionRisk без фильтра по символу — сотни записей на каждом тике).
            legs = positions_from_account(acct)
            details = self.bn.positions_detail()
            if cfg.get("manage_only_bot_positions"):
                legs = self._bot_legs(legs)     # реконсилим ТОЛЬКО бот-позицию (ручное не трогаем)
            try:
                funding = self.bn.funding_rates()
            except Exception:
                funding = {}
            try:
                hedge = self.bn.position_mode()
            except Exception:
                hedge = False
            eq_src = "binance"
            self._bn_ok_ts = time.time()
        else:
            equity = float(cfg.get("paper_equity_usd", 1000))
            eq_src = "paper"

        desired, frozen, notes = compute_plan(ts, mids, equity, cfg, self.copy_state)
        for c in list(desired):
            if c in self.disabled:
                desired.pop(c)

        bn_marks = self.bn.mark_prices() if self.have_keys else {}
        # managed_symbols — какие ноги hedge-билдер вправе вести/ЗАКРЫВАТЬ.
        # При заданном whitelist — только его монеты. При ПУСТОМ (copy-all) раньше получалось ∅,
        # из-за чего hedge-билдер НЕ МОГ закрыть нашу ногу при выходе лида (позиция зависала).
        # Фикс: в copy-all режиме управляем всеми символами, что держим ИЛИ копируем.
        managed = {to_symbol(c) for c in (cfg.get("coin_whitelist") or []) if to_symbol(c)}
        if not cfg.get("coin_whitelist"):
            managed = {s for (s, _ps) in legs} | {to_symbol(c) for c in desired if to_symbol(c)}
        fav = {"on": bool(cfg.get("favorability_gate", True)),
               "tol": float(cfg.get("favorability_tol_pct", 0.3))}
        roundup = bool(cfg.get("min_notional_roundup", True))
        if hedge:
            plan = executor.build_orders_hedge(desired, bn_marks, self.filters, legs, managed, fav=fav, roundup=roundup)
        else:
            cur = {sym: amt for (sym, ps), amt in legs.items()}
            plan = executor.build_orders(desired, bn_marks, self.filters, cur, fav=fav, roundup=roundup)

        # снимок расчёта для превью ручной синхронизации (sync_preview) — до фильтрации/применения
        self._last_compute = {
            "ts": time.time(),
            "orders": list(plan["orders"]),
            "skipped": list(plan["skipped"]),
            "marks": dict(bn_marks),
            "entry_by_sym": {to_symbol(c): d.get("entry") for c, d in desired.items() if to_symbol(c)},
            "cur_tgt": dict(cur_tgt),
            "prev_tgt": dict(self._prev_tgt_pos),
        }

        # adopt при старте/переключении: берём текущие позиции счёта КАК ЕСТЬ, снимок лида → baseline,
        # этот тик НЕ исполняем. Дальше следуем только за НОВЫМИ движениями лида; полный догон — «Синхронизировать».
        if getattr(self, "_adopt_next", False):
            self._adopt_next = False
            self._prev_tgt_pos = dict(cur_tgt)
            do_apply = False
            self.log("account adopted (adopt) — following new lead movements; catch-up by size/average — «Synchronize»", "info", tg=False)

        if do_apply and self.have_keys and (plan["orders"] or plan["leverage"]):
            # auto_sync OFF (по умолчанию): применяем ТОЛЬКО ордера от реального движения лида;
            # «sync»-правки (откат ручного вмешательства / поддержание кэпов) откладываем до кнопки
            # «Синхронизировать» (force). force — разовый: после применения сбрасывается.
            auto_sync = bool(cfg.get("auto_sync", False))
            force = getattr(self, "_force_sync", False)
            if not auto_sync and not force and plan["orders"]:
                kept, deferred = [], 0
                for o in plan["orders"]:
                    prev = self._prev_tgt_pos.get(o["symbol"], 0.0)
                    moved = abs(cur_tgt.get(o["symbol"], 0.0) - prev) > max(1e-9, abs(prev) * 0.001)
                    if moved:
                        kept.append(o)
                    else:
                        deferred += 1
                if deferred:
                    self.log(f"🔧 {deferred} edits deferred (auto_sync off — press «Synchronize»)", "skip", tg=False)
                plan["orders"] = kept
            if force:
                self._force_sync = False
        failed_symbols = set()   # символы, по которым биржа отклонила ордер (M-1)
        if do_apply and self.have_keys and (plan["orders"] or plan["leverage"]):
            execu = {
                "mode": cfg.get("execution_mode", "taker"),     # taker | maker
                "filters": self.filters,
                "maker_wait_sec": cfg.get("maker_wait_sec", 5),
                "maker_max_chases": cfg.get("maker_max_chases", 1),
                "maker_fallback_taker": cfg.get("maker_fallback_taker", True),
                "log": self.log,
            }
            res = executor.apply(self.bn, plan, execu)
            order_results = [r for r in res if r[0] == "order"]
            track_bot = bool(cfg.get("manage_only_bot_positions"))
            bot_pos_dirty = False
            for o, r in zip(plan["orders"], order_results):
                err = isinstance(r[3], str) and r[3].startswith("ERR")
                if err:
                    failed_symbols.add(o["symbol"])   # M-1: движение лида НЕ отработано → повторим
                    self.log(f"[copy] ❌ order {o['symbol']} {o['side']}: {r[3]}", "error")
                else:
                    self._record_bot_order(r[3])
                    sym = o["symbol"]
                    if track_bot:                       # классификатор: учитываем бот-набор
                        k = (sym, o.get("position_side") or "BOTH")
                        self._bot_pos[k] = self._bot_pos.get(k, 0.0) + (o["qty"] if o["side"] == "BUY" else -o["qty"])
                        if abs(self._bot_pos[k]) < 1e-9:
                            self._bot_pos.pop(k, None)
                        bot_pos_dirty = True
                    prev = self._prev_tgt_pos.get(sym, 0.0)
                    moved = abs(cur_tgt.get(sym, 0.0) - prev) > max(1e-9, abs(prev) * 0.001)
                    source = "target" if moved else "sync"
                    self.log(f"✅ {self._order_action(o)} {sym} {o['side']} "
                             f"{o['qty']:g} (~${o['notional']:.0f})", "trade", tg=False)
                    label = next((t.get("label") for t in (cfg.get("targets") or [])), "lead")
                    self._tg_send(self._fmt_copy_alert(o, bn_marks.get(sym), label, equity, source))
            for kind, sym, a, r in res:
                if kind == "leverage" and isinstance(r, str) and r.startswith("ERR"):
                    self.log(f"[copy] ❌ leverage {sym}: {r}", "error")
            self._save_copy_state()
            if bot_pos_dirty:
                self._save_bot_pos()
            # обновить позиции после исполнения
            details = self.bn.positions_detail()
        self._maybe_log_skips(plan["skipped"])
        if do_apply:
            # снимок цели для след. тика; по отклонённым символам baseline НЕ двигаем (M-1)
            self._prev_tgt_pos = advance_prev_tgt(cur_tgt, self._prev_tgt_pos, failed_symbols)
            if failed_symbols:
                self.log(f"[copy] ⏳ retry on next tick: {', '.join(sorted(failed_symbols))} "
                         f"(order rejected — lead movement not processed)", "skip", tg=False)
        if self.running and not self.live:
            try:
                self._paper_tick(desired, mids)   # бумажный учёт dry-сессии (mark-to-market по mids)
            except Exception:
                pass

        # представление позиций для UI
        positions = []
        for d in details:
            side = "LONG" if d["amt"] > 0 else "SHORT"
            notional = abs(d["amt"]) * d["mark"]
            margin = notional / d["leverage"] if d["leverage"] else notional
            roi = (d["uPnl"] / margin * 100) if margin else 0
            rate = funding.get(d["symbol"], 0)
            sgn = 1 if d["amt"] > 0 else -1
            funding_est = -sgn * notional * rate     # <0 = платим, >0 = получаем
            positions.append({
                "symbol": d["symbol"], "side": side, "positionSide": d["positionSide"],
                "qty": abs(d["amt"]), "entry": d["entry"], "breakeven": d.get("breakeven", 0),
                "mark": d["mark"], "liq": d.get("liq", 0), "notional": round(notional, 2),
                "margin": round(margin, 2), "margin_type": d.get("marginType", "cross"),
                "uPnl": round(d["uPnl"], 2), "roi": round(roi, 1), "leverage": d["leverage"],
                "funding_est": round(funding_est, 4), "funding_rate": round(rate * 100, 4),
            })

        target_view = []
        for t in cfg["targets"]:
            from copier.core.positions import net_positions, account_value
            x = next((x for x in ts if x["address"] == t["address"]), {})
            st = x.get("state", {})
            tv = account_value(st)
            spot = float(x.get("spot_usd", 0.0) or 0.0)
            basis = max(tv, spot)                  # ПОЛНЫЙ пул USDC (спот backs перп): max, не сумма
            tpos = []
            for coin, p in net_positions(st).items():
                if ":" in coin:
                    continue
                m = mids.get(coin) or p["entryPx"]
                tpos.append({"coin": coin, "side": "LONG" if p["szi"] > 0 else "SHORT",
                             "exposure_pct": round(abs(p["szi"]) * m / basis * 100, 1) if basis else 0,
                             "lev": p["lev"]})
            target_view.append({"address": t["address"], "label": t.get("label", t["address"][:10]),
                                "equity": round(tv), "spot_usd": round(spot), "basis_equity": round(basis),
                                "positions": tpos})

        status = {
            "ready": True, "ts": now_iso(),
            "running": self.running, "live": self.live, "data_mode": self.data_mode,
            "have_keys": self.have_keys, "hedge": hedge,
            "active_account": cfg.get("active_account", "main"),
            "account_type": getattr(self, "account_type", "futures"),
            "network": getattr(self, "account_net", None) or (cfg.get("binance") or {}).get("network", "testnet"),
            "equity": round(equity, 2), "equity_src": eq_src, "margin_ratio": margin_ratio,
            "leverage_mode": cfg.get("leverage_mode"),
            "execution_mode": cfg.get("execution_mode", "taker"),
            "positions": positions,
            "desired": [{"coin": c, **d} for c, d in desired.items()],
            "planned_orders": plan["orders"], "skipped": plan["skipped"],
            "frozen": [{"label": l, "coin": c, "move_pct": fr.get("move_pct")} for l, c, p, fr in frozen],
            "disabled": sorted(self.disabled),
            "targets": target_view,
            "notes": notes,
        }
        status["services"] = self._services_health(status)
        with self.lock:
            self.status = status
            self._status_ts = time.time()
        self._maybe_heartbeat(status)
        return status

    # ---------- цикл ----------
    def _poll_loop(self):
        while self.running:
            try:
                self._compute(do_apply=self.live)
            except Exception as e:
                self.log(f"[copy] tick: {e}", "error")
            for _ in range(int(self.cfg.get("poll_interval_sec", 30))):
                if not self.running:
                    break
                time.sleep(1)

    def _start_ws_stream(self):
        """Подписка на userFills целей: каждый филл будит реконсиляцию."""
        if self._ws_started:
            return
        try:
            import hyperliquid  # noqa: F401
        except Exception:
            self.log("WS requires .venv (SDK). Run: .venv/bin/python tools/serve.py. "
                     "Falling back to polling.", "error")
            self.data_mode = "poll"
            return
        from copier.hl.ws import FillStream
        base = HL_TEST if self.cfg.get("network") == "testnet" else HL_MAIN
        addrs = [t["address"] for t in self.cfg["targets"]]

        def on_fill(addr, fill):
            self._wake.set()

        # держим ссылку (self._copier_fs) — для статус-бара; on_reconnect=_wake.set → догон после обрыва
        self._copier_fs = FillStream(on_fill, base, log=self.log, on_reconnect=self._wake.set)
        for a in addrs:
            self._copier_fs.add(a)
        self._copier_fs.start()
        self._ws_started = True
        self.log(f"WS subscription to {len(addrs)} address(es) — instant triggers", "info")

    def _ws_reconcile_loop(self):
        try:
            self._compute(do_apply=self.live)
        except Exception as e:
            self.log(f"[copy] tick: {e}", "error")
        while self.running:
            self._wake.wait(timeout=60)     # фолбэк-реконсиляция раз в 60с
            self._wake.clear()
            if not self.running:
                break
            time.sleep(1.2)                 # дебаунс: дать филлам собраться
            try:
                self._compute(do_apply=self.live)
            except Exception as e:
                self.log(f"[copy] tick: {e}", "error")

    def start(self, live, mode=None):
        with self.lock:
            if mode in ("poll", "ws"):
                self.data_mode = mode
            if self.running:
                self.live = bool(live)
                self.log(f"mode -> {'LIVE' if self.live else 'DRY-RUN'}", "info")
                self._journal_on_toggle()
                return
            self.live = bool(live)
            self.running = True
            self._adopt_next = True            # на старте/после переключения — adopt (без форс-догона к лиду)
            self._stamp_active(force=True)      # счёт активен с этого момента (аудит last_active)
            if self.data_mode == "ws":
                self._start_ws_stream()
            target = self._ws_reconcile_loop if self.data_mode == "ws" else self._poll_loop
            self.thread = threading.Thread(target=target, daemon=True)
            self.thread.start()
            self.log(f"START ({'LIVE' if self.live else 'DRY-RUN'}, {self.data_mode})", "info")
            self._journal_on_start()

    def stop(self):
        with self.lock:
            self.running = False
        self._wake.set()
        self._close_session("stopped")
        self.log("STOP", "info")

    def sync_now(self):
        """Разовая принудительная синхронизация позиции с лидером (применяет и отложенные
        sync-правки). Нужна при auto_sync=off, чтобы вручную свести позицию к цели."""
        if not self.running:
            return {"error": "copier not running"}
        if not self.live:
            return {"error": "copier in DRY — synchronize only in LIVE"}
        self._force_sync = True
        self._wake.set()                       # ws-режим — мгновенно; poll — на следующем тике
        self.log("🔧 manual position synchronization with the lead requested", "info")
        return {"ok": True}

    def sync_preview(self):
        """Что сделает ручная синхра: отложенные (sync) ордера + отклонение цены от входа лида.
        Только читает снимок последнего расчёта — без пересчёта и без применения."""
        if not self.running:
            return {"error": "copier not running"}
        if not self.live:
            return {"error": "copier in DRY — synchronize only in LIVE"}
        snap = getattr(self, "_last_compute", None)
        if not snap:
            return {"error": "no computation yet — wait for a tick"}
        items = []
        for o in snap["orders"]:
            sym = o["symbol"]
            prev = snap["prev_tgt"].get(sym, 0.0)
            moved = abs(snap["cur_tgt"].get(sym, 0.0) - prev) > max(1e-9, abs(prev) * 0.001)
            if moved:
                continue                       # это копир применил бы сам (движение лида), не ручная синхра
            mark = snap["marks"].get(sym) or 0.0
            entry = snap["entry_by_sym"].get(sym)
            dev = ((mark - entry) / entry * 100) if (entry and mark) else None
            items.append({"symbol": sym, "side": o["side"], "action": self._order_action(o),
                          "qty": o["qty"], "notional": o["notional"], "dev_pct": dev})
        fav_skipped = sum(1 for _s, w in snap["skipped"] if str(w).startswith("favorability"))
        return {"ok": True, "items": items, "fav_skipped": fav_skipped}

    # ---------- действия ----------
    def _close_symbol(self, symbol, position_side, amt):
        filt = self.filters.get(symbol, {"stepSize": 0})
        qty = round_step(abs(amt), filt.get("stepSize", 0)) or abs(amt)
        side = "BUY" if amt < 0 else "SELL"
        ps = position_side if position_side and position_side != "BOTH" else None
        resp = self.bn.market_order(symbol, side, qty, reduce_only=(ps is None), position_side=ps)
        self._record_bot_order(resp)
        return resp

    def close(self, symbol, position_side=None):
        if not self.have_keys:
            return {"error": "no keys"}
        done = []
        for d in self.bn.positions_detail():
            if d["symbol"] != symbol:
                continue
            if position_side and d["positionSide"] != position_side:
                continue   # в hedge закрываем только указанную ногу (не трогаем ручную)
            try:
                self._close_symbol(d["symbol"], d["positionSide"], d["amt"])
                done.append(f"{d['symbol']}/{d['positionSide']}")
                self.log(f"Closed {d['symbol']}/{d['positionSide']} qty {abs(d['amt'])}", "trade")
            except Exception as e:
                self.log(f"[copy] close {symbol} ERR {e}", "error")
                return {"error": str(e)}
        # отключаем монету, чтобы цикл не переоткрыл сразу
        coin = next((c for c in (self.cfg.get("coin_whitelist") or []) if to_symbol(c) == symbol), None)
        if coin:
            self.disabled.add(coin)
        self._compute(do_apply=False)
        return {"closed": done, "disabled_coin": coin}

    def panic(self):
        if not self.have_keys:
            return {"error": "no keys"}
        self.stop()
        self._restamp_last_reason("panic")
        closed = []
        for d in self.bn.positions_detail():
            try:
                self._close_symbol(d["symbol"], d["positionSide"], d["amt"])
                closed.append(f"{d['symbol']}/{d['positionSide']}")
            except Exception as e:
                self.log(f"[copy] panic close {d['symbol']} ERR {e}", "error")
        self.log(f"🚨 PANIC: closed {len(closed)} positions, bot stopped", "trade")
        self._compute(do_apply=False)
        return {"closed": closed}

    def enable_coin(self, coin):
        self.disabled.discard(coin)
        self.log(f"coin {coin} re-enabled", "info")
