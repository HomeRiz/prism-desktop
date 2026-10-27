import asyncio
import datetime
import ssl

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from core import token_storage
from core import ha_websocket as hw
from core.ha_client import HAClient


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "cfg"
    directory.mkdir()

    def fake_get_config_path(filename="config.json"):
        return directory / filename

    monkeypatch.setattr("core.config_manager.get_config_path", fake_get_config_path)
    monkeypatch.setattr("core.token_storage.get_config_path", fake_get_config_path)
    return directory


@pytest.fixture
def no_keyring(monkeypatch):
    monkeypatch.setattr(token_storage, "_keyring_probed", True)
    monkeypatch.setattr(token_storage, "_keyring_available", False)
    token_storage._derive_key.cache_clear()
    yield
    token_storage._derive_key.cache_clear()


class FakeKeyring:
    def __init__(self):
        self.store = {}
        self.fail_set = False
        self.fail_get = False

    def get_keyring(self):
        return self

    def set_password(self, service, key, value):
        if self.fail_set:
            raise RuntimeError("keyring write denied")
        self.store[(service, key)] = value

    def get_password(self, service, key):
        if self.fail_get:
            raise RuntimeError("keyring read denied")
        return self.store.get((service, key))

    def delete_password(self, service, key):
        if (service, key) not in self.store:
            raise RuntimeError("no entry")
        del self.store[(service, key)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(token_storage, "keyring", fake)
    monkeypatch.setattr(token_storage, "_keyring_probed", True)
    monkeypatch.setattr(token_storage, "_keyring_available", True)
    token_storage._derive_key.cache_clear()
    yield fake
    token_storage._derive_key.cache_clear()


@pytest.fixture
def fixed_seed(monkeypatch):
    seed = {"value": b"machine-seed-one"}
    monkeypatch.setattr(token_storage, "_get_machine_seed", lambda: seed["value"])
    token_storage._derive_key.cache_clear()
    yield seed
    token_storage._derive_key.cache_clear()


@pytest.fixture
async def start_server():
    servers = []

    async def start(app: web.Application) -> TestServer:
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        servers.append(server)
        return server

    yield start
    for server in servers:
        await server.close()


def _make_ha_app(log):
    async def record(request):
        log.append((request.method, request.path_qs, dict(request.headers), await request.read()))

    async def api_root(request):
        await record(request)
        return web.json_response({"message": "API running."})

    async def states(request):
        await record(request)
        return web.json_response([{"entity_id": "light.a", "state": "on"}])

    async def config(request):
        await record(request)
        return web.json_response({"version": "2024.1"})

    async def state(request):
        await record(request)
        eid = request.match_info["eid"]
        if eid == "sensor.missing":
            return web.json_response({"message": "Entity not found."}, status=404)
        if eid == "sensor.bad":
            return web.Response(text="<html>not json</html>", content_type="application/json")
        return web.json_response({"entity_id": eid, "state": "on", "attributes": {"entity_picture": "/api/img/1"}})

    async def service(request):
        await record(request)
        if request.match_info["service"] == "fail":
            return web.Response(status=500)
        return web.json_response([])

    async def forecast(request):
        await record(request)
        body = await request.json()
        return web.json_response({"service_response": {body["entity_id"]: {"forecast": [{"temp": 1}]}}})

    async def camera(request):
        await record(request)
        return web.Response(body=b"\xff\xd8jpeg")

    async def img(request):
        await record(request)
        return web.Response(body=b"PNGDATA")

    async def redirect(request):
        await record(request)
        raise web.HTTPFound("http://127.0.0.1:1/steal")

    async def big(request):
        await record(request)
        return web.Response(body=b"x" * (HAClient.MAX_MEDIA_BYTES + 1))

    async def teapot(request):
        await record(request)
        return web.Response(status=418)

    app = web.Application()
    app.router.add_get("/api/", api_root)
    app.router.add_get("/api/states", states)
    app.router.add_get("/api/config", config)
    app.router.add_get("/api/states/{eid}", state)
    app.router.add_post("/api/services/{domain}/{service}", service)
    app.router.add_post("/api/services/weather/get_forecasts", forecast)
    app.router.add_get("/api/camera_proxy/{eid}", camera)
    app.router.add_get("/api/img/1", img)
    app.router.add_get("/api/redirect", redirect)
    app.router.add_get("/api/big", big)
    app.router.add_get("/api/teapot", teapot)
    return app


@pytest.fixture
def make_ha_app():
    return _make_ha_app


@pytest.fixture
def self_signed(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


class WsScript:
    def __init__(self):
        self.token = "good-token"
        self.hello = "auth_required"
        self.received = []
        self.binary = []
        self.to_send = []
        self.expected_subs = 2
        self.close_after = lambda connection: True
        self.on_message = None
        self.connections = 0


@pytest.fixture
def ws_script():
    return WsScript()


@pytest.fixture
async def ws_url(start_server, ws_script):
    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        ws_script.connections += 1
        mine = ws_script.connections
        if ws_script.hello is None:
            await ws.receive()
            return ws
        await ws.send_json({"type": ws_script.hello})
        if ws_script.hello != "auth_required":
            await ws.receive()
            return ws
        auth = await ws.receive_json()
        ws_script.received.append(auth)
        if auth.get("access_token") != ws_script.token:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid password"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok"})
        subs = 0
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                ws_script.binary.append(msg.data)
                continue
            if msg.type != WSMsgType.TEXT:
                continue
            data = msg.json()
            ws_script.received.append(data)
            if ws_script.on_message:
                await ws_script.on_message(ws, data)
            if data.get("type") in ("subscribe_events", "mobile_app/push_notification_channel"):
                subs += 1
                if subs == ws_script.expected_subs:
                    for item in ws_script.to_send:
                        if isinstance(item, str):
                            await ws.send_str(item)
                        else:
                            await ws.send_json(item)
                    if ws_script.close_after(mine):
                        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/api/websocket", handler)
    server = await start_server(app)
    return f"http://127.0.0.1:{server.port}"


_REAL_SLEEP = asyncio.sleep
REAL_WAIT_FOR = asyncio.wait_for


class _Recorder:
    def __init__(self, client):
        self.connected = 0
        self.disconnected = 0
        self.errors = []
        self.states = []
        self.notifications = []
        client.connected.connect(lambda: setattr(self, "connected", self.connected + 1))
        client.disconnected.connect(lambda: setattr(self, "disconnected", self.disconnected + 1))
        client.error.connect(self.errors.append)
        client.state_changed.connect(lambda eid, st: self.states.append((eid, st)))
        client.notification_received.connect(self.notifications.append)


@pytest.fixture
def fast_sleep(monkeypatch):
    async def quick(delay, *args):
        await _REAL_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", quick)


@pytest.fixture
def fast_timeouts(monkeypatch):
    async def capped(aw, timeout=None):
        return await REAL_WAIT_FOR(aw, 0.5 if timeout else timeout)

    monkeypatch.setattr(hw.asyncio, "wait_for", capped)

@pytest.fixture
def make_recorder():
    return _Recorder
