"""Loopback-only HTTP server for the SENTI desktop console (Python stdlib only).

Security model
--------------
* Bound to 127.0.0.1 only; the Host header must name 127.0.0.1:<port> or localhost:<port>
  (defeats DNS rebinding).
* A random per-launch token travels in the URL fragment (never sent to the server by the
  browser) and is then presented as ``Authorization: Bearer`` / ``X-SENTI-Token`` on every API
  call. ``EventSource`` cannot set headers, so ``/api/events`` also accepts ``?token=``.
* Any request carrying a foreign ``Origin`` or ``Sec-Fetch-Site: cross-site`` is rejected and
  no CORS headers are ever sent.
* JSON bodies are capped at 64 KiB. Static files are served from an allow-list built from the
  package's ``static`` directory, so path traversal cannot reach anything else.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from senti.events import make_event
from senti.ui.approvals import ApprovalAlreadyDecided, ApprovalBroker, UnknownApproval

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8777
PORT_ATTEMPTS = 20
MAX_BODY_BYTES = 64 * 1024
MEMORY_NAMESPACES = ("preferences", "personal", "project", "technical", "procedures")
CLIENT_QUEUE_SIZE = 1024
SSE_KEEPALIVE_SECONDS = 15.0

_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'")


class EventHub:
    """Fan host events out to every SSE client with a bounded, drop-oldest queue each."""

    def __init__(self, queue_size: int = CLIENT_QUEUE_SIZE):
        self._queue_size = queue_size
        self._lock = threading.Lock()
        self._clients: set[queue.Queue] = set()
        self._closed = False

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            if self._closed:
                q.put_nowait(None)
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def publish(self, event: Any) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            self._offer(q, event)

    @staticmethod
    def _offer(q: queue.Queue, item: Any) -> None:
        while True:
            try:
                q.put_nowait(item)
                return
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            clients = list(self._clients)
        for q in clients:
            self._offer(q, None)


class SentiConsole:
    """Application state shared by all request handlers."""

    def __init__(self, service: Any = None, *, broker: ApprovalBroker | None = None,
                 token: str | None = None):
        self.hub = EventHub()
        self.broker = broker or ApprovalBroker()
        if self.broker.event_sink is None:
            self.broker.event_sink = self.event_sink
        self.token = token or secrets.token_urlsafe(32)
        self.service = service
        self._busy = threading.Lock()
        self._state_lock = threading.Lock()
        self._request_id: str | None = None
        self._request_started: float | None = None
        self._seen_types: set[str] = set()
        self.state = "idle"
        self.conversation_id: str | None = None
        self.last_error: str | None = None

    # -- wiring ----------------------------------------------------------------------------
    def attach(self, service: Any) -> None:
        self.service = service

    @property
    def host(self) -> Any:
        return getattr(self.service, "host", None)

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def event_sink(self, event: dict[str, Any]) -> None:
        """Host-facing sink: tag with the active request and broadcast."""
        if not isinstance(event, dict):
            return
        event = dict(event)
        with self._state_lock:
            if self._request_id and "request_id" not in event:
                event["request_id"] = self._request_id
            if self._request_id:
                self._seen_types.add(str(event.get("type")))
            if event.get("type") == "state" and isinstance(event.get("state"), str):
                self.state = event["state"]
            if event.get("conversation_id"):
                self.conversation_id = event["conversation_id"]
        try:
            payload = json.dumps(event, ensure_ascii=False, default=str, allow_nan=False)
        except (TypeError, ValueError):
            return
        self.hub.publish(payload)

    def emit(self, event_type: str, **fields: Any) -> None:
        self.event_sink(make_event(event_type, self.conversation_id, **fields))

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            started = self._request_started
            return {
                "type": "snapshot", "state": self.state, "busy": self.busy,
                "request_id": self._request_id, "conversation_id": self.conversation_id,
                "elapsed": round(time.monotonic() - started, 1) if started else None,
                "approvals": self.broker.pending(),
            }

    # -- operations ------------------------------------------------------------------------
    def start_chat(self, text: str, conversation_id: str | None) -> str | None:
        """Start a worker for one message; ``None`` when a request is already active."""
        if not self._busy.acquire(blocking=False):
            return None
        request_id = uuid4().hex
        with self._state_lock:
            self._request_id = request_id
            self._request_started = time.monotonic()
            self._seen_types = set()
            if conversation_id:
                self.conversation_id = conversation_id
        self.broker.conversation_id = self.conversation_id
        self.emit("state", state="listening", detail="Request accepted")
        worker = threading.Thread(target=self._run_chat, args=(request_id, text, conversation_id),
                                  name=f"senti-chat-{request_id[:8]}", daemon=True)
        try:
            worker.start()
        except Exception:
            self._finish()
            raise
        return request_id

    def _run_chat(self, request_id: str, text: str, conversation_id: str | None) -> None:
        try:
            self.emit("state", state="processing", detail="Consulting the local model")
            result = self.service.send_message(text, conversation_id=conversation_id)
            if not isinstance(result, dict):
                raise TypeError("host returned a non-dict reply")
            cid = result.get("conversation_id")
            if isinstance(cid, str):
                with self._state_lock:
                    self.conversation_id = cid
            if "tool" not in self._seen_types:
                for item in result.get("tool_events") or []:
                    if isinstance(item, dict):
                        self.emit("tool", tool=str(item.get("tool", "unknown")), phase="executed",
                                  status=str(item.get("status", "unknown")),
                                  summary=str(item.get("summary", ""))[:500],
                                  risk=str(item.get("risk", "")))
            if "reply" not in self._seen_types:
                self.emit("reply", text=str(result.get("response", "")),
                          model=str(result.get("model", "")), usage=result.get("usage") or {})
            self.last_error = None
            self.emit("state", state="completed", detail="Reply delivered")
        except Exception as exc:  # noqa: BLE001 - reported to the operator, never swallowed.
            message = f"{type(exc).__name__}: {str(exc)[:400]}"
            self.last_error = message
            self.emit("error", message=message)
            self.emit("state", state="failed", detail=message)
        finally:
            self._finish()

    def _finish(self) -> None:
        with self._state_lock:
            self._request_id = None
            self._request_started = None
        if self._busy.locked():
            self._busy.release()

    def manifest(self) -> dict[str, Any]:
        host = self.host
        manifest = host.runtime_manifest() if host is not None else {}
        providers = manifest.get("providers") or []
        policy = manifest.get("policy") or {}
        manifest["console"] = {
            "busy": self.busy, "state": self.state, "conversation_id": self.conversation_id,
            "tool_count": len(providers),
            "available_tools": sum(1 for p in providers if isinstance(p, dict) and p.get("available")),
            "emergency_stop": bool(policy.get("emergency_stop", False)),
            "pending_approvals": len(self.broker.pending()),
            "sse_clients": self.hub.client_count, "last_error": self.last_error,
        }
        return manifest

    def set_emergency_stop(self, enabled: bool) -> dict[str, Any]:
        result = self.service.set_emergency_stop(enabled, reason="console_operator")
        denied = self.broker.deny_all("emergency_stop") if enabled else 0
        self.emit("policy", emergency_stop=enabled, denied_approvals=denied)
        if enabled:
            self.emit("state", state="requires_attention", detail="Emergency stop engaged")
        elif not self.busy:
            self.emit("state", state="idle", detail="Emergency stop released")
        return {**(result if isinstance(result, dict) else {}), "denied_approvals": denied}

    def list_memories(self, namespace: str | None) -> list[dict[str, Any]]:
        store = self.host.store
        namespaces = (namespace,) if namespace else MEMORY_NAMESPACES
        rows: list[dict[str, Any]] = []
        for ns in namespaces:
            for row in store.search_memories(query="", namespace=ns, limit=50,
                                             include_sensitive=False):
                rows.append({
                    "memory_id": row.get("memory_id"), "namespace": row.get("namespace", ns),
                    "memory_type": row.get("memory_type"), "payload": row.get("payload"),
                    "source": row.get("source"), "sensitivity": row.get("sensitivity"),
                    "confidence": row.get("confidence"), "updated_at": row.get("updated_at"),
                })
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        return rows

    def forget_memory(self, memory_id: str) -> bool:
        removed = bool(self.host.store.forget_memory(memory_id))
        if removed:
            self.emit("memory", action="forgotten", count=1, summary="Memory removed by operator")
        return removed

    def new_conversation(self) -> str | None:
        if self.busy:
            return None
        cid = self.host.new_conversation()
        with self._state_lock:
            self.conversation_id = cid
        self.emit("state", state="idle", detail="New conversation")
        prime = getattr(self.host, "prime", None)
        if callable(prime):
            # Pre-evaluate the fixed identity/tool prefix so the first reply is fast.
            threading.Thread(target=prime, args=(cid,), name="senti-prime", daemon=True).start()
        return cid


class _HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _static_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    if STATIC_DIR.is_dir():
        for path in STATIC_DIR.rglob("*"):
            if path.is_file():
                files["/" + path.relative_to(STATIC_DIR).as_posix()] = path
    return files


def make_handler(console: SentiConsole) -> type[BaseHTTPRequestHandler]:
    static = _static_files()

    class Handler(BaseHTTPRequestHandler):
        server_version = "SENTI"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        # -- plumbing --------------------------------------------------------------------
        @property
        def port(self) -> int:
            return int(self.server.server_address[1])

        def _base_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("Cache-Control", "no-store")

        def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self._base_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self.close_connection = True
            self._json(status, {"error": message})

        def _check_host_and_origin(self) -> None:
            allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
            if (self.headers.get("Host") or "").strip().lower() not in allowed_hosts:
                raise _HttpError(HTTPStatus.FORBIDDEN, "host not allowed")
            origin = self.headers.get("Origin")
            if origin is not None and origin.strip().lower() not in {
                    f"http://{h}" for h in allowed_hosts}:
                raise _HttpError(HTTPStatus.FORBIDDEN, "cross-origin request rejected")
            if (self.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
                raise _HttpError(HTTPStatus.FORBIDDEN, "cross-site request rejected")

        def _check_token(self, query: dict[str, list[str]], allow_query: bool = False) -> None:
            supplied = ""
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
            supplied = supplied or (self.headers.get("X-SENTI-Token") or "").strip()
            if not supplied and allow_query:
                supplied = (query.get("token") or [""])[0]
            if not supplied or not hmac.compare_digest(supplied.encode("utf-8"),
                                                       console.token.encode("utf-8")):
                raise _HttpError(HTTPStatus.UNAUTHORIZED, "missing or invalid token")

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get("Transfer-Encoding"):
                raise _HttpError(HTTPStatus.LENGTH_REQUIRED, "chunked bodies are not accepted")
            raw_length = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                raise _HttpError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from None
            if length < 0:
                raise _HttpError(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            if length > MAX_BODY_BYTES:
                # Drain a modest overflow so the client sees the 413 instead of a reset.
                if length <= 16 * MAX_BODY_BYTES:
                    self.rfile.read(length)
                raise _HttpError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
            if length == 0:
                return {}
            body = self.rfile.read(length)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise _HttpError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "expected application/json")
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _HttpError(HTTPStatus.BAD_REQUEST, "invalid JSON") from None
            if not isinstance(data, dict):
                raise _HttpError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
            return data

        def _dispatch(self) -> None:
            try:
                self._check_host_and_origin()
                parts = urlsplit(self.path)
                path = parts.path
                query = parse_qs(parts.query, keep_blank_values=True)
                if path.startswith("/api/"):
                    self._check_token(query, allow_query=(path == "/api/events"))
                    self._api(path, query)
                elif self.command in {"GET", "HEAD"}:
                    self._static(path)
                else:
                    raise _HttpError(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
            except _HttpError as exc:
                self._error(exc.status, exc.message)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True
            except Exception as exc:  # noqa: BLE001 - never leak a traceback to the client.
                try:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, type(exc).__name__)
                except OSError:
                    self.close_connection = True

        do_GET = do_HEAD = do_POST = do_DELETE = _dispatch

        def do_OPTIONS(self) -> None:
            self._error(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

        do_PUT = do_PATCH = do_OPTIONS

        # -- static ----------------------------------------------------------------------
        def _static(self, path: str) -> None:
            decoded = unquote(path)
            if decoded in {"", "/"}:
                decoded = "/index.html"
            elif decoded.startswith("/static/"):
                decoded = decoded[len("/static"):]
            target = static.get(decoded)
            if target is None or ".." in decoded or "\\" in decoded:
                raise _HttpError(HTTPStatus.NOT_FOUND, "not found")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in {"application/javascript"}:
                ctype += "; charset=utf-8"
            if target.suffix == ".js":
                ctype = "text/javascript; charset=utf-8"
            self._send_bytes(HTTPStatus.OK, target.read_bytes(), ctype)

        # -- api -------------------------------------------------------------------------
        def _api(self, path: str, query: dict[str, list[str]]) -> None:
            method = self.command
            segments = [unquote(s) for s in path.split("/")[2:]]
            route = segments[0] if segments else ""
            if console.service is None and route not in {"events"}:
                raise _HttpError(HTTPStatus.SERVICE_UNAVAILABLE, "host not ready")

            if route == "events" and len(segments) == 1 and method == "GET":
                return self._events()
            if route == "chat" and len(segments) == 1 and method == "POST":
                body = self._read_json()
                text = body.get("text")
                cid = body.get("conversation_id")
                if not isinstance(text, str) or not text.strip() or len(text) > 12_000:
                    raise _HttpError(HTTPStatus.BAD_REQUEST, "text must contain 1 to 12000 characters")
                if cid is not None and (not isinstance(cid, str) or not 1 <= len(cid) <= 64):
                    raise _HttpError(HTTPStatus.BAD_REQUEST, "conversation_id is invalid")
                request_id = console.start_chat(text, cid)
                if request_id is None:
                    raise _HttpError(HTTPStatus.CONFLICT, "a request is already in progress")
                return self._json(HTTPStatus.ACCEPTED, {"request_id": request_id})
            if route == "manifest" and len(segments) == 1 and method == "GET":
                return self._json(HTTPStatus.OK, console.manifest())
            if route == "state" and len(segments) == 1 and method == "GET":
                return self._json(HTTPStatus.OK, console.snapshot())
            if route == "approvals":
                if len(segments) == 1 and method == "GET":
                    return self._json(HTTPStatus.OK, {"approvals": console.broker.pending()})
                if len(segments) == 2 and method == "POST":
                    decision = self._read_json().get("decision")
                    if decision not in {"approve", "deny"}:
                        raise _HttpError(HTTPStatus.BAD_REQUEST, "decision must be approve or deny")
                    try:
                        item = console.broker.decide(segments[1], decision)
                    except UnknownApproval:
                        raise _HttpError(HTTPStatus.NOT_FOUND, "unknown approval") from None
                    except ApprovalAlreadyDecided as exc:
                        raise _HttpError(HTTPStatus.CONFLICT, f"approval already {exc.status}") from None
                    return self._json(HTTPStatus.OK, item)
            if route == "emergency-stop" and len(segments) == 1 and method == "POST":
                enabled = self._read_json().get("enabled")
                if not isinstance(enabled, bool):
                    raise _HttpError(HTTPStatus.BAD_REQUEST, "enabled must be a boolean")
                return self._json(HTTPStatus.OK, console.set_emergency_stop(enabled))
            if route == "memories":
                if len(segments) == 1 and method == "GET":
                    namespace = (query.get("namespace") or [""])[0].strip() or None
                    if namespace is not None and namespace not in MEMORY_NAMESPACES:
                        raise _HttpError(HTTPStatus.BAD_REQUEST, "unknown namespace")
                    return self._json(HTTPStatus.OK, {"memories": console.list_memories(namespace),
                                                      "namespaces": list(MEMORY_NAMESPACES)})
                if len(segments) == 2 and method == "DELETE":
                    memory_id = segments[1]
                    if not 1 <= len(memory_id) <= 64:
                        raise _HttpError(HTTPStatus.BAD_REQUEST, "memory_id is invalid")
                    if not console.forget_memory(memory_id):
                        raise _HttpError(HTTPStatus.NOT_FOUND, "unknown memory")
                    return self._json(HTTPStatus.OK, {"forgotten": memory_id})
            if route == "new-conversation" and len(segments) == 1 and method == "POST":
                self._read_json()
                cid = console.new_conversation()
                if cid is None:
                    raise _HttpError(HTTPStatus.CONFLICT, "a request is already in progress")
                return self._json(HTTPStatus.OK, {"conversation_id": cid})
            raise _HttpError(HTTPStatus.NOT_FOUND, "unknown endpoint")

        def _events(self) -> None:
            q = console.hub.subscribe()
            try:
                self.send_response(HTTPStatus.OK)
                self._base_headers()
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.close_connection = True
                self._sse(json.dumps(console.snapshot(), ensure_ascii=False, default=str))
                while True:
                    try:
                        item = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    if item is None:
                        return
                    self._sse(item)
            finally:
                console.hub.unsubscribe(q)

        def _sse(self, payload: str) -> None:
            lines = "".join(f"data: {line}\n" for line in payload.splitlines() or [""])
            self.wfile.write((lines + "\n").encode("utf-8"))
            self.wfile.flush()

    return Handler


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], console: SentiConsole):
        self.console = console
        super().__init__(address, make_handler(console))

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#token={self.console.token}"

    def shutdown(self) -> None:
        self.console.hub.close()
        super().shutdown()


def create_server(console: SentiConsole, port: int = DEFAULT_PORT,
                  attempts: int = PORT_ATTEMPTS) -> ConsoleServer:
    """Bind 127.0.0.1 on ``port`` or the next free port. ``port=0`` picks any free port."""
    if port == 0:
        return ConsoleServer(("127.0.0.1", 0), console)
    last_error: OSError | None = None
    for candidate in range(port, min(port + attempts, 65536)):
        try:
            return ConsoleServer(("127.0.0.1", candidate), console)
        except OSError as exc:
            last_error = exc
    raise OSError(f"no free port in {port}-{port + attempts - 1}") from last_error


def serve_in_thread(server: ConsoleServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="senti-console-http", daemon=True)
    thread.start()
    return thread
