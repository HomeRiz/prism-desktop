import asyncio
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, QRect


@pytest.fixture(scope="module")
def main_mod(tmp_path_factory):
    import core.utils as cu
    original = cu.get_config_path
    cfg_dir = tmp_path_factory.mktemp("maincfg")
    cu.get_config_path = lambda filename="config.json": cfg_dir / filename
    try:
        import main
    finally:
        cu.get_config_path = original
    return main


class FakeDash:
    def __init__(self, cols=4, rows=2, page=0):
        self.cols, self.rows, self.current_page = cols, rows, page
        self.entity_states = {}
        self.set_calls = []
        self.media = []
        self.updates = []
        self.empty = {}
        self.focus = []
        self.refreshed = 0
        self.toggled = []
        self.cache_applied = 0
        self._visible = False

    def set_buttons(self, buttons, appearance):
        self.set_calls.append((list(buttons), appearance))

    def update_media_art(self, eid, pm):
        self.media.append((eid, pm))

    def update_entity_state(self, eid, state, live=False):
        self.updates.append((eid, live))

    def find_first_empty_slot_on_page(self, page, sx, sy):
        return self.empty.get((page, sx, sy), (-1, -1))

    def refresh_pin_buttons(self):
        self.refreshed += 1

    def set_ignore_focus_loss(self, v):
        self.focus.append(v)

    def isVisible(self):
        return self._visible

    def apply_camera_cache(self, cache):
        self.cache_applied += 1

    def toggle(self, geo):
        self.toggled.append(geo)

    show_toast = show_confirm = lambda *a, **k: None


@pytest.fixture
def app(main_mod, qapp, tmp_path, monkeypatch):
    obj = main_mod.PrismDesktopApp.__new__(main_mod.PrismDesktopApp)
    QObject.__init__(obj)
    obj.config = {'buttons': [], 'appearance': {}}
    obj.saved = 0
    obj.config_manager = SimpleNamespace(save_config=lambda: setattr(obj, 'saved', obj.saved + 1))
    obj.dashboard = FakeDash()
    obj.tray_manager = None
    obj._pin_lock = asyncio.Lock()
    obj._media_art_cache = {}
    obj._camera_cache = {}
    obj._image_pic_paths = {}
    obj._welcome_banner = None
    obj._assist_opened_dashboard = True
    monkeypatch.setattr(main_mod.PrismDesktopApp, '_pid_file_path', lambda self: tmp_path / "prism.pid")
    return obj


def test_arg_constants(main_mod):
    assert (main_mod.TOGGLE_ARG, main_mod.ASSIST_ARG, main_mod.WELCOME_ARG) == ("--toggle", "--assist", "--welcome")
    assert 'entity_id' in main_mod.PRINTER_ENTITY_KEYS
    assert 'scene' in main_mod.STATELESS_TRIGGER_DOMAINS


@pytest.mark.parametrize("arg,cmd,sent,code", [("--toggle", "toggle", True, 0), ("--toggle", "toggle", False, 1),
                                                  ("--assist", "assist", True, 0), ("--assist", "assist", False, 1)])
def test_cli_args_forward_command_without_starting_ui(main_mod, monkeypatch, tmp_path, capsys, arg, cmd, sent, code):
    import core.utils as cu
    import services.local_ipc as ipc
    calls = []
    monkeypatch.setattr(ipc, 'send_local_command', lambda c: calls.append(c) or sent)
    monkeypatch.setattr(cu, 'get_config_path', lambda filename="config.json": tmp_path / filename)
    monkeypatch.setattr(sys, 'argv', ['main.py', arg])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(main_mod.__file__)), run_name='__main__')
    assert exc.value.code == code
    assert calls == [cmd]
    assert ("No running" in capsys.readouterr().out) is (not sent)


def test_read_language_from_config(main_mod, monkeypatch, tmp_path):
    import core.utils as cu
    path = tmp_path / "config.json"
    monkeypatch.setattr(cu, 'get_config_path', lambda filename="config.json": path)
    assert main_mod._read_language_from_config() == "en"
    path.write_text(json.dumps({'appearance': {'language': 'de'}}))
    assert main_mod._read_language_from_config() == "de"
    path.write_text(json.dumps({'appearance': {}}))
    assert main_mod._read_language_from_config() == "en"
    path.write_text("{broken")
    assert main_mod._read_language_from_config() == "en"


