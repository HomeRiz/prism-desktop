import asyncio
import os
import subprocess
import sys
import threading
import types
from unittest import mock

import pytest

from services import notifications as nt
from services.notifications import (
    MAX_ACTIONS,
    NotificationManager,
    WIN_TOKEN_PREFIX,
    is_safe_http_uri,
    parse_action_token,
    sanitize_actions,
)

def test_sanitize_actions_non_list_returns_empty():
    assert sanitize_actions(None) == []
    assert sanitize_actions("x") == []
    assert sanitize_actions({"action": "a", "title": "t"}) == []

def test_sanitize_actions_strips_and_keeps_valid():
    raw = [{"action": " OPEN ", "title": " Open ", "uri": " https://x.io "}, {"action": "B", "title": "Bee"}]
    assert sanitize_actions(raw) == [
        {"action": "OPEN", "title": "Open", "uri": "https://x.io"},
        {"action": "B", "title": "Bee"},
    ]

@pytest.mark.parametrize("entry", [
    "string", 5, None, [], {},
    {"action": "", "title": "t"},
    {"action": "  ", "title": "t"},
    {"action": "a", "title": ""},
    {"action": "a"},
    {"title": "t"},
    {"action": 1, "title": "t"},
    {"action": "a", "title": ["t"]},
])
def test_sanitize_actions_drops_malformed_entries(entry):
    assert sanitize_actions([entry]) == []

def test_sanitize_actions_truncates_to_limit_in_order():
    raw = [{"action": f"a{i}", "title": f"t{i}"} for i in range(MAX_ACTIONS + 4)]
    result = sanitize_actions(raw)
    assert [a["action"] for a in result] == [f"a{i}" for i in range(MAX_ACTIONS)]

@pytest.mark.parametrize("uri,expected", [
    ("https://example.com/a", True),
    ("http://192.168.1.2:8123/x", True),
    ("HTTP://EXAMPLE.COM", True),
    ("javascript:alert(1)", False),
    ("file:///etc/passwd", False),
    ("ftp://example.com", False),
    ("homeassistant://navigate/x", False),
    ("http://", False),
    ("//example.com", False),
    ("", False),
    (None, False),
    (5, False),
    ("http://[::1", False),
])
def test_is_safe_http_uri(uri, expected):
    assert is_safe_http_uri(uri) is expected

@pytest.mark.parametrize("token,count,expected", [
    ("0", 3, 0),
    ("2", 3, 2),
    ("3", 3, None),
    ("99", 3, None),
    (WIN_TOKEN_PREFIX + "1", 3, 1),
    (WIN_TOKEN_PREFIX + "5", 3, None),
    (WIN_TOKEN_PREFIX, 3, None),
    ("", 3, None),
    ("-1", 3, None),
    ("1.5", 3, None),
    ("abc", 3, None),
    ("prism_action:1", 3, None),
    (None, 3, None),
    (1, 3, None),
    ("0", 0, None),
])
def test_parse_action_token(token, count, expected):
    assert parse_action_token(token, count) == expected

def set_system(monkeypatch, name):
    monkeypatch.setattr(nt.platform, "system", lambda: name)

async def test_show_notification_dispatches_per_platform(manager, monkeypatch):
    calls = []
    for method in ("_show_windows", "_show_linux", "_show_macos", "_show_fallback"):
        monkeypatch.setattr(manager, method, lambda *a, _m=method: calls.append(_m))
    for system, expected in [("Windows", "_show_windows"), ("Linux", "_show_linux"),
                             ("Darwin", "_show_macos"), ("Plan9", "_show_fallback")]:
        calls.clear()
        set_system(monkeypatch, system)
        manager._show_notification("t", "m")
        assert calls == [expected]

async def test_show_notification_linux_with_actions_uses_dbus_path(manager, monkeypatch):
    set_system(monkeypatch, "Linux")
    seen = []

    async def fake_actions(*args):
        seen.append(args)

    monkeypatch.setattr(manager, "_show_linux_actions", fake_actions)
    actions = [{"action": "a", "title": "A"}]
    manager._show_notification("t", "m", None, actions, {"k": 1})
    await asyncio.sleep(0.01)
    assert seen == [("t", "m", None, actions, {"k": 1})]

