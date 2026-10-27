import asyncio
import base64
import http.server
import io
import os
import ssl
import sys
import threading
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web
from aiohttp.test_utils import TestServer


def build_app():
    async def hello(request):
        return web.json_response({"ok": True, "auth": request.headers.get("Authorization", "")})

    async def echo_ws(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str("echo:" + msg.data)
        return ws

    async def missing(request):
        raise web.HTTPNotFound()

    app = web.Application()
    app.router.add_get("/hello", hello)
    app.router.add_get("/ws", echo_ws)
    app.router.add_get("/missing", missing)
    return app


@pytest.fixture
async def server():
    srv = TestServer(build_app(), host="127.0.0.1")
    await srv.start_server()
    yield srv
    await srv.close()


async def test_aiohttp_client_server_round_trip_with_headers(server):
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer t"}) as session:
        async with session.get(server.make_url("/hello")) as resp:
            assert resp.status == 200
            assert await resp.json() == {"ok": True, "auth": "Bearer t"}


async def test_aiohttp_dummy_cookie_jar_is_available_for_anonymous_sessions(server):
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        async with session.get(server.make_url("/hello")) as resp:
            assert resp.status == 200


async def test_aiohttp_websocket_round_trip_and_close(server):
    async with aiohttp.ClientSession() as session:
        ws = await session.ws_connect(str(server.make_url("/ws")).replace("http", "ws", 1))
        await ws.send_str("ping")
        msg = await ws.receive(timeout=5)
        assert msg.type == aiohttp.WSMsgType.TEXT
        assert msg.data == "echo:ping"
        await ws.close()
        assert ws.closed


async def test_aiohttp_error_status_raises_client_response_error(server):
    async with aiohttp.ClientSession() as session:
        async with session.get(server.make_url("/missing")) as resp:
            assert resp.status == 404
            with pytest.raises(aiohttp.ClientResponseError):
                resp.raise_for_status()


async def test_aiohttp_connection_refused_is_a_client_error():
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientError):
            await session.get("http://127.0.0.1:1/", timeout=aiohttp.ClientTimeout(total=3))


def test_yarl_url_building_used_by_ha_client():
    from yarl import URL
    url = URL("http://127.0.0.1:8123") / "api" / "states"
    assert str(url) == "http://127.0.0.1:8123/api/states"
    assert url.host == "127.0.0.1" and url.port == 8123


def test_pillow_generates_resizes_and_saves_png():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle([4, 4, 252, 252], radius=40, fill=(30, 30, 30, 255))
    resized = image.resize((64, 64), Image.Resampling.LANCZOS)
    assert resized.size == (64, 64)
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    reopened = Image.open(io.BytesIO(buf.getvalue()))
    reopened.load()
    assert reopened.format == "PNG" and reopened.size == (64, 64)
    assert reopened.getpixel((32, 32)) == (30, 30, 30, 255)


def test_pillow_rejects_malformed_image_data():
    from PIL import Image, UnidentifiedImageError
    with pytest.raises(UnidentifiedImageError):
        Image.open(io.BytesIO(b"definitely not an image"))


def test_pillow_rejects_truncated_png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(buf, format="PNG")
    truncated = buf.getvalue()[: len(buf.getvalue()) // 2]
    with pytest.raises(Exception):
        Image.open(io.BytesIO(truncated)).load()


def test_pillow_image_bytes_load_into_qpixmap(qapp):
    from PIL import Image
    from PyQt6.QtGui import QPixmap
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(buf, format="PNG")
    pixmap = QPixmap()
    assert pixmap.loadFromData(buf.getvalue())
    assert (pixmap.width(), pixmap.height()) == (16, 16)


def make_fernet(salt=b"0123456789abcdef", seed=b"machine-seed"):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=1000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(seed)))


def test_cryptography_fernet_round_trip_with_pbkdf2_key():
    token = "eyJhbGciOi.long-lived-token"
    f = make_fernet()
    ciphertext = f.encrypt(token.encode("utf-8"))
    assert token.encode() not in ciphertext
    assert f.decrypt(ciphertext).decode("utf-8") == token


def test_cryptography_fernet_detects_tampering():
    from cryptography.fernet import InvalidToken
    f = make_fernet()
    ciphertext = bytearray(f.encrypt(b"secret"))
    ciphertext[len(ciphertext) // 2] ^= 0x01
    with pytest.raises(InvalidToken):
        f.decrypt(bytes(ciphertext))


def test_cryptography_wrong_key_or_salt_cannot_decrypt():
    from cryptography.fernet import InvalidToken
    ciphertext = make_fernet(salt=b"a" * 16).encrypt(b"secret")
    with pytest.raises(InvalidToken):
        make_fernet(salt=b"b" * 16).decrypt(ciphertext)
    with pytest.raises(InvalidToken):
        make_fernet(salt=b"a" * 16, seed=b"other").decrypt(ciphertext)


def test_cryptography_pbkdf2_is_deterministic_and_salt_sensitive():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    def derive(salt):
        return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=1000).derive(b"seed")

    assert derive(b"s" * 16) == derive(b"s" * 16)
    assert derive(b"s" * 16) != derive(b"t" * 16)
    assert len(derive(b"s" * 16)) == 32


