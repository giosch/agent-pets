"""Loopback-only HTTP host. The display stream carries public activity metadata."""
import hmac
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty
import secrets
import sqlite3
import threading
import time
from socketserver import TCPServer
from urllib.parse import parse_qs, urlsplit

from .adapters import Signal
from .model import Habitat
from .themes import POSES, Themes

WEB = Path(__file__).with_name("web")
STATIC = {"/": "index.html", "/habitat.css": "habitat.css", "/habitat.js": "habitat.js",
          "/favicon.svg": "favicon.svg", "/connections": "connections.html", "/connections.js": "connections.js"}


class HabitatServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, habitat: Habitat, themes: Themes, *, demo=False, directory=None):
        self.habitat = habitat
        self.themes = themes
        self.key = secrets.token_urlsafe(32)
        self.management = secrets.token_urlsafe(32)
        self.settings_lock = threading.Lock()
        self.demo = demo
        self.directory = directory
        self.inbox_lock = threading.Lock()
        self.next_drain = 0
        super().__init__(("127.0.0.1", port), Handler)

    def drain(self):
        if self.directory is not None and not self.demo:
            from .inbox import drain
            with self.inbox_lock:
                drain(self.directory, self.habitat)

    def service_actions(self):
        if time.monotonic() >= self.next_drain:
            self.next_drain = time.monotonic() + 3
            try:
                self.drain()
            except (OSError, sqlite3.OperationalError):
                # A transient writer conflict leaves unacknowledged events in the inbox.
                pass

    def server_bind(self):
        # HTTPServer normally reverse-resolves this address. The habitat always
        # binds a numeric loopback address and can start with DNS unavailable.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _local(self) -> bool:
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.send_error(HTTPStatus.FORBIDDEN)
            return False
        return True

    def _send(self, data: bytes, content_type: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        if content_type == "image/svg+xml":
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
        else:
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._local():
            return
        url = urlsplit(self.path)
        if url.path == "/v1/events":
            self._events(parse_qs(url.query).get("feed") == ["1"])
        elif url.path == "/v1/snapshot":
            self._send(json.dumps(self.server.habitat.snapshot()).encode(), "application/json")
        elif url.path == "/v1/connections" and self.server.directory and not self.server.demo:
            from .desktop import integration, login
            from .installation import installed_version
            from .adapters import SOURCES
            host = self.server
            with host.habitat.lock:
                count = len(host.habitat.listeners)
                last = dict(host.habitat.last_events)
            data = {"displays": count, "login": login(host.directory), "version": installed_version(),
                    "agents": {s: {**integration(s, host.directory), "last": last.get(s)} for s in SOURCES}}
            self._send(json.dumps(data).encode(), "application/json")
        elif url.path == "/v1/themes":
            data = {"packs": self.server.themes.catalog(), "demo": self.server.demo}
            self._send(json.dumps(data).encode(), "application/json")
        elif url.path in STATIC:
            path = WEB / STATIC[url.path]
            content_type = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(path)[0]
            self._send(path.read_bytes(), content_type or "application/octet-stream")
        elif url.path.startswith("/art/"):
            try:
                _, _, kind, pack_id, pose = url.path.split("/")
                if pose not in POSES:
                    raise ValueError
                variant = int(parse_qs(url.query).get("variant", [0])[0])
                if not 0 <= variant <= 2**53 - 1:
                    raise ValueError
                pack = self.server.themes.packs[kind, pack_id]
                self._send(pack.svg(pose, variant), "image/svg+xml")
            except (KeyError, ValueError):
                self.send_error(404)
        else:
            self.send_error(404)

    def _events(self, include_feed):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.connection.settimeout(15)
        queue = self.server.habitat.subscribe(include_feed)
        try:
            while True:
                try:
                    message = queue.get(timeout=5)
                    frame = f"data: {json.dumps(message, separators=(',', ':'))}\n\n"
                except Empty:
                    frame = ": heartbeat\n\n"
                self.wfile.write(frame.encode())
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.server.habitat.unsubscribe(queue)

    def _manage(self):
        from .desktop import codex_trust, login, probe
        from .installation import check_updates, uninstall_from_settings
        from .hooks import configure
        host = self.server
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(),
                                   ("Bearer " + host.management).encode()):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError("Invalid request")
            data = json.loads(self.rfile.read(length))
            action, source = data["action"], data.get("source")
            with host.settings_lock:
                result = {}
                if action in {"install", "remove", "probe"} and source in {"claude", "codex"}:
                    if action != "probe":
                        configure(source, host.directory, remove=action == "remove")
                    if action != "remove":
                        result["verified"] = probe(source, host.directory)
                elif action == "trust":
                    result["trust"] = codex_trust(host.directory)
                elif action == "login" and isinstance(data.get("enabled"), bool):
                    result["login"] = login(host.directory, data["enabled"])
                elif action == "uninstall" and isinstance(data.get("purge"), bool):
                    uninstall_from_settings(host.directory, data["purge"])
                elif action == "updates":
                    result = check_updates()
                elif action == "finish":
                    (host.directory / "setup-complete").touch()
                elif action == "stop":
                    self._send(b"{}", "application/json")
                    host.shutdown()
                    return
                else:
                    raise ValueError("Unknown action")
            self._send(json.dumps(result).encode(), "application/json")
        except (ValueError, OSError, TypeError, KeyError) as error:
            self._send(json.dumps({"error": str(error)}).encode(), "application/json", 400)

    def do_POST(self):
        if not self._local():
            return
        if self.path == "/manage" and self.server.directory and not self.server.demo:
            self._manage()
            return
        if self.path not in {"/internal/activity", "/internal/drain", "/internal/stop", "/internal/ping"} or self.server.demo:
            self.send_error(404)
            return
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(),
                                   ("Bearer " + self.server.key).encode()):
            self.send_error(403)
            return
        if self.path == "/internal/ping":
            self._send(b'{"app":"clawd-tank"}', "application/json")
            return
        if self.path == "/internal/stop":
            self._send(b"", "application/json", 204)
            self.server.shutdown()
            return
        if self.path == "/internal/drain":
            try:
                self.server.drain()
            except (OSError, sqlite3.OperationalError):
                self.send_error(503, "Activity is queued")
                return
            self._send(b"", "application/json", 204)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= 16384 or self.headers.get_content_type() != "application/json":
                raise ValueError
            signal = Signal(**json.loads(self.rfile.read(length)))
        except (TypeError, ValueError):
            self.send_error(400)
            return
        try:
            self.server.habitat.apply(signal)
        except OSError:
            self.send_error(503, "Could not persist session")
            return
        self._send(b"", "application/json", 204)