def test_show_linux_builds_notify_send_command(manager, monkeypatch, tmp_path):
    image = tmp_path / "pic.jpg"
    image.write_bytes(b"x")
    run = mock.Mock()
    monkeypatch.setattr(nt.subprocess, "run", run)
    manager._show_linux("Title", "Body", str(image))
    assert run.call_args.args[0] == ["notify-send", "-a", "Prism Desktop", "-i", str(image), "Title", "Body"]
    assert run.call_args.kwargs["check"] is False

@pytest.mark.parametrize("exc", [FileNotFoundError(), subprocess.TimeoutExpired("notify-send", 5)])
def test_show_linux_falls_back_to_tray(manager, monkeypatch, exc):
    monkeypatch.setattr(nt.subprocess, "run", mock.Mock(side_effect=exc))
    manager._show_linux("T", "B")
    assert manager.tray_icon.messages[0][:2] == ("T", "B")

def test_show_macos_prefers_tray(manager, monkeypatch):
    run = mock.Mock()
    monkeypatch.setattr(nt.subprocess, "run", run)
    manager._show_macos("T", "B")
    assert manager.tray_icon.messages[0][:2] == ("T", "B")
    run.assert_not_called()

def test_show_macos_osascript_escapes_quotes_and_backslashes(manager, monkeypatch):
    manager.tray_icon = None
    run = mock.Mock()
    monkeypatch.setattr(nt.subprocess, "run", run)
    manager._show_macos('He said "hi"', 'path\\n" & do shell script "evil')
    script = run.call_args.args[0][2]
    assert run.call_args.args[0][:2] == ["osascript", "-e"]
    assert 'with title "He said \\"hi\\""' in script
    assert 'display notification "path\\\\n\\" & do shell script \\"evil"' in script

@pytest.mark.parametrize("uri,expected_open", [
    ("https://example.com", True),
    ("javascript:alert(1)", False),
    ("file:///etc/passwd", False),
])
async def test_handle_action_only_opens_http_uris(manager, monkeypatch, uri, expected_open):
    opened = []
    fired = []

    async def fire(*a):
        fired.append(a)

    monkeypatch.setattr(manager, "_open_uri", opened.append)
    monkeypatch.setattr(manager, "_fire_action_event", fire)
    manager._handle_action({"action": "GO", "title": "t", "uri": uri}, None)
    await asyncio.sleep(0.01)
    assert opened == ([uri] if expected_open else [])
    assert fired == [("GO", None)]

async def test_handle_action_uri_action_fires_no_event(manager, monkeypatch):
    opened = []
    fired = []

    async def fire(*a):
        fired.append(a)

    monkeypatch.setattr(manager, "_open_uri", opened.append)
    monkeypatch.setattr(manager, "_fire_action_event", fire)
    manager._handle_action({"action": "URI", "title": "t", "uri": "https://a.io"}, {"x": 1})
    await asyncio.sleep(0.01)
    assert opened == ["https://a.io"]
    assert fired == []

def test_open_uri_linux_uses_detached_xdg_open(manager, monkeypatch):
    monkeypatch.setattr(nt.sys, "platform", "linux")
    popen = mock.Mock()
    monkeypatch.setattr(nt.subprocess, "Popen", popen)
    manager._open_uri("https://a.io")
    assert popen.call_args.args[0] == ["xdg-open", "https://a.io"]

async def test_fire_action_event_sends_merged_event(manager, monkeypatch):
    sent = []

    async def fire(url, webhook, data):
        sent.append((url, webhook, data))
        return True

    monkeypatch.setattr(nt, "fire_notification_action_event", fire)
    await manager._fire_action_event("OPEN", {"room": "k", "action": "spoof"})
    assert sent == [("http://ha.local:8123", "wh",
                     {"room": "k", "action": "OPEN", "device_id": "dev", "device_name": "pc"})]

async def test_fire_action_event_retries_once_then_gives_up(manager, monkeypatch):
    attempts = []

    async def fire(*args):
        attempts.append(args)
        return False

    monkeypatch.setattr(nt, "fire_notification_action_event", fire)
    await manager._fire_action_event("A", None)
    assert len(attempts) == 2

