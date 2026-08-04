# Monitor — how we watch traders

> Discovery part of the service: **Monitor** (watch selected addresses) →
> **Copier** (execute, see [COPIER-CORE.md](COPIER-CORE.md)).

> 🇷🇺 [Русская версия](MONITOR.ru.md).

```
Monitor (watch, alerts)  ──►  Copier (execute)
   ↑ Hyperliquid WS+poll        ↑ Binance
```

Whom to copy — you pick manually (e.g. via an external dashboard) and add the address to the monitor.

---

## What it does
Watches a list of addresses on Hyperliquid and **sends alerts to Telegram** when a watched
address opens/adds to/reduces/closes/reverses a position or changes leverage. It also keeps
data for the "Monitor" tab in the UI (positions, equity, ROI).

## Two mechanisms (instant + reliable)
| Channel | What it gives | When |
|---|---|---|
| **WebSocket** (`userFills` of the lead) | instant alert on a trade | as soon as the trader makes a trade |
| **Poll** (once per `monitor_interval_sec`, 30s) | data for the UI + **backstop alerts** | a safety net if the WS missed something |

Alerts go out instantly from the WS; the poll compares a snapshot of positions and sends an alert
**only if the WS did not send it** (dedup by `(address, coin, action)` within the `MON_DEDUP_SEC` window).
This way there are no duplicates, but also no misses due to a WS disconnect. The WS is resilient
(auto-reconnect, see COPIER-CORE §7).

## What it catches
`OPENED` · `ADDED` · `REDUCED` · `CLOSED` · `REVERSED` · `changed leverage`.

## Alert format
```
👁 Watched · 58bro
0x1111111111111111111111111111111111111111
────────────
🔴 BTC (Cross · Short · Add)
• Size: -28.5446 → -29.0369 (+1.72%)
• Order volume: $32.9K
• Avg. price: $66,850
• Exposure: 35.9% · 5x
📅 2026-06-15 13:21:06 UTC
```
The name is taken from the label you assigned to the address. Backstop alerts (from the poll) are
marked, so you can tell they did not come via the WS.

## Link with the copier
- **"→ To copier"** on an address = make it the **copy target** (we work with a single address).
- The copied address is marked in the monitor as "currently copying".
- **Bell** (`alerts`) — enable/disable alerts for a specific address.

## Settings (`config/config.json`)
| Key | Purpose | Typical |
|---|---|---|
| `monitors[]` | list: `{address, name, alerts}` | up to ~10–15 addresses |
| `monitor_interval_sec` | poll period (UI + backstop) | 30 |
| `monitor_min_delta_pct` | backstop alert threshold (% position change) | 5 |

---

## Full cycle
```
[Monitor]  watches an address's trades, alerts to Telegram (WS + backstop)
   │  "→ To copier" → "Start LIVE"
   ▼
[Copier]  reconciles the position to our equity with caps/risk (COPIER-CORE.md)
```
