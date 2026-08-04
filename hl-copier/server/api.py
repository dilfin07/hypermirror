"""REST API веб-интерфейса (stdlib http.server). Только localhost.

Эндпоинты:
  GET  /api/status   /api/logs   /api/config
  POST /api/config   /api/keys   /api/start {live}  /api/stop
  POST /api/close {symbol}   /api/panic   /api/enable {coin}
Статика фронта — из web/dist (после npm run build).
"""
import json
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from copier.config import PROJECT_ROOT
from server.controller import controller
from server import docs_site

WEB_DIST = os.path.join(PROJECT_ROOT, "web", "dist")
V2_DIST = os.path.join(PROJECT_ROOT, "web", "v2")   # новый UI (прототип) на /v2; боевой фронт на / не трогаем
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon",
        ".woff2": "font/woff2", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # тихо

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, text, ctype, code=200):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return {}

    def _auth_ok(self, path):
        if not path.startswith("/api/") or path in ("/api/auth_status", "/api/login"):
            return True
        if not controller.auth_required():
            return True
        h = self.headers.get("Authorization", "")
        tok = h[7:] if h.startswith("Bearer ") else ""
        return controller.check_token(tok)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if not self._auth_ok(path):
            return self._json({"error": "unauthorized"}, 401)
        # документация — публичная (не содержит секретов), открывается в новом табе
        if path == "/docs":
            return self._raw(docs_site.page_html(), "text/html; charset=utf-8")
        if path == "/docs/list":
            return self._json({"docs": docs_site.list_docs()})
        if path == "/docs/raw":
            md = docs_site.read_doc(q.get("file", [""])[0])
            if md is None:
                return self._json({"error": "not found"}, 404)
            return self._raw(md, "text/markdown; charset=utf-8")
        if path == "/api/auth_status":
            return self._json(controller.auth_status())
        if path == "/api/status":
            return self._json(controller.get_status())
        if path == "/api/logs":
            return self._json({"logs": controller.get_logs()})
        if path == "/api/config":
            return self._json(controller.get_config())
        if path == "/api/account_stats":
            return self._json(controller.get_account_stats())
        if path == "/api/klines":
            return self._json(controller.klines(q.get("symbol", [""])[0],
                                                 q.get("interval", ["15m"])[0],
                                                 int(q.get("limit", ["300"])[0])))
        if path == "/api/trades":
            return self._json(controller.user_trades(q.get("symbol", [""])[0]))
        if path == "/api/monitors":
            return self._json({"monitors": controller.get_monitors()})
        if path == "/api/orders":
            return self._json(controller.get_orders())
        if path == "/api/fills":
            return self._json(controller.get_fills())
        if path == "/api/position_history":
            return self._json(controller.get_position_history())
        if path == "/api/copy_sessions":
            return self._json(controller.get_copy_sessions())
        return self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        b = self._body()
        if not self._auth_ok(path):
            return self._json({"error": "unauthorized"}, 401)
        try:
            if path == "/api/login":
                return self._json(controller.login(b.get("password", "")))
            if path == "/api/ui_auth":
                return self._json(controller.set_ui_auth(b.get("password", ""), b.get("enabled", False)))
            if path == "/api/start":
                controller.start(bool(b.get("live", False)), b.get("mode"))
                return self._json({"ok": True})
            if path == "/api/stop":
                controller.stop()
                return self._json({"ok": True})
            if path == "/api/sync":
                return self._json(controller.sync_now())
            if path == "/api/close":
                return self._json(controller.close(b["symbol"], b.get("position_side")))
            if path == "/api/panic":
                return self._json(controller.panic())
            if path == "/api/enable":
                controller.enable_coin(b["coin"])
                return self._json({"ok": True})
            if path == "/api/config":
                return self._json(controller.set_config(b))
            if path == "/api/keys":
                return self._json(controller.set_keys(b.get("api_key", ""), b.get("api_secret", ""), b.get("key_env", "BINANCE")))
            if path == "/api/active_account":
                return self._json(controller.set_active_account(b.get("id", ""), b.get("force", False)))
            if path == "/api/telegram":
                return self._json(controller.set_telegram(b.get("token", ""), b.get("chat_id", ""), b.get("enabled", False)))
            if path == "/api/telegram_test":
                return self._json(controller.test_telegram())
            if path == "/api/notify":
                return self._json(controller.notify_tg(b.get("text", ""), b.get("kind", "copy")))
            if path == "/api/monitor_add":
                return self._json(controller.add_monitor(b.get("address", ""), b.get("name", "")))
            if path == "/api/monitor_remove":
                return self._json(controller.remove_monitor(b.get("address", "")))
            if path == "/api/monitor_toggle":
                return self._json(controller.toggle_monitor(b.get("address", "")))
            if path == "/api/monitor_refresh":
                return self._json(controller.refresh_monitor(b.get("address", "")))
            if path == "/api/copy_set":
                return self._json(controller.set_copy_target(b.get("address", "")))
            if path == "/api/copy_clear":
                return self._json(controller.clear_copy_target())
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"error": "not found"}, 404)

    def _send_file(self, full):
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_dir(self, root, rel, missing_msg):
        rel = rel or "index.html"
        safe = posixpath.normpath(rel).lstrip("/")
        full = os.path.join(root, safe)
        if not full.startswith(root) or not os.path.isfile(full):   # SPA fallback
            full = os.path.join(root, "index.html")
            if not os.path.isfile(full):
                return self._json({"error": missing_msg}, 404)
        return self._send_file(full)

    def _serve_static(self, path):
        # новый UI (прототип) на /v2 — из web/v2, боевой фронт на / не трогаем
        if path == "/v2" or path.startswith("/v2/"):
            return self._serve_dir(V2_DIST, path[len("/v2"):], "новый UI не собран (web/v2)")
        if path == "/":
            path = "/index.html"
        return self._serve_dir(WEB_DIST, path, "фронт не собран. cd web && npm install && npm run build "
                                               "(или npm run dev на :5173)")


def serve(host="127.0.0.1", port=8787):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"🌐 HL-copier API + UI: http://{host}:{port}")
    print(f"   (фронт-дев: cd web && npm run dev → http://localhost:5173)")
    httpd.serve_forever()
