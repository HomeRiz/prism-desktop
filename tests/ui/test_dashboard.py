import copy

import pytest
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtCore import QEvent

from ui.constants import calculate_width
from ui.dashboard import Dashboard
from ui.theme_manager import ThemeManager

BUTTONS = [
    {'type': 'switch', 'entity_id': 'light.kitchen', 'label': 'Kitchen', 'row': 0, 'col': 0},
    {'type': 'widget', 'entity_id': 'sensor.temp', 'label': 'Temp', 'row': 1, 'col': 2, 'span_x': 2},
    {'type': 'script', 'entity_id': 'script.go', 'label': 'Go', 'row': 0, 'col': 1, 'page': 1},
]
APPEARANCE = {'pages': 2}


@pytest.fixture
def make_dashboard(qtbot):
    def _make(buttons=None, rows=2, cols=4, appearance=None, theme=True):
        cfg = {'appearance': dict(appearance or {})}
        d = Dashboard(cfg, ThemeManager() if theme else None, None, "1.0", rows=rows, cols=cols)
        qtbot.addWidget(d)
        d.set_buttons(copy.deepcopy(buttons if buttons is not None else BUTTONS), APPEARANCE)
        return d
    return _make


@pytest.fixture
def dash(make_dashboard):
    return make_dashboard()


def by_slot(d, slot):
    return next(b for b in d.buttons if b.slot == slot)


def by_entity(d, entity):
    return next(b for b in d.buttons if b.config.get('entity_id') == entity)


def test_grid_builds_one_button_per_cell(dash):
    assert len(dash.buttons) == dash.rows * dash.cols == 8
    assert sorted(b.slot for b in dash.buttons) == list(range(8))


def test_configured_buttons_land_on_their_cells(dash):
    assert by_entity(dash, 'light.kitchen').slot == 0
    wide = by_entity(dash, 'sensor.temp')
    assert wide.slot == 6 and (wide.span_x, wide.span_y) == (2, 1)
    assert dash.grid.itemAtPosition(1, 2).widget() is wide


def test_other_page_buttons_are_not_shown(dash):
    assert all(b.config.get('entity_id') != 'script.go' for b in dash.buttons)
    assert len(dash.all_button_configs) == 3


def test_empty_cells_are_add_buttons_and_hidden_cell_under_span(dash):
    empties = [b for b in dash.buttons if not b.config]
    assert len(empties) == 6
    assert [b.isVisibleTo(dash) for b in dash.buttons if b.slot == 7] == [False]


def test_button_config_row_col_written_back(dash):
    wide = by_entity(dash, 'sensor.temp')
    assert (wide.config['row'], wide.config['col']) == (1, 2)