def test_put_cache_evicts_oldest(main_mod):
    cache = {}
    for i in range(5):
        main_mod.PrismDesktopApp._put_cache(cache, i, i, max_size=3)
    assert list(cache) == [2, 3, 4]
    main_mod.PrismDesktopApp._put_cache(cache, 2, "new", max_size=3)
    assert cache[2] == "new" and len(cache) == 3


def test_create_task_safe_defers_to_event_loop(main_mod, monkeypatch):
    seen = []
    monkeypatch.setattr(main_mod.QTimer, 'singleShot', staticmethod(lambda ms, fn: seen.append((ms, fn))))
    created = []
    monkeypatch.setattr(main_mod.asyncio, 'create_task', lambda coro: created.append(coro))
    main_mod._create_task_safe("coro")
    assert seen[0][0] == 0 and created == []
    seen[0][1]()
    assert created == ["coro"]


def test_local_commands_route(app, monkeypatch):
    calls = []
    monkeypatch.setattr(type(app), '_toggle_dashboard', lambda self: calls.append("t"))
    monkeypatch.setattr(type(app), '_open_assist', lambda self: calls.append("a"), raising=False)
    app._handle_local_command("toggle")
    app._handle_local_command("assist")
    app._handle_local_command("bogus")
    assert calls == ["t", "a"]


def test_toggle_dashboard_applies_camera_cache_only_when_hidden(app):
    app._toggle_dashboard()
    assert app.dashboard.cache_applied == 1 and app._assist_opened_dashboard is False
    app.dashboard._visible = True
    app._toggle_dashboard()
    assert app.dashboard.cache_applied == 1 and len(app.dashboard.toggled) == 2


def test_tray_geometry_defaults_to_empty_rect(app):
    assert app._tray_geometry() == QRect()
    app.tray_manager = SimpleNamespace(geometry=lambda: QRect(1, 2, 3, 4))
    assert app._tray_geometry() == QRect(1, 2, 3, 4)


def test_pid_file_written_and_removed(app, tmp_path):
    app._write_pid_file()
    assert (tmp_path / "prism.pid").read_text().isdigit()
    app._remove_pid_file()
    assert not (tmp_path / "prism.pid").exists()
    app._remove_pid_file()


@pytest.mark.parametrize("mobile,expected", [
    ({}, False), ({'send_cpu': True}, True), ({'send_ram': True}, True),
])
def test_metrics_wanted(app, mobile, expected):
    app.config['mobile_app'] = mobile
    assert app._metrics_wanted() is expected


def test_sensor_push_skipped_without_webhook_or_when_disabled(app, main_mod, monkeypatch):
    posts = []
    monkeypatch.setattr(main_mod.requests, 'post', lambda *a, **k: posts.append((a, k)))
    app._push_sensor_state_sync(False)
    app.config.update(mobile_app={'webhook_id': 'w', 'send_logged_in': False}, home_assistant={'url': 'http://ha'})
    app._push_sensor_state_sync(False)
    app.config['mobile_app'] = {'webhook_id': 'w'}
    app.config['home_assistant'] = {'url': ''}
    app._push_sensor_state_sync(False)
    assert posts == []


def test_sensor_push_posts_to_webhook_and_tolerates_errors(app, main_mod, monkeypatch):
    posts = []
    monkeypatch.setattr(main_mod.requests, 'post', lambda url, json=None, timeout=None: posts.append((url, json, timeout)))
    app.config.update(mobile_app={'webhook_id': 'abc'}, home_assistant={'url': 'http://ha:8123/'})
    app._push_sensor_state_sync(False)
    url, payload, timeout = posts[0]
    assert url == 'http://ha:8123/api/webhook/abc' and timeout == 3
    assert payload['type'] == 'update_sensor_states'

    def boom(*a, **k):
        raise OSError("net")
    monkeypatch.setattr(main_mod.requests, 'post', boom)
    app._push_sensor_state_sync(True)


