import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core import worker_threads as wt
from core.worker_threads import ConnectionTestThread


class FakeClient:
    instances = []

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.closed = False
        self.result = FakeClient.result
        self.thread_name = None
        FakeClient.instances.append(self)

    async def test_connection(self):
        self.thread_name = threading.current_thread().name
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.result = (True, "Connected")
    monkeypatch.setattr(wt, "HAClient", FakeClient)
    return FakeClient


def run_thread(qtbot, thread):
    with qtbot.waitSignal(thread.finished, timeout=10000) as blocker:
        thread.start()
    thread.wait(5000)
    return blocker.args


def test_success_result_is_emitted(qtbot, fake_client):
    thread = ConnectionTestThread("http://ha", "tok")
    assert run_thread(qtbot, thread) == [True, "Connected"]
    assert not thread.isRunning()


def test_failure_message_is_forwarded(qtbot, fake_client):
    fake_client.result = (False, "Invalid access token")
    assert run_thread(qtbot, ConnectionTestThread("http://ha", "bad")) == [False, "Invalid access token"]


def test_client_receives_credentials_and_is_closed(qtbot, fake_client):
    run_thread(qtbot, ConnectionTestThread("http://ha:8123", "secret"))
    client = fake_client.instances[0]
    assert (client.url, client.token) == ("http://ha:8123", "secret")
    assert client.closed is True


def test_work_runs_off_the_main_thread(qtbot, fake_client):
    run_thread(qtbot, ConnectionTestThread("http://ha", "tok"))
    assert fake_client.instances[0].thread_name != threading.main_thread().name


def test_exception_is_reported_as_failure_and_client_still_closed(qtbot, fake_client):
    fake_client.result = RuntimeError("kaboom")
    assert run_thread(qtbot, ConnectionTestThread("http://ha", "tok")) == [False, "kaboom"]
    assert fake_client.instances[0].closed is True


def test_constructor_failure_inside_thread_is_reported(qtbot, monkeypatch):
    def broken(url, token):
        raise ValueError("bad url")

    monkeypatch.setattr(wt, "HAClient", broken)
    assert run_thread(qtbot, ConnectionTestThread("x", "y")) == [False, "bad url"]


def test_thread_can_be_started_again_after_finishing(qtbot, fake_client):
    thread = ConnectionTestThread("http://ha", "tok")
    run_thread(qtbot, thread)
    assert run_thread(qtbot, thread) == [True, "Connected"]
    assert len(fake_client.instances) == 2


@pytest.fixture
def http_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            code = 200 if self.headers.get("Authorization") == "Bearer good" else 401
            self.send_response(code)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_real_client_against_local_server_accepts_valid_token(qtbot, http_server):
    url, seen = http_server
    assert run_thread(qtbot, ConnectionTestThread(url, "good")) == [True, "Connected"]
    assert seen == [("/api/", "Bearer good")]


def test_real_client_against_local_server_rejects_bad_token(qtbot, http_server):
    url, _ = http_server
    assert run_thread(qtbot, ConnectionTestThread(url, "bad")) == [False, "Invalid access token"]


def test_real_client_reports_unreachable_host(qtbot):
    ok, message = run_thread(qtbot, ConnectionTestThread("http://127.0.0.1:1", "tok"))
    assert ok is False and message.startswith("Connection error:")
