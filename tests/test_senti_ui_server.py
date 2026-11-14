import http.client
import json
import queue
import threading
import time

import pytest

from senti.events import make_event
from senti.ui.server import MAX_BODY_BYTES, SentiConsole, create_server, serve_in_thread


class FakeStore:
    def __init__(self):
        self.memories = {
            "m1": {"memory_id": "m1", "namespace": "preferences", "memory_type": "preference",
                   "payload": {"text": "Prefers dark mode"}, "source": "user",
                   "sensitivity": "normal", "confidence": 1.0, "updated_at": "2026-01-02"},
            "m2": {"memory_id": "m2", "namespace": "project", "memory_type": "fact",
                   "payload": {"text": "Works on SENTI"}, "source": "user",
                   "sensitivity": "normal", "confidence": 1.0, "updated_at": "2026-01-01"},
        }

    def search_memories(self, query="", *, namespace="personal", limit=20, include_sensitive=False):
        assert include_sensitive is False
        return [dict(m) for m in self.memories.values() if m["namespace"] == namespace][:limit]

    def forget_memory(self, memory_id):
        return self.memories.pop(memory_id, None) is not None


class FakeHost:
    def __init__(self):
        self.store = FakeStore()
        self.emergency_stop = False
        self.event_sink = None
        self.conversations = 0

    def runtime_manifest(self):
        return {"product": "SENTI", "resolved_model_tag": "SENTI:latest", "ollama_status": "connected",
                "model_installed": True, "database_status": "available",
                "policy": {"emergency_stop": self.emergency_stop,
                           "mutations_enabled": not self.emergency_stop},
                "providers": [{"name": "a", "available": True}, {"name": "b", "available": False}]}

    def new_conversation(self):
        self.conversations += 1
        return f"conv-{self.conversations}"


class FakeService:
    def __init__(self, host):
        self.host = host
        self.release = threading.Event()
        self.release.set()
        self.calls = []

    def send_message(self, text, *, conversation_id=None):
        self.calls.append((text, conversation_id))
        sink = self.host.event_sink
        if sink:
            sink(make_event("state", "c1", state="investigating", detail="looking"))
            sink(make_event("tool", "c1", tool="senti_probe", phase="executed",
                            status="succeeded", summary="ok", risk="read_only"))
        assert self.release.wait(5)
        if text == "boom":
            raise RuntimeError("model exploded")
        return {"conversation_id": "c1", "response": f"Done, sir. ({text})", "model": "SENTI",
                "tool_events": [], "usage": {"elapsed_seconds": 0.1}}

    def set_emergency_stop(self, enabled, *, reason="host_operator"):
        self.host.emergency_stop = enabled
        return {"emergency_stop": enabled, "mutations_enabled": not enabled, "persisted": True}


@pytest.fixture()
def env():
    host = FakeHost()
    service = FakeService(host)
    console = SentiConsole(service)
    host.event_sink = console.event_sink
    server = create_server(console, port=0)
    serve_in_thread(server)
    yield console, service, server
    service.release.set()
    server.shutdown()
    server.server_close()


