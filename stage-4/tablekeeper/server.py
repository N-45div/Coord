"""HTTP transport: routing, body framing and JSON responses for the handlers in api.py."""
from __future__ import annotations

import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import ui
from .api import Api, Request
from .errors import ApiError
from .jsonio import dumps

MAX_BODY = 64 * 1024 * 1024

# (method, path template, handler name). `{name}` matches one percent-decoded segment.
ROUTES = [
    ("GET", "/health", "health"),
    ("POST", "/_test/reset", "reset"),
    ("GET", "/_test/export", "export"),
    ("POST", "/_test/import", "import_"),
    ("POST", "/auth/signup", "signup"),
    ("POST", "/auth/login", "login"),
    ("GET", "/restaurants", "restaurants"),
    ("GET", "/restaurants/{id}", "restaurant"),
    ("GET", "/availability", "availability"),
    ("POST", "/reservations", "create_reservation"),
    ("GET", "/reservations", "list_reservations"),
    ("GET", "/reservations/{reference}", "get_reservation"),
    ("PATCH", "/reservations/{reference}", "amend_reservation"),
    ("POST", "/reservations/{reference}/cancel", "cancel_reservation"),
    ("POST", "/reservation-moves", "move_reservations"),
    ("GET", "/reservations/{reference}/history", "reservation_history"),
    ("GET", "/reservations/{reference}/decision", "reservation_decision"),
    ("GET", "/restaurants/{id}/policies", "policies"),
    ("POST", "/restaurants/{id}/policies", "publish_policy"),
    ("POST", "/series", "create_series"),
    ("GET", "/series/{id}", "get_series"),
]
_COMPILED = [(method, template.split("/")[1:], name) for method, template, name in ROUTES]


def match(method: str, segments: list[str]):
    """(handler name, path params) for a request, or None. A wrong method is a 404 (A-14)."""
    for route_method, parts, name in _COMPILED:
        if route_method != method or len(parts) != len(segments):
            continue
        params = {}
        for part, segment in zip(parts, segments):
            if part.startswith("{"):
                if not segment:
                    break
                params[part[1:-1]] = segment
            elif part != segment:
                break
        else:
            return name, params
    return None


class BadFraming(Exception):
    pass


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "tablekeeper"
        sys_version = ""
        timeout = 120  # seconds an idle keep-alive connection is held

        def __getattr__(self, name: str):
            # Every HTTP method goes through one dispatcher, so none ends in 501.
            if name.startswith("do_"):
                return self._dispatch
            raise AttributeError(name)

        def log_message(self, format: str, *args) -> None:  # quiet access log
            pass

        def send_error(self, code: int, message: str | None = None, explain: str | None = None):
            # Protocol-level failures (bad request line, oversized headers) keep §5's body.
            self.close_connection = True
            self._send(code, {"error": {"code": "not_found" if code == 404 else "malformed_request",
                                        "message": message or "bad request"}})

        def _read_body(self) -> bytes:
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                return self._read_chunked()
            length = self.headers.get("Content-Length")
            if length is None:
                return b""
            if not length.strip().isdigit() or int(length) > MAX_BODY:
                raise BadFraming("bad Content-Length")
            return self.rfile.read(int(length))

        def _read_chunked(self) -> bytes:
            chunks, total = [], 0
            while True:
                size_line = self.rfile.readline(1024).split(b";")[0].strip()
                try:
                    size = int(size_line, 16)
                except ValueError:
                    raise BadFraming("bad chunk size") from None
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass  # trailers
                    return b"".join(chunks)
                total += size
                if total > MAX_BODY:
                    raise BadFraming("body too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(1024)

        def _dispatch(self) -> None:
            try:
                body = self._read_body()
            except BadFraming as exc:
                self.close_connection = True
                self._send(400, ApiError(400, "malformed_request", str(exc)).body())
                return
            url = urlsplit(self.path)
            page = _page(url.path, api) if self.command in ("GET", "HEAD") else None
            if page is not None:
                self._send_asset(page)
                return
            segments = [unquote(s) for s in url.path.split("/")[1:]]
            route = match(self.command, segments)
            try:
                if route is None:
                    raise ApiError(404, "not_found", "no such endpoint")
                name, params = route
                query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
                request = Request(
                    method=self.command, path=unquote(url.path), params=params, query=query,
                    headers={k.lower(): _header_text(v) for k, v in self.headers.items()},
                    body=body)
                status, payload = getattr(api, name)(request)
            except ApiError as exc:
                status, payload = exc.status, exc.body()
            except OverflowError:  # date arithmetic beyond datetime's range: an invalid value
                status, payload = 422, ApiError(422, "validation_failed", "value out of range").body()
            except Exception:  # a defect, never an expected outcome
                traceback.print_exc(file=sys.stderr)
                status, payload = 500, {"error": {"code": "internal_error",
                                                  "message": "unexpected server error"}}
            self._send(status, payload)

        def _send_asset(self, page: ui.Asset) -> None:
            try:
                self.send_response(200)
                self.send_header("Content-Type", page.content_type)
                self.send_header("Content-Length", str(len(page.body)))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", _CSP)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(page.body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _send(self, status: int, payload) -> None:
            data = b"" if payload is None else dumps(payload)
            try:
                self.send_response(status)
                if payload is not None:
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                if self.close_connection:
                    self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    return Handler


# The page uses only its own script, stylesheet and inline-SVG images.
_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _page(path: str, api: Api) -> ui.Asset | None:
    """The screen shell or static asset for a browser route, None for API paths."""
    if path in ui.SCREENS:
        return ui.screen(api.restaurant_summaries())
    if path.startswith("/static/"):
        return ui.asset(unquote(path[len("/static/"):]))
    return None


def _header_text(value: str) -> str:
    # http.server decodes header bytes as Latin-1; recover UTF-8 text where it was UTF-8.
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512

    def handle_error(self, request, client_address) -> None:
        # A client dropping its connection is routine (timeouts, aborted fetches); log the rest.
        if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            super().handle_error(request, client_address)