@pytest.mark.parametrize("mutate", [
    lambda c: c["home_assistant"].update(url=""),
    lambda c: c["mobile_app"].update(webhook_id=""),
    lambda c: c.pop("mobile_app"),
    lambda c: c.pop("home_assistant"),
])
async def test_fire_action_event_requires_url_and_webhook(manager, monkeypatch, notify_config, mutate):
    mutate(notify_config)
    fire = mock.AsyncMock()
    monkeypatch.setattr(nt, "fire_notification_action_event", fire)
    await manager._fire_action_event("A", None)
    fire.assert_not_called()

def test_on_linux_action_dispatches_matching_index(manager, monkeypatch):
    handled = []
    monkeypatch.setattr(manager, "_handle_action", lambda a, d: handled.append((a, d)))
    actions = [{"action": "a", "title": "A"}, {"action": "b", "title": "B"}]
    manager._on_linux_action(actions, {"d": 1}, "1")
    manager._on_linux_action(actions, {"d": 1}, "7")
    manager._on_linux_action(actions, {"d": 1}, "default")
    assert handled == [(actions[1], {"d": 1})]

async def test_windows_click_dispatches_on_loop(manager, monkeypatch):
    handled = []
    monkeypatch.setattr(manager, "_handle_action", lambda a, d: handled.append((a, d)))
    actions = [{"action": "a", "title": "A"}]
    manager._loop = asyncio.get_running_loop()
    thread = threading.Thread(
        target=manager._on_windows_click, args=(actions, {"x": 1}, {"arguments": WIN_TOKEN_PREFIX + "0"})
    )
    thread.start()
    thread.join(timeout=5)
    for _ in range(100):
        if handled:
            break
        await asyncio.sleep(0.01)
    assert handled == [(actions[0], {"x": 1})]

@pytest.mark.parametrize("args", [
    {"arguments": ""},
    {"arguments": "prism_action:0"},
    {"arguments": WIN_TOKEN_PREFIX + "9"},
    "str",
    None,
])
async def test_windows_click_ignores_foreign_or_body_clicks(manager, args):
    manager._loop = mock.Mock()
    manager._on_windows_click([{"action": "a", "title": "A"}], None, args)
    manager._loop.call_soon_threadsafe.assert_not_called()

def run_toast_worker(manager, actions, toast, register=None):
    module = types.ModuleType("win11toast")
    module.toast = toast
    module.register = register or mock.Mock()
    with mock.patch.dict(sys.modules, {"win11toast": module}):
        manager._windows_toast_worker("T", "M", {"app_id": manager.APP_ID}, actions, {"d": 1})

def test_windows_toast_worker_builds_protocol_buttons(manager):
    toast = mock.Mock()
    actions = [{"action": "a", "title": "Alpha"}, {"action": "b", "title": "Beta"}]
    run_toast_worker(manager, actions, toast)
    args, kwargs = toast.call_args
    assert args == ("T", "M")
    assert kwargs["buttons"] == [
        {"activationType": "protocol", "arguments": WIN_TOKEN_PREFIX + "0", "content": "Alpha"},
        {"activationType": "protocol", "arguments": WIN_TOKEN_PREFIX + "1", "content": "Beta"},
    ]
    assert callable(kwargs["on_click"])

def test_windows_toast_worker_registers_app_once(manager):
    register = mock.Mock()
    run_toast_worker(manager, [], mock.Mock(), register)
    run_toast_worker(manager, [], mock.Mock(), register)
    assert register.call_count == 1
    assert register.call_args.args == (manager.APP_ID, manager.APP_NAME)

def test_windows_registration_failure_is_not_retried(manager):
    register = mock.Mock(side_effect=RuntimeError("no"))
    run_toast_worker(manager, [], mock.Mock(), register)
    run_toast_worker(manager, [], mock.Mock(), register)
    assert register.call_count == 1
    assert manager._windows_registered is True

def test_windows_toast_worker_error_uses_fallback(manager):
    manager._loop = mock.Mock()
    run_toast_worker(manager, [], mock.Mock(side_effect=RuntimeError("fail")))
    manager._loop.call_soon_threadsafe.assert_called_once()