def test_welcome_shown_only_when_needed(app, monkeypatch):
    shown = []
    monkeypatch.setattr(type(app), '_show_welcome_banner', lambda self: shown.append(1))
    app.config['welcome_shown'] = True
    app.dashboard._visible = True
    app._maybe_show_welcome()
    assert shown == []
    monkeypatch.setattr(sys, 'argv', ['main.py', '--welcome'])
    app._maybe_show_welcome()
    assert shown == [1]
    app.config['welcome_shown'] = False
    app.dashboard._visible = False
    app._maybe_show_welcome()
    assert shown == [1]
    app.dashboard._visible = True
    app._maybe_show_welcome()
    assert shown == [1, 1]


def test_welcome_done_persists_and_releases_focus_guard(app):
    app.dashboard.btn_settings = SimpleNamespace(clicked=SimpleNamespace(disconnect=lambda fn: (_ for _ in ()).throw(RuntimeError())))
    banner = SimpleNamespace(finished=SimpleNamespace(disconnect=lambda fn: None), hide=lambda: None)
    app._welcome_banner = banner
    app._on_welcome_done()
    assert app.config['welcome_shown'] is True and app.saved == 1
    assert app.dashboard.focus == [False] and app._welcome_banner is None


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeClient:
    def __init__(self, state):
        self.state = state
        self.asked = []

    async def get_state(self, eid):
        self.asked.append(eid)
        return self.state


class FakeDispatcher:
    def __init__(self):
        self.clicks = []

    async def handle_button_click(self, cfg):
        self.clicks.append(cfg)


@pytest.fixture
def clickable(app, monkeypatch):
    from ui import notifications
    app.toasts = []
    monkeypatch.setattr(notifications, 'notify_entity_unavailable', lambda d, label: app.toasts.append(label))
    app.service_dispatcher = FakeDispatcher()
    return app


def test_pin_window_click_toggles_and_saves(clickable):
    clickable.ha_client = FakeClient(None)
    run(clickable._handle_button_click({'type': 'pin_window'}))
    assert clickable.config['appearance']['pin_window'] is True
    run(clickable._handle_button_click({'type': 'pin_window'}))
    assert clickable.config['appearance']['pin_window'] is False
    assert clickable.saved == 2 and clickable.dashboard.refreshed == 2
    assert clickable.service_dispatcher.clicks == []


@pytest.mark.parametrize("entity,state,blocked", [
    ("light.k", "unavailable", True), ("light.k", "unknown", True), ("light.k", "on", False),
    ("scene.s", "unknown", False), ("scene.s", "unavailable", True), ("button.b", "unknown", False),
])
def test_click_blocked_for_unavailable_entities(clickable, entity, state, blocked):
    clickable.ha_client = FakeClient({'state': state})
    cfg = {'entity_id': entity, 'label': ''}
    run(clickable._handle_button_click(cfg))
    assert bool(clickable.toasts) is blocked
    assert (clickable.service_dispatcher.clicks == []) is blocked


def test_blocked_label_falls_back_to_title_cased_entity_name(clickable):
    clickable.ha_client = FakeClient({'state': 'unavailable'})
    run(clickable._handle_button_click({'entity_id': 'light.living_room'}))
    assert clickable.toasts == ['Living Room']


def test_click_without_entity_dispatches_directly(clickable):
    clickable.ha_client = FakeClient(None)
    cfg = {'type': 'script'}
    run(clickable._handle_button_click(cfg))
    assert clickable.service_dispatcher.clicks == [cfg] and clickable.ha_client.asked == []


def tile(row, col, page=0, **extra):
    return {'type': 'switch', 'entity_id': f'light.r{row}c{col}p{page}', 'row': row, 'col': col, 'page': page, **extra}


def test_reorder_swaps_positions_and_saves(app):
    a, b = tile(0, 0), tile(0, 1)
    app.config['buttons'] = [a, b]
    app.on_buttons_reordered(0, 1)
    assert (a['row'], a['col']) == (0, 1) and (b['row'], b['col']) == (0, 0)
    assert app.saved == 1 and len(app.dashboard.set_calls) == 1


def test_reorder_moves_to_empty_cell(app):
    a = tile(0, 0)
    app.config['buttons'] = [a]
    app.on_buttons_reordered(0, 5)
    assert (a['row'], a['col']) == (1, 1)