def test_oversized_button_becomes_forbidden_placeholder(make_dashboard):
    d = make_dashboard([{'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 3, 'span_x': 2}])
    forbidden = [b for b in d.buttons if b.config.get('type') == 'forbidden']
    assert len(forbidden) == 1 and forbidden[0].slot == 3
    assert not any(b.config.get('entity_id') == 'light.a' for b in d.buttons)


def test_colliding_buttons_second_hidden(make_dashboard):
    d = make_dashboard([
        {'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 0},
        {'type': 'switch', 'entity_id': 'light.b', 'row': 0, 'col': 0},
    ])
    ents = [b.config.get('entity_id') for b in d.buttons if b.isVisibleTo(d) and b.config.get('entity_id')]
    assert ents == ['light.a']


def test_out_of_grid_config_skipped(make_dashboard):
    d = make_dashboard([{'type': 'switch', 'entity_id': 'light.a', 'row': 9, 'col': 9}])
    assert all(not b.config for b in d.buttons)


def test_pin_window_config_counts_as_configured(make_dashboard):
    d = make_dashboard([{'type': 'pin_window', 'row': 0, 'col': 0}])
    assert d.buttons[0].config['type'] == 'pin_window'
    d.refresh_pin_buttons()
    assert d.buttons[0]._app_config is d.config


def test_entity_state_update_reaches_matching_button_and_cache(dash):
    dash.update_entity_state('light.kitchen', {'state': 'on', 'attributes': {}})
    assert by_entity(dash, 'light.kitchen')._state == 'on'
    assert dash.entity_states['light.kitchen']['state'] == 'on'


def test_entity_state_for_unknown_entity_is_cached_only(dash):
    dash.update_entity_state('sensor.other', {'state': '1', 'attributes': {}})
    assert 'sensor.other' in dash.entity_states
    assert all(b._state == 'off' for b in dash.buttons)


def test_cached_state_applied_when_button_assigned_later(make_dashboard):
    d = make_dashboard([])
    d.update_entity_state('light.new', {'state': 'on', 'attributes': {}})
    d.set_buttons([{'type': 'switch', 'entity_id': 'light.new', 'row': 0, 'col': 0}], APPEARANCE)
    assert by_entity(d, 'light.new')._state == 'on'


def test_widget_state_formats_value_with_unit(dash):
    dash.update_entity_state('sensor.temp', {'state': '21.5', 'attributes': {'unit_of_measurement': 'W'}})
    assert by_entity(dash, 'sensor.temp').value_label.text() == '21.5W'


def test_live_update_flashes_indicator_only_when_live(make_dashboard):
    d = make_dashboard([{'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 0}], appearance={})
    btn = by_entity(d, 'light.a')
    btn.refresh_indicators_enabled = True
    d.update_entity_state('light.a', {'state': 'on', 'attributes': {}})
    assert btn.refresh_flash_anim.state() != btn.refresh_flash_anim.State.Running
    d.update_entity_state('light.a', {'state': 'off', 'attributes': {}}, live=True)
    assert btn.refresh_flash_anim.state() == btn.refresh_flash_anim.State.Running


def test_printer_secondary_entities_trigger_redraw_not_state(make_dashboard):
    d = make_dashboard([{'type': '3d_printer', 'entity_id': 'sensor.printer', 'row': 0, 'col': 0,
                         'printer_state_entity': 'sensor.pstate', 'printer_camera_entity': 'camera.p',
                         'printer_nozzle_entity': 'sensor.nozzle', 'printer_bed_entity': 'sensor.bed'}])
    btn = d.buttons[0]
    d.update_entity_state('sensor.pstate', {'state': 'printing', 'attributes': {}})
    assert btn._state == 'printing'
    d.update_entity_state('sensor.nozzle', {'state': '200', 'attributes': {}})
    assert btn._state == 'printing'


def test_camera_image_updates_camera_and_printer_buttons(make_dashboard):
    d = make_dashboard([
        {'type': 'camera', 'entity_id': 'camera.door', 'row': 0, 'col': 0},
        {'type': '3d_printer', 'entity_id': 'sensor.p', 'row': 0, 'col': 1, 'printer_camera_entity': 'camera.p'},
    ])
    pm = QPixmap(64, 48)
    pm.fill(Qt.GlobalColor.red)
    d.update_camera_image('camera.door', pm)
    d.update_camera_image('camera.p', pm)
    assert by_entity(d, 'camera.door')._last_camera_pixmap is pm
    assert by_entity(d, 'sensor.p')._last_camera_pixmap is pm


def test_apply_camera_cache_ignores_malformed_entries(make_dashboard):
    d = make_dashboard([{'type': 'camera', 'entity_id': 'camera.door', 'row': 0, 'col': 0}])
    pm = QPixmap(10, 10)
    pm.fill(Qt.GlobalColor.blue)
    d.apply_camera_cache({'camera.door': (123.0, pm), 'camera.x': 'bad', 'camera.y': (1,)})
    assert d.buttons[0]._last_camera_pixmap is pm


def test_media_art_goes_to_media_player_only(make_dashboard):
    d = make_dashboard([{'type': 'media_player', 'entity_id': 'media_player.tv', 'row': 0, 'col': 0},
                        {'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 1}])
    pm = QPixmap(8, 8)
    d.update_media_art('media_player.tv', pm)
    d.update_media_art('light.a', pm)
    assert by_entity(d, 'media_player.tv')._album_art is pm
    assert by_entity(d, 'light.a')._album_art is None


def test_click_on_configured_button_emits_config(dash, qtbot):
    btn = by_entity(dash, 'light.kitchen')
    with qtbot.waitSignal(dash.button_clicked) as sig:
        btn.clicked.emit(btn.config)
    assert sig.args == [btn.config]


def test_click_on_empty_button_requests_add_for_its_slot(dash, qtbot):
    empty = by_slot(dash, 2)
    with qtbot.waitSignal(dash.add_button_clicked) as sig:
        empty.clicked.emit({})
    assert sig.args == [2]


def test_click_on_forbidden_slot_is_ignored(dash, qtbot):
    with qtbot.assertNotEmitted(dash.button_clicked), qtbot.assertNotEmitted(dash.add_button_clicked):
        dash._on_button_clicked(1, {'type': 'forbidden'})


def test_overlay_service_request_is_forwarded(dash, qtbot):
    with qtbot.waitSignal(dash.button_clicked) as sig:
        dash.overlay_manager.service_request.emit({'a': 1})
    assert sig.args == [{'a': 1}]


def test_button_signals_forwarded(dash, qtbot):
    btn = by_entity(dash, 'light.kitchen')
    with qtbot.waitSignal(dash.edit_button_requested) as s1:
        btn.edit_requested.emit(0)
    with qtbot.waitSignal(dash.clear_button_requested) as s2:
        btn.clear_requested.emit(0)
    with qtbot.waitSignal(dash.move_to_page_requested) as s3:
        btn.move_to_page_requested.emit(0, 1)
    with qtbot.waitSignal(dash.volume_scroll_requested) as s4:
        btn.volume_scroll.emit('media_player.x', 0.4)
    assert (s1.args, s2.args, s3.args, s4.args) == ([0], [0], [0, 1], ['media_player.x', 0.4])


def test_buttons_dropped_emits_reordered(dash, qtbot):
    with qtbot.waitSignal(dash.buttons_reordered) as sig:
        dash.on_button_dropped(0, 3)
    assert sig.args == [0, 3]


def test_drop_allowed_rules(dash):
    kitchen = by_entity(dash, 'light.kitchen')
    assert dash._drop_allowed(kitchen, 2) is True
    assert dash._drop_allowed(kitchen, 6) is True
    assert dash._drop_allowed(kitchen, 7) is False
    assert dash._drop_allowed(by_slot(dash, 2), 3) is False
    assert dash._drop_allowed(None, 3) is False


def test_page_navigation_clamps_and_emits(dash, qtbot):
    with qtbot.waitSignal(dash.page_change_requested) as sig:
        dash.switch_to_page(1)
    assert sig.args == [1] and dash.current_page == 1
    assert by_entity(dash, 'script.go').slot == 1
    with qtbot.assertNotEmitted(dash.page_change_requested):
        dash.switch_to_page(5)
        dash.jump_to_page(1)
    dash.jump_to_page(-3)
    assert dash.current_page == 0
    assert all(b.config.get('entity_id') != 'script.go' for b in dash.buttons)


def test_page_count_shrink_resets_current_page(dash):
    dash.jump_to_page(1)
    dash.set_buttons(BUTTONS, {'pages': 1})
    assert dash.current_page == 0
    assert not dash.btn_page_indicator.isVisibleTo(dash)


def test_empty_slot_search_current_and_other_page(dash):
    dash.show()
    assert dash.get_first_empty_slot() == (0, 1)
    assert dash.get_first_empty_slot(span_x=3, span_y=2) == (-1, -1)
    assert dash.find_first_empty_slot_on_page(1) == (0, 0)
    assert dash.find_first_empty_slot_on_page(0, span_x=2) == (0, 1)


def test_find_empty_slot_none_when_page_full(make_dashboard):
    full = [{'type': 'switch', 'entity_id': f'light.{i}', 'row': i // 2, 'col': i % 2} for i in range(4)]
    d = make_dashboard(full, rows=2, cols=2)
    assert d.find_first_empty_slot_on_page(0) == (-1, -1)


def test_resize_expands_and_relocates_neighbour(dash):
    kitchen = by_entity(dash, 'light.kitchen')
    neighbour_cfg = {'type': 'switch', 'entity_id': 'light.b', 'row': 0, 'col': 1}
    dash.set_buttons(BUTTONS + [neighbour_cfg], APPEARANCE)
    kitchen = by_entity(dash, 'light.kitchen')
    dash.handle_button_resize(kitchen.slot, 2, 1)
    assert kitchen.config['span_x'] == 2
    moved = by_entity(dash, 'light.b')
    assert (moved.config['row'], moved.config['col']) != (0, 1)


def test_resize_blocked_when_nowhere_to_relocate(make_dashboard):
    cfgs = [{'type': 'switch', 'entity_id': f'light.{i}', 'row': i // 2, 'col': i % 2} for i in range(4)]
    d = make_dashboard(cfgs, rows=2, cols=2)
    a = by_entity(d, 'light.0')
    d.handle_button_resize(a.slot, 2, 1)
    assert a.config.get('span_x', 1) == 1


def test_resize_clamped_to_grid_edge(dash):
    wide = by_entity(dash, 'sensor.temp')
    dash.handle_button_resize(wide.slot, 4, 5)
    assert wide.config['span_x'] == 2 and wide.config['span_y'] == 1


def test_resize_ignores_unknown_slot_and_empty_button(dash):
    dash.handle_button_resize(99, 2, 2)
    dash.handle_button_resize(2, 2, 2)


def test_resize_finished_saves(dash, qtbot):
    with qtbot.waitSignal(dash.save_config_requested):
        dash.handle_button_resize_finished()


def test_printer_resize_grows_rows(make_dashboard):
    d = make_dashboard([{'type': '3d_printer', 'entity_id': 'sensor.p', 'row': 0, 'col': 0}], rows=1)
    d.handle_button_resize(0, 1, 2)
    assert d.rows == 2 and len(d.buttons) == 8
    assert d.config['appearance']['rows'] == 2


def test_target_height_formula(dash):
    h1, h2 = dash._calculate_target_height(1), dash._calculate_target_height(2)
    assert h2 - h1 == 80 + 8


def test_toast_lifecycle_and_confirm_priority(dash, qtbot):
    dash.show_toast("hello", duration_ms=0)
    first = dash._active_banner
    assert first.banner_type == "toast" and first.label.text() == "hello"
    dash.update_toast("changed")
    assert dash._active_banner is first and first.label.text() == "changed"
    confirmed = []
    dash.show_confirm("sure?", on_confirm=lambda: confirmed.append(1))
    banner = dash._active_banner
    assert banner is not first and banner.banner_type == "confirm"
    dash.show_toast("ignored")
    assert dash._active_banner is banner
    dash._dismiss_banner()
    assert dash._active_banner is None


def test_update_toast_without_active_banner_creates_one(dash):
    dash.update_toast("new")
    assert dash._active_banner.label.text() == "new"


def test_confirm_callbacks_fire_and_banner_dismissed(dash, qtbot):
    got = []
    dash.show_confirm("x", on_confirm=lambda: got.append("yes"), on_reject=lambda: got.append("no"))
    banner = dash._active_banner
    banner.rejected.emit()
    assert got == ["no"] and dash._active_banner is None


def test_theme_change_invalidates_button_styles(make_dashboard):
    d = make_dashboard()
    btn = d.buttons[0]
    btn.update_style()
    assert btn._style_fp is not None
    d.theme_manager.set_theme('light')
    assert btn._style_fp is None or btn._style_fp[-1] == 'light'


def test_set_cols_updates_engine_and_width(dash):
    dash.set_cols(5)
    assert dash.cols == 5
    assert dash._fixed_width == calculate_width(5)
    assert dash.grid_manager.layout_engine.cols == 5


def test_set_rows_same_value_noop_and_animates_otherwise(dash):
    dash.set_rows(2)
    assert dash._pending_rows_update is None
    dash.set_rows(3)
    assert dash._pending_rows_update == 3


def make_key(key, text="", mods=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, key, mods, text)


@pytest.mark.parametrize("shortcut,key,text,mods,expected", [
    ("a", Qt.Key.Key_A, "a", Qt.KeyboardModifier.NoModifier, True),
    ("a", Qt.Key.Key_B, "b", Qt.KeyboardModifier.NoModifier, False),
    ("<ctrl>+a", Qt.Key.Key_A, "\x01", Qt.KeyboardModifier.ControlModifier, True),
    ("<ctrl>+a", Qt.Key.Key_A, "a", Qt.KeyboardModifier.NoModifier, False),
    ("<ctrl>+<shift>+1", Qt.Key.Key_1, "1", Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, True),
    ("<alt>+<f5>", Qt.Key.Key_F5, "", Qt.KeyboardModifier.AltModifier, True),
    ("<esc>", Qt.Key.Key_Escape, "", Qt.KeyboardModifier.NoModifier, True),
    ("<space>", Qt.Key.Key_Space, " ", Qt.KeyboardModifier.NoModifier, True),
    ("<esc>", Qt.Key.Key_Tab, "", Qt.KeyboardModifier.NoModifier, False),
    ("<ctrl>", Qt.Key.Key_Control, "", Qt.KeyboardModifier.ControlModifier, False),
    ("", Qt.Key.Key_A, "a", Qt.KeyboardModifier.NoModifier, False),
    ("<page_down>", Qt.Key.Key_PageDown, "", Qt.KeyboardModifier.NoModifier, True),
    ("<unknown>", Qt.Key.Key_A, "a", Qt.KeyboardModifier.NoModifier, False),
])
def test_matches_pynput_shortcut(dash, shortcut, key, text, mods, expected):
    assert dash.matches_pynput_shortcut(make_key(key, text, mods), shortcut) is expected


def test_custom_shortcut_triggers_button_click(make_dashboard, qtbot):
    d = make_dashboard([{'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 0,
                         'custom_shortcut': {'enabled': True, 'value': '<ctrl>+k'}},
                        {'type': 'switch', 'entity_id': 'light.b', 'row': 0, 'col': 1,
                         'custom_shortcut': {'enabled': False, 'value': 'x'}}])
    with qtbot.waitSignal(d.button_clicked) as sig:
        d.keyPressEvent(make_key(Qt.Key.Key_K, "\x0b", Qt.KeyboardModifier.ControlModifier))
    assert sig.args[0]['entity_id'] == 'light.a'
    with qtbot.assertNotEmitted(d.button_clicked):
        d.keyPressEvent(make_key(Qt.Key.Key_X, "x"))


def test_dashboard_renders_after_show(dash):
    dash.show()
    assert not dash.grab().isNull()
