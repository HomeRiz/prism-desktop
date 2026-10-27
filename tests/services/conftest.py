import enum
import importlib.util
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"


class StubServer:
    def __init__(self):
        self.routes = {}
        self.requests = []
        self.httpd = None
        self.thread = None

    @property
    def base(self):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def route(self, path, body=b"", status=200, headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.routes[path] = (status, body, headers or {})


def _make_handler(stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            stub.requests.append((self.path, dict(self.headers)))
            status, body, headers = stub.routes.get(self.path, (404, b"missing", {}))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


@pytest.fixture
def http_stub():
    stub = StubServer()
    stub.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(stub))
    stub.thread = threading.Thread(target=stub.httpd.serve_forever, daemon=True)
    stub.thread.start()
    yield stub
    stub.httpd.shutdown()
    stub.httpd.server_close()
    stub.thread.join(timeout=5)


class FakeMessageType(enum.IntEnum):
    METHOD_CALL = 1
    METHOD_RETURN = 2
    ERROR = 3
    SIGNAL = 4


class FakeBusType(enum.Enum):
    SESSION = 1
    SYSTEM = 2


class FakeVariant:
    def __init__(self, signature, value):
        self.signature = signature
        self.value = value


class FakeMessage:
    def __init__(self, destination=None, path=None, interface=None, member=None,
                 signature="", body=None, message_type=FakeMessageType.METHOD_CALL,
                 error_name=None):
        self.destination = destination
        self.path = path
        self.interface = interface
        self.member = member
        self.signature = signature
        self.body = body if body is not None else []
        self.message_type = message_type
        self.error_name = error_name


def reply(body=None):
    return FakeMessage(message_type=FakeMessageType.METHOD_RETURN, body=body or [])


def error_reply(text="boom", name="org.example.Error"):
    return FakeMessage(message_type=FakeMessageType.ERROR, body=[text], error_name=name)


class FakeBus:
    instances = []
    connect_error = None

    def __init__(self, bus_type=None):
        self.bus_type = bus_type
        self.unique_name = ":1.42"
        self.calls = []
        self.handlers = []
        self.disconnected = False
        self.responder = lambda msg: reply()
        FakeBus.instances.append(self)

    async def connect(self):
        if FakeBus.connect_error is not None:
            raise FakeBus.connect_error
        return self

    async def call(self, message):
        self.calls.append(message)
        result = self.responder(message)
        if isinstance(result, Exception):
            raise result
        return result

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    def remove_message_handler(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def disconnect(self):
        self.disconnected = True

    def deliver(self, message):
        for handler in list(self.handlers):
            handler(message)


@pytest.fixture
def fake_dbus_modules(monkeypatch):
    FakeBus.instances = []
    FakeBus.connect_error = None
    pkg = types.ModuleType("dbus_next")
    aio = types.ModuleType("dbus_next.aio")
    pkg.BusType = FakeBusType
    pkg.Message = FakeMessage
    pkg.MessageType = FakeMessageType
    pkg.Variant = FakeVariant
    aio.MessageBus = FakeBus
    pkg.aio = aio
    monkeypatch.setitem(sys.modules, "dbus_next", pkg)
    monkeypatch.setitem(sys.modules, "dbus_next.aio", aio)
    return types.SimpleNamespace(
        FakeBus=FakeBus, Message=FakeMessage, MessageType=FakeMessageType,
        Variant=FakeVariant, BusType=FakeBusType, reply=reply, error_reply=error_reply,
    )


class FakeListener:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.alive = True
        FakeListener.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.alive = False

    def is_alive(self):
        return self.alive


class FakeGlobalHotKeys(FakeListener):
    pass


class FakeMouseListener(FakeListener):
    instances = []


class FakeButton(enum.Enum):
    left = 1
    right = 2
    middle = 3
    x1 = 4
    x2 = 5

    def __str__(self):
        return f"Button.{self.name}"


class FakeKey:
    def __init__(self, name=None, char=None, vk=None):
        if name is not None:
            self.name = name
        if char is not None:
            self.char = char
        if vk is not None:
            self.vk = vk
        self._id = (name, char, vk)

    def __hash__(self):
        return hash(self._id)

    def __eq__(self, other):
        return isinstance(other, FakeKey) and other._id == self._id

    def __repr__(self):
        return f"FakeKey{self._id}"


@pytest.fixture
def fake_pynput(monkeypatch):
    FakeListener.instances = []
    FakeMouseListener.instances = []
    pkg = types.ModuleType("pynput")
    kb = types.ModuleType("pynput.keyboard")
    ms = types.ModuleType("pynput.mouse")
    kb.Listener = FakeListener
    kb.GlobalHotKeys = FakeGlobalHotKeys
    ms.Listener = FakeMouseListener
    ms.Button = FakeButton
    pkg.keyboard = kb
    pkg.mouse = ms
    monkeypatch.setitem(sys.modules, "pynput", pkg)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", kb)
    monkeypatch.setitem(sys.modules, "pynput.mouse", ms)
    return types.SimpleNamespace(
        Listener=FakeListener, GlobalHotKeys=FakeGlobalHotKeys,
        MouseListener=FakeMouseListener, Button=FakeButton, Key=FakeKey,
    )


@pytest.fixture
def load_service(monkeypatch):
    def loader(name):
        module_name = f"prism_isolated_{name}"
        spec = importlib.util.spec_from_file_location(module_name, SERVICES_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
        return module

    return loader


@pytest.fixture
def signal_log():
    def attach(**signals):
        log = {name: [] for name in signals}
        for name, signal in signals.items():
            signal.connect(lambda *a, _n=name: log[_n].append(a[0] if len(a) == 1 else a))
        return log

    return attach


class FakeTray:
    def __init__(self, available=True):
        self.available = available
        self.messages = []

    def isSystemTrayAvailable(self):
        return self.available

    def showMessage(self, *args):
        self.messages.append(args)


class FakeImageClient:
    def __init__(self, data=b"img"):
        self.data = data
        self.calls = []

    async def get_camera_image(self, src):
        self.calls.append(("camera", src))
        return self.data

    async def get_entity_image(self, src):
        self.calls.append(("entity", src))
        return self.data

    async def get_media_image(self, src):
        self.calls.append(("media", src))
        return self.data


@pytest.fixture
def notify_config():
    return {
        "home_assistant": {"url": "http://ha.local:8123"},
        "mobile_app": {"webhook_id": "wh", "device_id": "dev", "device_name": "pc"},
    }


@pytest.fixture
def manager(qapp, notify_config):
    from services.notifications import NotificationManager

    return NotificationManager(tray_icon=FakeTray(), ha_client=FakeImageClient(), config=notify_config)