def test_reorder_rejected_when_it_would_overlap(app):
    wide, other = tile(0, 0, span_x=2), tile(0, 2)
    app.config['buttons'] = [wide, other]
    app.on_buttons_reordered(0, 1)
    assert (wide['row'], wide['col']) == (0, 0) and app.saved == 0


def test_reorder_with_no_source_tile_is_noop(app):
    app.config['buttons'] = [tile(1, 1)]
    app.on_buttons_reordered(0, 1)
    assert app.saved == 0 and app.dashboard.set_calls == []


def test_reorder_replays_known_states_silently(app, monkeypatch):
    app.config['buttons'] = [tile(0, 0)]
    app.dashboard.entity_states = {'light.x': {'state': 'on', 'attributes': {}}}
    app.on_buttons_reordered(0, 1)
    assert app.dashboard.updates == [('light.x', False)]


def test_clear_removes_only_tile_on_current_page(app):
    keep, drop, other_page = tile(0, 1), tile(0, 0), tile(0, 0, page=1)
    app.config['buttons'] = [keep, drop, other_page]
    app.on_clear_button_requested(0)
    assert app.config['buttons'] == [keep, other_page] and app.saved == 1


def test_move_to_page_moves_with_original_span(app):
    src = tile(0, 0, span_x=2)
    app.config['buttons'] = [src]
    app.dashboard.empty[(1, 2, 1)] = (1, 0)
    app.on_move_to_page_requested(0, 1)
    moved = app.config['buttons'][0]
    assert (moved['page'], moved['row'], moved['col'], moved['span_x']) == (1, 1, 0, 2)


def test_move_to_full_page_notifies_and_keeps_tile(app, monkeypatch):
    from ui import notifications
    pages = []
    monkeypatch.setattr(notifications, 'notify_page_full', lambda d, n: pages.append(n))
    app.config['buttons'] = [tile(0, 0)]
    app.on_move_to_page_requested(0, 1)
    assert pages == [2] and app.config['buttons'][0]['page'] == 0


def test_move_as_1x1_fallback_asks_for_confirmation(app, monkeypatch):
    from ui import notifications
    asked = []
    monkeypatch.setattr(notifications, 'notify_move_as_1x1', lambda d, w, h, p, cb: asked.append((w, h, p, cb)))
    app.config['buttons'] = [tile(0, 0, span_x=2, span_y=2)]
    app.dashboard.empty[(1, 1, 1)] = (0, 3)
    app.on_move_to_page_requested(0, 1)
    assert asked[0][:3] == (2, 2, 2) and app.config['buttons'][0]['page'] == 0
    asked[0][3]()
    moved = app.config['buttons'][0]
    assert (moved['page'], moved['span_x'], moved['span_y'], moved['col']) == (1, 1, 1, 3)


def test_state_change_routes_media_art_and_images(app, monkeypatch, main_mod):
    tasks = []
    monkeypatch.setattr(main_mod, '_create_task_safe', lambda coro: (tasks.append(coro), coro.close()))
    monkeypatch.setattr(type(app), '_fetch_camera_image', lambda self, e: _noop(), raising=False)
    monkeypatch.setattr(type(app), '_fetch_image_entity', lambda self, e, s: _noop(), raising=False)
    monkeypatch.setattr(type(app), '_fetch_album_art', lambda self, e, s: _noop(), raising=False)
    app.on_state_changed('camera.door', {'state': 'idle', 'attributes': {}})
    app.on_state_changed('image.pic', {'state': 'x', 'attributes': {}})
    app.on_state_changed('media_player.tv', {'state': 'on', 'attributes': {'entity_picture': '/p'}})
    app.on_state_changed('media_player.tv2', {'state': 'on', 'attributes': {'media_content_type': 'music'}})
    app.on_state_changed('sensor.t', {'state': '1', 'attributes': {}}, live=False)
    assert len(tasks) == 3
    assert app.dashboard.media == [('media_player.tv2', None)]
    assert app.dashboard.updates[-1] == ('sensor.t', False) and app.dashboard.updates[0][1] is True


async def _noop():
    return None
