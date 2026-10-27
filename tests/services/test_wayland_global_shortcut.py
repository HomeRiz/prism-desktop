import asyncio

import pytest


@pytest.fixture
def ws_mod(fake_dbus_modules, load_service, monkeypatch):
    monkeypatch.setenv("DESKTOPINTEGRATION", "1")
    return load_service("wayland_global_shortcut")


@pytest.fixture
def d(fake_dbus_modules):
    return fake_dbus_modules


@pytest.mark.parametrize("source,expected", [
    ("<ctrl>+<alt>+h", "CTRL+ALT+h"),
    ("<ctrl>+<shift>+<f5>", "CTRL+SHIFT+F5"),
    ("<cmd>+<space>", "LOGO+space"),
    ("<ctrl>+<esc>", "CTRL+Escape"),
    ("<alt>+<enter>", "ALT+Return"),
    ("<ctrl>+<page_up>", "CTRL+Page_Up"),
    ("<ctrl>+<backspace>", "CTRL+BackSpace"),
    ("<CTRL> + <ALT> + H", "CTRL+ALT+h"),
    ("<ctrl>+<alt>+<102>", "CTRL+ALT+102"),
    ("<ctrl>++x", "CTRL+x"),
    ("x", "x"),
])
def test_pynput_to_portal_shortcut(ws_mod, source, expected):
    assert ws_mod._pynput_to_portal_shortcut(source) == expected


@pytest.mark.parametrize("empty", ["", "  ", "+", " + + "])
def test_pynput_to_portal_shortcut_rejects_empty(ws_mod, empty):
    with pytest.raises(ValueError):
        ws_mod._pynput_to_portal_shortcut(empty)


def test_request_path_follows_portal_convention(ws_mod):
    assert ws_mod._request_path(":1.42", "tok") == "/org/freedesktop/portal/desktop/request/1_42/tok"


def test_random_tokens_are_unique_and_valid_object_path_elements(ws_mod):
    first, second = ws_mod._random_token("prism_req"), ws_mod._random_token("prism_req")
    assert first != second and first.startswith("prism_req_")
    assert all(c.isalnum() or c == "_" for c in first)


@pytest.mark.parametrize("session,expected", [("wayland", True), ("x11", False), ("tty", False), (None, False)])
def test_is_wayland_session(ws_mod, monkeypatch, session, expected):
    if session is None:
        monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    else:
        monkeypatch.setenv("XDG_SESSION_TYPE", session)
    assert ws_mod.is_wayland_session() is expected


@pytest.mark.parametrize("current,session_desktop,expected", [
    ("KDE", "", True),
    ("plasma", "", True),
    ("", "KDE", True),
    ("X-Plasma", "x", True),
    ("GNOME", "gnome", False),
    ("", "", False),
])
def test_kde_wayland_detection_controls_support(ws_mod, monkeypatch, current, session_desktop, expected):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", current)
    monkeypatch.setenv("XDG_SESSION_DESKTOP", session_desktop)
    assert ws_mod.is_kde_wayland_session() is expected
    assert ws_mod.supports_wayland_global_shortcuts() is expected