def install_fake_dbus_notifier(monkeypatch, connected, supported, nid):
    notifier = mock.Mock()
    notifier.connect = mock.AsyncMock(return_value=connected)
    notifier.actions_supported = supported
    notifier.notify = mock.AsyncMock(return_value=nid)
    module = types.ModuleType("services.dbus_notifier")
    module.DBusNotifier = mock.Mock(return_value=notifier)
    monkeypatch.setitem(sys.modules, "services.dbus_notifier", module)
    return notifier

async def test_show_linux_actions_uses_dbus_when_supported(manager, monkeypatch):
    notifier = install_fake_dbus_notifier(monkeypatch, True, True, 7)
    fallback = mock.Mock()
    monkeypatch.setattr(manager, "_show_linux", fallback)
    await manager._show_linux_actions("T", "M", "/img.jpg", [{"action": "a", "title": "Alpha"}], None)
    kwargs = notifier.notify.call_args.kwargs
    assert kwargs["actions"] == [("0", "Alpha")]
    assert kwargs["image_path"] == "/img.jpg"
    fallback.assert_not_called()

@pytest.mark.parametrize("connected,supported,nid", [(False, True, 1), (True, False, 1), (True, True, None)])
async def test_show_linux_actions_degrades_to_notify_send(manager, monkeypatch, connected, supported, nid):
    install_fake_dbus_notifier(monkeypatch, connected, supported, nid)
    fallback = mock.Mock()
    monkeypatch.setattr(manager, "_show_linux", fallback)
    await manager._show_linux_actions("T", "M", None, [{"action": "a", "title": "A"}], None)
    fallback.assert_called_once_with("T", "M", None)

@pytest.mark.parametrize("source,kind", [
    ("camera.front", "camera"),
    ("image.cat", "entity"),
    ("/api/image_proxy/x", "media"),
    ("https://x/y.jpg", "media"),
    ("local/foo.jpg", "media"),
])
async def test_download_image_routes_by_source_prefix(manager, source, kind):
    path = await manager._download_image(source)
    try:
        assert manager.ha_client.calls == [(kind, source)]
        assert path.endswith(".jpg")
        with open(path, "rb") as f:
            assert f.read() == b"img"
    finally:
        os.remove(path)

async def test_download_image_without_client_or_data(manager):
    manager.ha_client.data = b""
    assert await manager._download_image("camera.x") is None
    manager.ha_client = None
    assert await manager._download_image("camera.x") is None

async def test_download_image_swallows_errors(manager):
    manager.ha_client.get_camera_image = mock.AsyncMock(side_effect=RuntimeError("down"))
    assert await manager._download_image("camera.x") is None

async def test_show_with_image_deletes_temp_file_after_delay(manager, monkeypatch, tmp_path):
    image = tmp_path / "n.jpg"
    image.write_bytes(b"x")
    monkeypatch.setattr(manager, "_download_image", mock.AsyncMock(return_value=str(image)))
    shown = []
    monkeypatch.setattr(manager, "_show_notification", lambda *a: shown.append(a))
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(nt.asyncio, "sleep", fake_sleep)
    await manager._show_with_image("T", "M", "camera.x", None, None)
    assert shown == [("T", "M", str(image), None, None)]
    assert sleeps == [15]
    assert not image.exists()

async def test_show_ha_notification_rejects_non_dict(manager, monkeypatch):
    show = mock.Mock()
    monkeypatch.setattr(manager, "_show_notification", show)
    for bad in (None, "x", [1], 5):
        manager.show_ha_notification(bad)
    show.assert_not_called()

async def test_show_ha_notification_sanitises_actions_and_action_data(manager, monkeypatch):
    show = mock.Mock()
    monkeypatch.setattr(manager, "_show_notification", show)
    manager.show_ha_notification({
        "title": "T", "message": "M", "action_data": "not a dict",
        "actions": [{"action": "a", "title": "A"}, {"junk": True}],
    })
    assert show.call_args.kwargs == {"actions": [{"action": "a", "title": "A"}], "action_data": None}

async def test_show_ha_notification_with_image_goes_async(manager, monkeypatch):
    seen = []

    async def fake(*args):
        seen.append(args)

    monkeypatch.setattr(manager, "_show_with_image", fake)
    manager.show_ha_notification({"title": "T", "message": "M", "image": "camera.door", "action_data": {"k": 1}})
    await asyncio.sleep(0.01)
    assert seen == [("T", "M", "camera.door", [], {"k": 1})]