def request(server, method, path, body=None, *, token=True, host=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{server.port}"}
    if token:
        hdrs["Authorization"] = "Bearer " + (token if isinstance(token, str) else server.console.token)
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw
    return resp.status, payload, resp


class EventReader:
    def __init__(self, server):
        self.queue = queue.Queue()
        self.conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
        self.conn.request("GET", f"/api/events?token={server.console.token}",
                          headers={"Host": f"127.0.0.1:{server.port}"})
        self.resp = self.conn.getresponse()
        assert self.resp.status == 200
        assert self.resp.getheader("Content-Type").startswith("text/event-stream")
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for raw in self.resp:
                line = raw.decode().rstrip("\n")
                if line.startswith("data: "):
                    self.queue.put(json.loads(line[6:]))
        except Exception:
            pass

    def until(self, predicate, timeout=5):
        seen = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            seen.append(event)
            if predicate(event):
                return seen
        raise AssertionError(f"event not seen; got {seen}")

    def close(self):
        self.conn.close()


def wait_idle(console, timeout=5):
    deadline = time.monotonic() + timeout
    while console.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not console.busy


# ---- security ----------------------------------------------------------------------------

def test_token_is_long_and_required(env):
    console, _, server = env
    assert len(console.token) >= 43  # 32 random bytes, url-safe base64
    assert request(server, "GET", "/api/manifest", token=False)[0] == 401
    assert request(server, "GET", "/api/manifest", token="wrong")[0] == 401
    status, body, _ = request(server, "GET", "/api/manifest")
    assert status == 200 and body["product"] == "SENTI"
    status, _, _ = request(server, "GET", "/api/manifest", token=False,
                           headers={"X-SENTI-Token": console.token})
    assert status == 200


def test_query_token_only_accepted_for_event_stream(env):
    console, _, server = env
    assert request(server, "GET", f"/api/manifest?token={console.token}", token=False)[0] == 401


def test_host_header_enforced(env):
    _, _, server = env
    assert request(server, "GET", "/api/manifest", host="evil.example:80")[0] == 403
    assert request(server, "GET", "/api/manifest", host=f"evil.example:{server.port}")[0] == 403
    assert request(server, "GET", "/", host="127.0.0.1:1")[0] == 403
    assert request(server, "GET", "/api/manifest", host=f"localhost:{server.port}")[0] == 200


def test_cross_origin_rejected_without_cors(env):
    _, _, server = env
    status, _, resp = request(server, "POST", "/api/emergency-stop", {"enabled": True},
                              headers={"Origin": "http://evil.example"})
    assert status == 403
    assert resp.getheader("Access-Control-Allow-Origin") is None
    assert request(server, "GET", "/api/manifest", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    status, _, resp = request(server, "GET", "/api/manifest",
                              headers={"Origin": f"http://127.0.0.1:{server.port}"})
    assert status == 200 and resp.getheader("Access-Control-Allow-Origin") is None
    assert request(server, "OPTIONS", "/api/chat")[0] == 405


def test_body_limit_and_content_type(env):
    _, _, server = env
    big = json.dumps({"text": "x" * (MAX_BODY_BYTES + 10)}).encode()
    assert request(server, "POST", "/api/chat", big)[0] == 413
    assert request(server, "POST", "/api/chat", b"{\"text\": \"hi\"}",
                   headers={"Content-Type": "text/plain"})[0] == 415
    assert request(server, "POST", "/api/chat", b"not json")[0] == 400


@pytest.mark.parametrize("path", [
    "/../server.py", "/static/../server.py", "/%2e%2e/server.py", "/static/%2e%2e/approvals.py",
    "/static/..%5cserver.py", "/..%2f..%2fpyproject.toml", "//etc/passwd", "/C:/Windows/win.ini",
])
def test_path_traversal_blocked(env, path):
    _, _, server = env
    status, body, _ = request(server, "GET", path, token=False)
    assert status == 404
    assert b"import" not in (body if isinstance(body, bytes) else json.dumps(body).encode())


def test_static_files_served_with_security_headers(env):
    _, _, server = env
    status, body, resp = request(server, "GET", "/", token=False)
    assert status == 200 and b"SENTI" in body
    csp = resp.getheader("Content-Security-Policy")
    assert "script-src 'self'" in csp and "http" not in csp
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    for name in ("/static/app.js", "/static/app.css", "/static/markdown.js"):
        assert request(server, "GET", name, token=False)[0] == 200
    assert b"https://" not in body  # no CDN


# ---- chat --------------------------------------------------------------------------------

def test_chat_returns_immediately_then_streams_events(env):
    console, service, server = env
    reader = EventReader(server)
    reader.until(lambda e: e["type"] == "snapshot")
    service.release.clear()
    started = time.monotonic()
    status, body, _ = request(server, "POST", "/api/chat", {"text": "hello"})
    assert status == 202 and len(body["request_id"]) == 32
    assert time.monotonic() - started < 1.0
    assert console.busy
    service.release.set()
    events = reader.until(lambda e: e["type"] == "state" and e["state"] == "completed")
    reader.close()
    kinds = [(e["type"], e.get("state")) for e in events]
    assert ("state", "listening") in kinds
    assert ("state", "investigating") in kinds
    assert ("tool", None) in kinds
    reply = next(e for e in events if e["type"] == "reply")
    assert reply["text"] == "Done, sir. (hello)"
    assert reply["request_id"] == body["request_id"]
    assert all(e.get("request_id") == body["request_id"] for e in events if e["type"] != "snapshot")
    wait_idle(console)
    assert console.conversation_id == "c1"


def test_chat_conflicts_while_busy(env):
    console, service, server = env
    service.release.clear()
    assert request(server, "POST", "/api/chat", {"text": "first"})[0] == 202
    status, body, _ = request(server, "POST", "/api/chat", {"text": "second"})
    assert status == 409 and "progress" in body["error"]
    assert request(server, "POST", "/api/new-conversation", {})[0] == 409
    service.release.set()
    wait_idle(console)
    assert request(server, "POST", "/api/chat", {"text": "third"})[0] == 202
    wait_idle(console)
    assert [c[0] for c in service.calls] == ["first", "third"]


def test_chat_failure_emits_error_and_failed_state(env):
    console, _, server = env
    reader = EventReader(server)
    assert request(server, "POST", "/api/chat", {"text": "boom"})[0] == 202
    events = reader.until(lambda e: e["type"] == "state" and e["state"] == "failed")
    reader.close()
    assert any(e["type"] == "error" and "model exploded" in e["message"] for e in events)
    wait_idle(console)


def test_chat_validates_input(env):
    _, _, server = env
    assert request(server, "POST", "/api/chat", {"text": "  "})[0] == 400
    assert request(server, "POST", "/api/chat", {"text": "hi", "conversation_id": 5})[0] == 400


def test_reply_synthesised_when_host_emits_nothing(env):
    console, service, server = env
    service.host.event_sink = None
    reader = EventReader(server)
    assert request(server, "POST", "/api/chat", {"text": "quiet"})[0] == 202
    events = reader.until(lambda e: e["type"] == "state" and e["state"] == "completed")
    reader.close()
    assert [e["text"] for e in events if e["type"] == "reply"] == ["Done, sir. (quiet)"]
    wait_idle(console)


# ---- approvals / policy / memory ---------------------------------------------------------

def test_approval_endpoints(env):
    console, _, server = env
    results = []
    worker = threading.Thread(target=lambda: results.append(
        console.broker.handler("senti_set_volume", {"level": 5}, "controlled",
                               {"current_state": "50%", "intended_state": "5%"})), daemon=True)
    worker.start()
    deadline = time.monotonic() + 3
    while not console.broker.pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    status, body, _ = request(server, "GET", "/api/approvals")
    assert status == 200 and len(body["approvals"]) == 1
    item = body["approvals"][0]
    assert item["preview"]["intended_state"] == "5%"
    approval_id = item["approval_id"]
    assert request(server, "POST", f"/api/approvals/{approval_id}", {"decision": "maybe"})[0] == 400
    assert request(server, "POST", "/api/approvals/unknown", {"decision": "approve"})[0] == 404
    status, body, _ = request(server, "POST", f"/api/approvals/{approval_id}", {"decision": "approve"})
    assert status == 200 and body["status"] == "approved"
    assert request(server, "POST", f"/api/approvals/{approval_id}", {"decision": "deny"})[0] == 409
    worker.join(2)
    assert results == [True]


def test_emergency_stop_toggles_and_denies_pending(env):
    console, service, server = env
    results = []
    worker = threading.Thread(target=lambda: results.append(
        console.broker.handler("senti_delete", {}, "high", {})), daemon=True)
    worker.start()
    deadline = time.monotonic() + 3
    while not console.broker.pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert request(server, "POST", "/api/emergency-stop", {"enabled": "yes"})[0] == 400
    status, body, _ = request(server, "POST", "/api/emergency-stop", {"enabled": True})
    assert status == 200 and body["emergency_stop"] is True and body["denied_approvals"] == 1
    worker.join(2)
    assert results == [False]
    assert service.host.emergency_stop is True
    _, manifest, _ = request(server, "GET", "/api/manifest")
    assert manifest["console"]["emergency_stop"] is True
    assert manifest["console"]["tool_count"] == 2 and manifest["console"]["available_tools"] == 1
    status, body, _ = request(server, "POST", "/api/emergency-stop", {"enabled": False})
    assert status == 200 and body["emergency_stop"] is False


def test_memory_list_and_forget(env):
    _, service, server = env
    status, body, _ = request(server, "GET", "/api/memories")
    assert status == 200 and [m["memory_id"] for m in body["memories"]] == ["m1", "m2"]
    status, body, _ = request(server, "GET", "/api/memories?namespace=project")
    assert [m["memory_id"] for m in body["memories"]] == ["m2"]
    assert request(server, "GET", "/api/memories?namespace=secrets")[0] == 400
    assert request(server, "DELETE", "/api/memories/m1")[0] == 200
    assert "m1" not in service.host.store.memories
    assert request(server, "DELETE", "/api/memories/m1")[0] == 404


def test_new_conversation(env):
    console, _, server = env
    status, body, _ = request(server, "POST", "/api/new-conversation", {})
    assert status == 200 and body["conversation_id"] == "conv-1"
    assert console.conversation_id == "conv-1"


def test_event_hub_drops_oldest_when_client_is_slow():
    from senti.ui.server import EventHub

    hub = EventHub(queue_size=3)
    q = hub.subscribe()
    for i in range(10):
        hub.publish(str(i))
    assert [q.get_nowait() for _ in range(3)] == ["7", "8", "9"]
    hub.close()
    assert q.get_nowait() is None


def test_port_fallback_skips_busy_port():
    console = SentiConsole(None)
    first = create_server(console, port=0)
    try:
        second = create_server(console, port=first.port, attempts=5)
        try:
            assert second.port != first.port
        finally:
            second.server_close()
    finally:
        first.server_close()


def test_main_module_has_no_shell_surface():
    import senti.__main__ as launcher

    assert callable(launcher.main) and callable(launcher.open_window)