def test_kde_on_x11_is_not_wayland_support(ws_mod, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert ws_mod.supports_wayland_global_shortcuts() is False


def test_ensure_desktop_file_writes_entry_once(ws_mod, monkeypatch, isolated_home):
    monkeypatch.delenv("DESKTOPINTEGRATION")
    monkeypatch.delenv("APPIMAGELAUNCHER_DISABLE", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    monkeypatch.setenv("APPIMAGE", "/opt/P.AppImage")
    ws_mod._ensure_desktop_file()
    target = isolated_home / ".local/share/applications/prism-desktop.desktop"
    assert "Exec=/opt/P.AppImage\n" in target.read_text()
    target.write_text("mine")
    ws_mod._ensure_desktop_file()
    assert target.read_text() == "mine"


def test_ensure_desktop_file_respects_external_integration(ws_mod, isolated_home):
    ws_mod._ensure_desktop_file()
    assert not (isolated_home / ".local/share/applications").exists()


def test_install_appimage_icon(ws_mod, tmp_path, isolated_home):
    assert ws_mod._install_appimage_icon(str(tmp_path)) == "prism-desktop"
    icon = tmp_path / "usr/share/icons/hicolor/256x256/apps/prism-desktop.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"png")
    dest = ws_mod._install_appimage_icon(str(tmp_path))
    assert dest.startswith(str(isolated_home)) and open(dest, "rb").read() == b"png"


class Portal:
    def __init__(self, d, ws_mod, session_response=0, bind_response=0, register_error=None, reroute=False):
        self.d, self.ws_mod = d, ws_mod
        self.session_response = session_response
        self.bind_response = bind_response
        self.register_error = register_error
        self.reroute = reroute
        self.bus = None

    def respond(self, token, code, results):
        path = self.ws_mod._request_path(":1.42", token)
        if self.reroute:
            path += "/rerouted"
        message = self.d.Message(message_type=self.d.MessageType.SIGNAL, interface=self.ws_mod.REQUEST_IFACE,
                                 member="Response", path=path, body=[code, results])
        asyncio.get_running_loop().call_soon(self.bus.deliver, message)
        return path

    def __call__(self, msg):
        d = self.d
        if msg.member == "Register":
            return d.error_reply(self.register_error) if self.register_error else d.reply()
        if msg.member == "CreateSession":
            token = msg.body[0]["handle_token"].value
            path = self.respond(token, self.session_response, {"session_handle": d.Variant("o", "/session/1")})
            return d.reply([path])
        if msg.member == "BindShortcuts":
            return d.reply([self.respond(msg.body[3]["handle_token"].value, self.bind_response, {})])
        return d.reply()


async def wait_until(condition, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        assert loop.time() < end, "condition not reached"
        await asyncio.sleep(0.01)


@pytest.fixture
async def start(ws_mod, d):
    started = []

    async def go(portal_kwargs=None, shortcut="<ctrl>+<alt>+h"):
        triggered = []
        shortcut_obj = ws_mod.WaylandGlobalShortcut(shortcut, lambda: triggered.append(1))
        portal = Portal(d, ws_mod, **(portal_kwargs or {}))
        original = d.FakeBus.__init__

        def init(self, bus_type=None):
            original(self, bus_type)
            self.responder = portal
            portal.bus = self

        d.FakeBus.__init__ = init
        started.append((shortcut_obj, original))
        shortcut_obj.start()
        await asyncio.sleep(0)
        return shortcut_obj, portal, triggered

    yield go
    for shortcut_obj, original in started:
        d.FakeBus.__init__ = original
        shortcut_obj.stop()
    await asyncio.sleep(0.05)


def bound(portal):
    return portal.bus is not None and any(c.member == "BindShortcuts" for c in portal.bus.calls)


async def test_registration_flow_binds_preferred_trigger(start, ws_mod):
    shortcut, portal, _ = await start()
    await wait_until(lambda: bound(portal) and shortcut._session_handle and not portal.bus.disconnected)
    bind = next(c for c in portal.bus.calls if c.member == "BindShortcuts")
    assert bind.body[0] == "/session/1"
    shortcut_id, props = bind.body[1][0]
    assert shortcut_id == ws_mod.SHORTCUT_ID
    assert props["preferred_trigger"].value == "CTRL+ALT+h"
    register = next(c for c in portal.bus.calls if c.member == "Register")
    assert register.body[0] == ws_mod.APP_ID
    assert shortcut.is_alive() and shortcut.declined is False


async def test_activation_signal_triggers_callback_only_for_our_session(start, d, ws_mod):
    shortcut, portal, triggered = await start()
    await wait_until(lambda: bound(portal) and shortcut._session_handle)
    activated = ws_mod.GLOBAL_SHORTCUTS_IFACE

    def fire(session, sid):
        portal.bus.deliver(d.Message(message_type=d.MessageType.SIGNAL, interface=activated,
                                     member="Activated", body=[session, sid, 0, {}]))

    fire("/session/other", ws_mod.SHORTCUT_ID)
    fire("/session/1", "different-id")
    assert triggered == []
    fire("/session/1", ws_mod.SHORTCUT_ID)
    assert triggered == [1]


async def test_session_closed_signal_stops_backend(start, d, ws_mod):
    shortcut, portal, _ = await start()
    await wait_until(lambda: bound(portal) and shortcut._session_handle)
    portal.bus.deliver(d.Message(message_type=d.MessageType.SIGNAL, interface=ws_mod.SESSION_IFACE,
                                 member="Closed", path="/session/1", body=[]))
    await wait_until(lambda: not shortcut.is_alive())
    assert portal.bus is None or portal.bus.disconnected


async def test_stop_closes_session_and_disconnects(start, ws_mod):
    shortcut, portal, _ = await start()
    await wait_until(lambda: bound(portal) and shortcut._session_handle)
    bus = portal.bus
    shortcut.stop()
    await wait_until(lambda: not shortcut.is_alive())
    assert any(c.member == "Close" and c.path == "/session/1" for c in bus.calls)
    assert bus.disconnected and bus.handlers == []
    assert shortcut._session_handle is None and shortcut._response_waiters == {}


async def test_user_declining_session_sets_declined_flag(start):
    shortcut, portal, _ = await start({"session_response": 1})
    await wait_until(lambda: not shortcut.is_alive())
    assert shortcut.declined is True
    assert not any(c.member == "BindShortcuts" for c in portal.bus.calls)


async def test_declined_binding_sets_declined_flag(start):
    shortcut, portal, _ = await start({"bind_response": 2})
    await wait_until(lambda: not shortcut.is_alive())
    assert shortcut.declined is True


async def test_register_app_info_not_found_is_tolerated(start):
    shortcut, portal, _ = await start({"register_error": "App info not found for prism"})
    await wait_until(lambda: bound(portal))
    assert shortcut.is_alive()


async def test_other_register_errors_fail_without_declined(start):
    shortcut, portal, _ = await start({"register_error": "Permission denied"})
    await wait_until(lambda: not shortcut.is_alive())
    assert shortcut.declined is False


async def test_rerouted_request_path_is_followed(start):
    shortcut, portal, _ = await start({"reroute": True})
    await wait_until(lambda: bound(portal) and shortcut._session_handle)
    assert shortcut.is_alive() and shortcut.declined is False
    assert any("rerouted" in c.body[0] for c in portal.bus.calls if c.member == "AddMatch")


async def test_invalid_shortcut_string_fails_before_touching_the_bus(start):
    shortcut, portal, _ = await start(shortcut="+")
    await wait_until(lambda: not shortcut.is_alive())
    assert portal.bus is None and shortcut.declined is False


async def test_start_twice_keeps_single_task(start):
    shortcut, portal, _ = await start()
    task = shortcut._task
    shortcut.start()
    assert shortcut._task is task
    await wait_until(lambda: bound(portal))


async def test_stop_before_start_is_safe(ws_mod):
    shortcut = ws_mod.WaylandGlobalShortcut("<ctrl>+a", lambda: None)
    shortcut.stop()
    assert shortcut.is_alive() is False