def test_cryptography_rejects_malformed_fernet_key():
    from cryptography.fernet import Fernet
    with pytest.raises(ValueError):
        Fernet(b"too-short")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"tag_name": "v9.9"}'
        self.send_response(200 if self.path == "/ok" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_requests_fetches_json_from_local_server(http_server):
    import requests
    resp = requests.get(http_server + "/ok", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["tag_name"] == "v9.9"


def test_requests_reports_http_errors_and_connection_failures(http_server):
    import requests
    with pytest.raises(requests.HTTPError):
        requests.get(http_server + "/nope", timeout=5).raise_for_status()
    with pytest.raises(requests.ConnectionError):
        requests.get("http://127.0.0.1:1/", timeout=3)


def test_certifi_bundle_exists_and_loads_into_ssl_context():
    import certifi
    path = Path(certifi.where())
    assert path.is_file() and path.stat().st_size > 10_000
    ctx = ssl.create_default_context(cafile=str(path))
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.cert_store_stats()["x509_ca"] > 50


def test_psutil_metrics_used_by_sensors_are_sane():
    import psutil
    assert 0.0 <= psutil.cpu_percent(interval=None) <= 100.0 * psutil.cpu_count()
    assert 0.0 < psutil.virtual_memory().percent <= 100.0
    assert 0.0 <= psutil.disk_usage(os.path.abspath(os.sep)).percent <= 100.0
    assert psutil.boot_time() > 0
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    assert battery is None or 0 <= battery.percent <= 100


def test_qasync_event_loop_runs_a_coroutine(qapp):
    import qasync
    loop = qasync.QEventLoop(qapp)
    try:
        async def work():
            await asyncio.sleep(0.01)
            return 42

        assert loop.run_until_complete(work()) == 42
    finally:
        loop.close()


def test_qasync_loop_drives_aiohttp_against_local_server(qapp):
    import qasync
    loop = qasync.QEventLoop(qapp)

    async def scenario():
        srv = TestServer(build_app(), host="127.0.0.1")
        await srv.start_server()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(srv.make_url("/hello")) as resp:
                    return resp.status
        finally:
            await srv.close()

    try:
        assert loop.run_until_complete(scenario()) == 200
    finally:
        loop.close()


def test_pyqt6_offscreen_application_creates_a_widget(qapp):
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
    assert QApplication.instance() is qapp
    assert qapp.platformName() == "offscreen"
    label = QLabel("hello")
    button = QPushButton("go")
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    button.click()
    assert label.text() == "hello"
    assert clicked == [True]
    label.deleteLater()
    button.deleteLater()


def test_pyqt6_local_socket_classes_used_by_ipc_are_available():
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    assert QLocalServer and QLocalSocket


def test_pystray_menu_objects_can_be_built_without_a_display():
    pystray = pytest.importorskip("pystray")
    calls = []
    menu = pystray.Menu(pystray.MenuItem("Quit", lambda icon, item: calls.append(1)))
    items = list(menu.items)
    assert [i.text for i in items] == ["Quit"]


def test_pynput_hotkey_parsing_and_key_types_are_available():
    from pynput import keyboard, mouse
    keys = keyboard.HotKey.parse("<ctrl>+<alt>+h")
    assert keyboard.Key.ctrl in keys and keyboard.Key.alt in keys
    assert keyboard.KeyCode.from_char("h") in keys
    assert mouse.Button.left != mouse.Button.right
    with pytest.raises(ValueError):
        keyboard.HotKey.parse("<not_a_key>+x")


@pytest.mark.skipif(sys.platform == "darwin", reason="keyring is intentionally not used on macOS")
def test_keyring_fail_backend_raises_instead_of_storing_secrets():
    keyring = pytest.importorskip("keyring")
    from keyring.backends import fail
    backend = fail.Keyring()
    with pytest.raises(keyring.errors.KeyringError):
        backend.set_password("svc", "user", "pw")


def test_dbus_next_variant_available_where_installed():
    dbus_next = pytest.importorskip("dbus_next")
    variant = dbus_next.Variant("s", "x")
    assert variant.signature == "s" and variant.value == "x"
