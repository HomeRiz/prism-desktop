import pytest


@pytest.fixture
def im(fake_pynput, load_service, qapp):
    return load_service("input_manager")


@pytest.fixture
def K(fake_pynput):
    return fake_pynput.Key


@pytest.fixture
def mgr(im):
    manager = im.InputManager()
    yield manager
    manager.stop_listening()


def collect(signal):
    log = []
    signal.connect(lambda *a: log.append(a[0] if a else None))
    return log


def kb(fake_pynput):
    return fake_pynput.Listener.instances


def test_mouse_map_covers_all_buttons(mgr, fake_pynput):
    assert set(mgr._mouse_map.values()) == {
        "Button.left", "Button.right", "Button.middle", "Button.x1", "Button.x2"
    }


def test_update_shortcut_empty_config_stops_everything(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "<ctrl>+a"})
    mgr.update_shortcut({})
    assert mgr._keyboard_listener is None and not mgr._health_timer.isActive()


def test_keyboard_shortcut_starts_global_hotkeys_and_emits_trigger(mgr, fake_pynput):
    fired = collect(mgr.triggered)
    mgr.update_shortcut({"type": "keyboard", "value": "<ctrl>+<alt>+h"})
    listener = mgr._keyboard_listener
    assert isinstance(listener, fake_pynput.GlobalHotKeys) and listener.started
    assert list(listener.args[0]) == ["<ctrl>+<alt>+h"]
    listener.args[0]["<ctrl>+<alt>+h"]()
    assert fired == [None]
    assert mgr._health_timer.isActive()


def test_keyboard_shortcut_without_value_starts_nothing(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": ""})
    assert mgr._keyboard_listener is None


def test_invalid_hotkey_is_reported_not_raised(mgr, fake_pynput, monkeypatch, im):
    def bad(*a, **k):
        raise ValueError("bad hotkey")

    monkeypatch.setattr(im.keyboard, "GlobalHotKeys", bad)
    mgr.update_shortcut({"type": "keyboard", "value": "<nope>"})
    assert mgr._keyboard_listener is None


def test_updating_shortcut_stops_previous_listener(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    first = mgr._keyboard_listener
    mgr.update_shortcut({"type": "keyboard", "value": "b"})
    assert first.stopped and mgr._keyboard_listener is not first


def vk_listener(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "<ctrl>+<102>"})
    listener = mgr._keyboard_listener
    return listener.kwargs["on_press"], listener.kwargs["on_release"]


def test_vk_shortcut_requires_modifier_and_vk(mgr, K):
    fired = collect(mgr.triggered)
    on_press, on_release = vk_listener(mgr)
    on_press(K(vk=102))
    assert fired == []
    on_press(K(name="ctrl_l"))
    on_press(K(vk=101))
    assert fired == []
    on_press(K(vk=102))
    assert fired == [None]
    on_release(K(name="ctrl_l"))
    on_press(K(vk=102))
    assert fired == [None]


def test_mouse_shortcut_triggers_only_on_matching_press(mgr, fake_pynput):
    fired = collect(mgr.triggered)
    mgr.update_shortcut({"type": "mouse", "value": "Button.x1"})
    on_click = mgr._mouse_listener.kwargs["on_click"]
    on_click(0, 0, fake_pynput.Button.left, True)
    on_click(0, 0, fake_pynput.Button.x1, False)
    assert fired == []
    on_click(0, 0, fake_pynput.Button.x1, True)
    assert fired == [None]


def test_stop_listening_stops_all_and_clears_state(mgr, K):
    mgr.update_shortcut({"type": "mouse", "value": "Button.left"})
    mouse_listener = mgr._mouse_listener
    mgr._pressed_keys.add(K(name="a"))
    mgr.stop_listening()
    assert mouse_listener.stopped and mgr._mouse_listener is None
    assert mgr._pressed_keys == set() and not mgr._health_timer.isActive()


def test_restore_shortcut_restarts_configured_listener(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    mgr.stop_listening()
    mgr.restore_shortcut()
    assert mgr._keyboard_listener is not None and mgr._health_timer.isActive()


def test_restore_without_shortcut_is_noop(mgr):
    mgr.restore_shortcut()
    assert mgr._keyboard_listener is None and mgr._mouse_listener is None


def test_recording_keyboard_combo_emits_and_stops(mgr, K):
    recorded = collect(mgr.recorded)
    started, stopped = collect(mgr.recording_started), collect(mgr.recording_stopped)
    mgr.start_recording()
    assert started == [None] and mgr._is_recording
    ctrl, h = K(name="ctrl_l"), K(char="h", vk=72)
    mgr._on_record_key_press(ctrl)
    mgr._on_record_key_press(h)
    mgr._on_record_key_release(h)
    assert recorded == [{"type": "keyboard", "value": "<ctrl>+h"}]
    assert stopped == [None] and not mgr._is_recording


def test_recording_modifier_only_does_not_finish(mgr, K):
    recorded = collect(mgr.recorded)
    mgr.start_recording()
    ctrl = K(name="ctrl_l")
    mgr._on_record_key_press(ctrl)
    mgr._on_record_key_release(ctrl)
    assert recorded == [] and mgr._is_recording


def test_recording_mouse_click_emits_button(mgr, fake_pynput):
    recorded = collect(mgr.recorded)
    mgr.start_recording()
    mgr._on_record_mouse_click(0, 0, fake_pynput.Button.right, False)
    assert recorded == []
    mgr._on_record_mouse_click(0, 0, fake_pynput.Button.right, True)
    assert recorded == [{"type": "mouse", "value": "Button.right"}]


def test_record_callbacks_ignored_when_not_recording(mgr, K, fake_pynput):
    recorded = collect(mgr.recorded)
    mgr._on_record_key_press(K(char="a", vk=65))
    mgr._on_record_key_release(K(char="a", vk=65))
    mgr._on_record_mouse_click(0, 0, fake_pynput.Button.left, True)
    assert recorded == []


@pytest.mark.parametrize("keys,expected", [
    ([dict(name="ctrl_l"), dict(char="a", vk=65)], "<ctrl>+a"),
    ([dict(name="alt_l"), dict(name="shift"), dict(name="ctrl"), dict(char="1", vk=49)], "<ctrl>+<alt>+<shift>+1"),
    ([dict(name="cmd"), dict(char="k", vk=75)], "<cmd>+k"),
    ([dict(name="win"), dict(char="k", vk=75)], "<cmd>+k"),
    ([dict(name="ctrl_l"), dict(name="f5")], "<ctrl>+<f5>"),
    ([dict(name="ctrl_l"), dict(char="6", vk=102)], "<ctrl>+<102>"),
    ([dict(name="ctrl_l"), dict(char="\x01", vk=65)], "<ctrl>+a"),
    ([dict(name="space")], "<space>"),
    ([dict(char="b", vk=66), dict(char="a", vk=65)], "a"),
    ([dict(name="ctrl_l")], None),
    ([], None),
])
def test_format_combo(mgr, K, keys, expected):
    assert mgr._format_combo({K(**k) for k in keys}) == expected


def test_wayland_unsupported_desktop_disables_keyboard_shortcut(mgr, im, monkeypatch):
    monkeypatch.setattr(im, "is_wayland_session", lambda: True)
    monkeypatch.setattr(im, "supports_wayland_global_shortcuts", lambda: False)
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    assert mgr._keyboard_listener is None and not mgr._health_timer.isActive()
    mgr.update_shortcut({"type": "mouse", "value": "Button.left"})
    assert mgr._mouse_listener is not None


class FakePortal:
    instances = []
    fail = False
    declined = False

    def __init__(self, shortcut, callback):
        if FakePortal.fail:
            raise RuntimeError("portal setup failed")
        self.shortcut, self.callback = shortcut, callback
        self.started = self.stopped = False
        self.alive = True
        FakePortal.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.alive = False

    def is_alive(self):
        return self.alive


@pytest.fixture
def portal(im, monkeypatch):
    FakePortal.instances, FakePortal.fail, FakePortal.declined = [], False, False
    monkeypatch.setattr(im, "_WAYLAND_PORTAL_AVAILABLE", True)
    monkeypatch.setattr(im, "WaylandGlobalShortcut", FakePortal)
    monkeypatch.setattr(im, "is_wayland_session", lambda: True)
    monkeypatch.setattr(im, "supports_wayland_global_shortcuts", lambda: True)
    return FakePortal


def test_wayland_portal_backend_used_when_supported(mgr, portal):
    fired = collect(mgr.triggered)
    mgr.update_shortcut({"type": "keyboard", "value": "<ctrl>+a"})
    assert portal.instances[0].started and mgr._keyboard_listener is None
    portal.instances[0].callback()
    assert fired == [None]
    mgr.stop_listening()
    assert portal.instances[0].stopped and mgr._wayland_shortcut is None


def test_wayland_portal_failure_falls_back_to_pynput(mgr, portal, fake_pynput):
    portal.fail = True
    mgr.update_shortcut({"type": "keyboard", "value": "<ctrl>+a"})
    assert mgr._wayland_shortcut is None
    assert isinstance(mgr._keyboard_listener, fake_pynput.GlobalHotKeys)


def test_health_check_restarts_dead_keyboard_listener(mgr, fake_pynput):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    dead = mgr._keyboard_listener
    dead.alive = False
    mgr._check_listener_alive()
    assert mgr._keyboard_listener is not dead and mgr._keyboard_listener.started


def test_health_check_restarts_dead_mouse_listener(mgr):
    mgr.update_shortcut({"type": "mouse", "value": "Button.left"})
    dead = mgr._mouse_listener
    dead.alive = False
    mgr._check_listener_alive()
    assert mgr._mouse_listener is not dead


def test_health_check_restarts_missing_listener(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    mgr._keyboard_listener = None
    mgr._check_listener_alive()
    assert mgr._keyboard_listener is not None


def test_health_check_leaves_live_listener_and_skips_while_recording(mgr):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    live = mgr._keyboard_listener
    mgr._check_listener_alive()
    assert mgr._keyboard_listener is live
    live.alive = False
    mgr._is_recording = True
    mgr._check_listener_alive()
    assert mgr._keyboard_listener is live


def test_health_check_restarts_dead_wayland_backend_unless_declined(mgr, portal):
    mgr.update_shortcut({"type": "keyboard", "value": "a"})
    dead = portal.instances[0]
    dead.alive = False
    dead.declined = True
    mgr._check_listener_alive()
    assert len(portal.instances) == 1
    dead.declined = False
    mgr._check_listener_alive()
    assert len(portal.instances) == 2 and mgr._wayland_shortcut is portal.instances[1]


@pytest.fixture
def bsm(im, qapp):
    manager = im.ButtonShortcutManager()
    yield manager
    manager.stop()


def button(shortcut, enabled=True, **extra):
    return {"id": shortcut, "custom_shortcut": {"enabled": enabled, "value": shortcut}, **extra}


def test_update_shortcuts_registers_only_enabled_with_value(bsm, fake_pynput):
    bsm.update_shortcuts([
        button("<ctrl>+1"), button("<ctrl>+2", enabled=False), button(""),
        {"id": "plain"}, {"id": "x", "custom_shortcut": {"enabled": True}},
    ])
    assert list(bsm._shortcuts) == ["<ctrl>+1"]
    assert bsm._listener.started


def test_update_shortcuts_with_none_enabled_starts_no_listener(bsm):
    bsm.update_shortcuts([button("<ctrl>+1", enabled=False)])
    assert bsm._listener is None


def test_update_shortcuts_replaces_previous_listener(bsm):
    bsm.update_shortcuts([button("<ctrl>+1")])
    first = bsm._listener
    bsm.update_shortcuts([button("<ctrl>+2")])
    assert first.stopped and bsm._listener is not first


def press(bsm, *keys):
    for key in keys:
        bsm._on_press(key)


def test_button_shortcut_fires_with_full_config(bsm, K):
    fired = collect(bsm.shortcut_triggered)
    cfg = button("<ctrl>+<shift>+k", label="Lamp")
    bsm.update_shortcuts([cfg])
    press(bsm, K(name="ctrl_l"), K(name="shift"), K(char="K", vk=75))
    assert fired == [cfg]


def test_button_shortcut_requires_exact_modifier_set(bsm, K):
    fired = collect(bsm.shortcut_triggered)
    bsm.update_shortcuts([button("<ctrl>+k")])
    press(bsm, K(char="k", vk=75))
    press(bsm, K(name="ctrl_l"), K(name="alt_l"), K(char="k", vk=75))
    assert fired == []


def test_button_shortcut_modifier_release_resets(bsm, K):
    fired = collect(bsm.shortcut_triggered)
    bsm.update_shortcuts([button("<ctrl>+k")])
    press(bsm, K(name="ctrl_l"))
    bsm._on_release(K(name="ctrl_l"))
    press(bsm, K(char="k", vk=75))
    assert fired == []


def test_button_shortcut_paused_suppresses_and_clears_modifiers(bsm, K):
    fired = collect(bsm.shortcut_triggered)
    bsm.update_shortcuts([button("<ctrl>+k")])
    press(bsm, K(name="ctrl_l"))
    bsm.set_paused(True)
    assert bsm._pressed_mods == set()
    press(bsm, K(name="ctrl_l"), K(char="k", vk=75))
    assert fired == []
    bsm.set_paused(False)
    press(bsm, K(name="ctrl_l"), K(char="k", vk=75))
    assert fired == [bsm._shortcuts["<ctrl>+k"]]


@pytest.mark.parametrize("shortcut,key,mods,expected", [
    ("<ctrl>+<102>", dict(vk=102), {"ctrl"}, True),
    ("<ctrl>+<102>", dict(vk=103), {"ctrl"}, False),
    ("a", dict(char="a"), set(), True),
    ("a", dict(char="A"), set(), True),
    ("a", dict(char=None, vk=65), set(), True),
    ("6", dict(char=None, vk=102), set(), False),
    ("a", dict(char="b", vk=66), set(), False),
    ("<f1>", dict(name="f1"), set(), True),
    ("<f1>", dict(name="f2"), set(), False),
    ("<ctrl>", dict(name="a"), {"ctrl"}, False),
    ("ab", dict(char="a"), set(), False),
])
def test_matches(bsm, K, shortcut, key, mods, expected):
    bsm._pressed_mods = set(mods)
    assert bsm._matches(K(**key), shortcut) is expected


def test_stop_clears_listener_and_modifiers(bsm, K):
    bsm.update_shortcuts([button("a")])
    press(bsm, K(name="ctrl_l"))
    listener = bsm._listener
    bsm.stop()
    assert listener.stopped and bsm._listener is None and bsm._pressed_mods == set()
