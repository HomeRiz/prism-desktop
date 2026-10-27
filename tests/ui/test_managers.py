import copy

import pytest
from PyQt6.QtCore import QRect, QPoint

from ui.dashboard import Dashboard
from ui.managers.grid_manager import GridManager, VirtualButton
from ui.managers import overlay_manager as om_mod
from ui.theme_manager import ThemeManager
from ui.widgets import overlays as ov

CFGS = [
    {'type': 'switch', 'entity_id': 'light.a', 'label': 'A', 'row': 0, 'col': 0},
    {'type': 'climate', 'entity_id': 'climate.c', 'label': 'C', 'row': 0, 'col': 1},
    {'type': 'curtain', 'entity_id': 'cover.k', 'label': 'K', 'row': 0, 'col': 2},
    {'type': 'alarm_control_panel', 'entity_id': 'alarm_control_panel.h', 'label': 'H', 'row': 1, 'col': 0},
]


@pytest.fixture(autouse=True)
def fast_overlays(monkeypatch):
    for name in ('MORPH_OPEN_DURATION', 'MORPH_CLOSE_DURATION', 'CONTENT_FADE_DURATION'):
        monkeypatch.setattr(ov, name, 20)


@pytest.fixture
def dash(qtbot):
    d = Dashboard({'appearance': {}}, ThemeManager(), None, "1.0", rows=2, cols=4)
    qtbot.addWidget(d)
    d.set_buttons(copy.deepcopy(CFGS), {'pages': 1})
    d.show()
    return d


@pytest.fixture
def om(dash):
    return dash.overlay_manager


@pytest.fixture
def emitted(om):
    calls = []
    om.service_request.connect(calls.append)
    return calls


def btn(dash, entity):
    return next(b for b in dash.buttons if b.config.get('entity_id') == entity)


def rect_of(dash, entity):
    b = btn(dash, entity)
    return QRect(b.mapToGlobal(QPoint(0, 0)), b.size())


def test_virtual_button_copies_spans():
    v = VirtualButton({'span_x': 3, 'span_y': 2, 'entity_id': 'x'})
    assert (v.span_x, v.span_y) == (3, 2) and v.config['entity_id'] == 'x'
    d = VirtualButton({})
    assert (d.span_x, d.span_y) == (1, 1)


def test_grid_manager_tracks_cols(dash):
    gm = dash.grid_manager
    assert isinstance(gm, GridManager) and gm.layout_engine.cols == 4
    gm.update_cols(6)
    assert gm.layout_engine.cols == 6


def test_set_buttons_filters_by_page_and_applies_appearance(dash):
    configs = copy.deepcopy(CFGS) + [{'type': 'switch', 'entity_id': 'light.p2', 'row': 0, 'col': 3, 'page': 1}]
    dash.grid_manager.set_buttons(configs, {'border_effect': 'Aurora Borealis', 'show_dimming': True,
                                            'button_style': 'Flat', 'temperature_unit': 'fahrenheit',
                                            'refresh_indicators': True})
    assert dash._border_effect == 'Aurora Borealis' and dash._show_dimming is True
    assert dash._temperature_unit == 'fahrenheit'
    assert len(dash._button_configs) == 4
    assert dash._all_button_configs is configs
    b = btn(dash, 'light.a')
    assert b.button_style == 'Flat' and b.refresh_indicators_enabled is True
    assert b.temperature_unit_preference == 'fahrenheit'


def test_set_buttons_reuses_state_when_entity_unchanged(dash):
    b = btn(dash, 'light.a')
    b.set_state('on')
    dash.grid_manager.set_buttons(copy.deepcopy(CFGS))
    assert btn(dash, 'light.a')._state == 'on'


def test_set_buttons_resets_button_when_entity_changes(dash):
    dash.update_entity_state('light.a', {'state': 'on', 'attributes': {}})
    changed = copy.deepcopy(CFGS)
    changed[0]['entity_id'] = 'light.z'
    dash.grid_manager.set_buttons(changed)
    assert btn(dash, 'light.z')._state == 'off'


def test_set_buttons_grows_button_pool_with_rows(dash):
    dash._rows = 3
    dash.grid_manager.set_buttons(copy.deepcopy(CFGS))
    assert len(dash.buttons) == 12


def test_oversized_config_becomes_virtual_and_forbidden(dash):
    cfg = [{'type': 'switch', 'entity_id': 'light.w', 'row': 0, 'col': 3, 'span_x': 3}]
    dash.grid_manager.set_buttons(cfg)
    assert len(dash._virtual_buttons) == 1
    assert [b.config.get('type') for b in dash.buttons if b.slot == 3] == ['forbidden']


def test_rebuild_assigns_slots_and_hides_unplaced(dash):
    dash.grid_manager.rebuild_grid(preview_mode=True, update_height=False)
    assert sorted(b.slot for b in dash.buttons if b.isVisibleTo(dash)) == list(range(8))
    assert btn(dash, 'climate.c').slot == 1


def test_rebuild_preview_does_not_write_positions(dash):
    b = btn(dash, 'light.a')
    b.config['row'] = 0
    b.config['col'] = 0
    dash.grid_manager.rebuild_grid(preview_mode=True, update_height=False)
    assert (b.config['row'], b.config['col']) == (0, 0)


def test_rebuild_height_animation_started_when_rows_change(dash):
    dash._rows = 3
    dash.grid_manager.rebuild_grid(update_height=True)
    assert dash.height_anim.endValue() > dash.height()


def test_overlay_manager_initial_state(om):
    assert om.any_overlay_open() is False


def test_emit_service_adds_skip_debounce_once(om, emitted):
    om._emit_service({"service": "x"})
    om._emit_service({"service": "y", "skip_debounce": False})
    assert emitted[0]["skip_debounce"] is True and emitted[1]["skip_debounce"] is False


def test_dimmer_open_sets_initial_value_from_brightness(dash, om, qtbot):
    dash.update_entity_state('light.a', {'state': 'on', 'attributes': {'brightness': 127}})
    om.start_dimmer(btn(dash, 'light.a').slot, rect_of(dash, 'light.a'), btn(dash, 'light.a').config)
    assert om.dimmer_overlay.isVisible() and om.any_overlay_open()
    assert om.dimmer_overlay._value == 49
    assert om._active_dimmer_entity == 'light.a'


def test_dimmer_ignores_missing_config_or_entity(dash, om):
    om.start_dimmer(0, QRect(0, 0, 10, 10), {})
    om.start_dimmer(0, QRect(0, 0, 10, 10), {'type': 'switch'})
    assert not om.dimmer_overlay.isVisible()


def test_dimmer_live_updates_and_final_value(dash, om, emitted):
    om._active_dimmer_entity = 'light.a'
    om._active_dimmer_type = 'switch'
    om._live_dimming = True
    om.on_dimmer_value_changed(40)
    om.process_pending_dimmer()
    assert emitted[-1]["service"] == "light.turn_on"
    assert emitted[-1]["service_data"] == {"brightness_pct": 40}
    om.on_dimmer_value_changed(60)
    om.process_pending_dimmer()
    om.on_dimmer_finished()
    assert emitted[-1]["service_data"] == {"brightness_pct": 60}
    assert om._active_dimmer_entity is None


def test_dimmer_pending_without_active_entity_is_dropped(om, emitted):
    om.on_dimmer_value_changed(10)
    om.process_pending_dimmer()
    assert emitted == []


def test_curtain_sends_only_on_release(om, emitted):
    om._active_dimmer_entity = 'cover.k'
    om._active_dimmer_type = 'curtain'
    om._live_dimming = True
    om.on_dimmer_value_changed(30)
    om.process_pending_dimmer()
    assert emitted == []
    om.on_dimmer_finished()
    assert emitted[0]["service"] == "cover.set_cover_position"
    assert emitted[0]["service_data"] == {"position": 30}


def test_volume_release_sends_fraction(om, emitted):
    om._active_dimmer_entity = 'media_player.tv'
    om._active_dimmer_type = 'media_player'
    om.on_dimmer_value_changed(25)
    om.process_pending_dimmer()
    om.on_dimmer_finished()
    assert emitted[0]["service"] == "media_player.volume_set"
    assert emitted[0]["service_data"] == {"volume_level": 0.25}


def test_climate_actions_require_active_entity(om, emitted):
    om.on_climate_mode_changed('heat')
    om.on_climate_fan_changed('low')
    om.on_climate_value_changed(21)
    om.process_pending_climate()
    assert emitted == []


def test_climate_actions_emit_services(om, emitted):
    om._active_climate_entity = 'climate.c'
    om.on_climate_mode_changed('cool')
    om.on_climate_fan_changed('high')
    om.on_climate_value_changed(22.5)
    om.process_pending_climate()
    services = {c["service"]: c["service_data"] for c in emitted}
    assert services["climate.set_hvac_mode"] == {"hvac_mode": "cool"}
    assert services["climate.set_fan_mode"] == {"fan_mode": "high"}
    assert services["climate.set_temperature"] == {"temperature": 22.5}


def test_climate_temperature_converted_to_source_unit(dash, om, emitted):
    dash.update_entity_state('climate.c', {'state': 'heat', 'attributes': {'temperature_unit': '°F'}})
    om.set_temperature_unit_preference('celsius')
    om._active_climate_entity = 'climate.c'
    om.on_climate_value_changed(20)
    om.process_pending_climate()
    assert emitted[0]["service_data"]["temperature"] == pytest.approx(68, abs=0.5)


def test_climate_open_and_close_cycle(dash, om, qtbot):
    b = btn(dash, 'climate.c')
    om.start_climate(b.slot, rect_of(dash, 'climate.c'), b.config)
    assert om.climate_overlay.isVisible() and om._active_climate_entity == 'climate.c'
    with qtbot.waitSignal(om.climate_overlay.finished, timeout=5000):
        om.close_all_overlays_animated()
    assert om._active_climate_entity is None
    assert om.any_overlay_open() is False


def test_second_open_while_open_is_queued_then_run(dash, om, qtbot):
    a, c = btn(dash, 'light.a'), btn(dash, 'climate.c')
    om.start_dimmer(a.slot, rect_of(dash, 'light.a'), a.config)
    qtbot.waitUntil(lambda: om.dimmer_overlay.get_content_opacity() >= 1.0, timeout=5000)
    om.start_climate(c.slot, rect_of(dash, 'climate.c'), c.config)
    assert om._pending_open_action is not None
    qtbot.waitUntil(lambda: om.climate_overlay.isVisible(), timeout=5000)
    assert om._pending_open_action is None


def test_same_button_tap_toggles_overlay_off(dash, om, qtbot):
    a = btn(dash, 'light.a')
    om.start_dimmer(a.slot, rect_of(dash, 'light.a'), a.config)
    qtbot.waitUntil(lambda: om.dimmer_overlay.get_content_opacity() >= 1.0, timeout=5000)
    with qtbot.waitSignal(om.dimmer_overlay.finished, timeout=5000):
        om.start_dimmer(a.slot, rect_of(dash, 'light.a'), a.config)
    assert om._pending_open_action is None


def test_close_all_overlays_is_instant(dash, om):
    a = btn(dash, 'light.a')
    om.start_dimmer(a.slot, rect_of(dash, 'light.a'), a.config)
    om.close_all_overlays()
    assert not om.any_overlay_open() and om._active_dimmer_entity is None


def test_parent_resize_closes_overlays(dash, om):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QResizeEvent
    a = btn(dash, 'light.a')
    om.start_dimmer(a.slot, rect_of(dash, 'light.a'), a.config)
    assert om.eventFilter(dash, QResizeEvent(dash.size(), dash.size())) is False
    assert not om.any_overlay_open()
    assert om.eventFilter(om, QEvent(QEvent.Type.Resize)) is False


def test_printer_actions_use_configured_entities(om, emitted):
    om.on_printer_action('pause')
    om._active_printer_config = {'printer_pause_entity': 'button.pause', 'printer_stop_entity': 'button.stop'}
    for action in ('pause', 'resume', 'stop', 'other'):
        om.on_printer_action(action)
    assert [(c["service"], c["entity_id"]) for c in emitted] == [
        ("button.press", "button.pause"), ("button.press", "button.pause"), ("button.press", "button.stop")]
    om._active_printer_config = {}
    om.on_printer_action('stop')
    assert len(emitted) == 3


def test_alarm_action_builds_service_name_and_code(om, emitted):
    om.on_alarm_action('arm_home', '')
    assert emitted == []
    om._active_alarm_entity = 'alarm_control_panel.h'
    om.on_alarm_action('disarm', '1234')
    om.on_alarm_action('arm_away', '')
    assert emitted[0]["service"] == "alarm_control_panel.alarm_disarm"
    assert emitted[0]["service_data"] == {"code": "1234"}
    assert emitted[1]["service_data"] == {}


def test_alarm_overlay_opens_and_keypad_resizes(dash, om, qtbot):
    b = btn(dash, 'alarm_control_panel.h')
    om.start_alarm(b.slot, rect_of(dash, 'alarm_control_panel.h'), b.config)
    assert om.alarm_overlay.isVisible()
    qtbot.waitUntil(lambda: om.alarm_overlay.get_content_opacity() >= 1.0, timeout=5000)
    before = om._size_alarm_rect(b, QRect(0, 0, 300, 100), rows=2).height()
    after = om._size_alarm_rect(b, QRect(0, 0, 300, 100), rows=3).height()
    assert after >= before
    om.on_alarm_keypad_toggled(True)
    om.on_alarm_keypad_toggled(False)


def test_entity_updates_reach_visible_overlays_only(dash, om):
    state = {'state': 'cool', 'attributes': {'fan_mode': 'low'}}
    om.update_entity_state('climate.c', state)
    assert om.climate_overlay._current_hvac_mode == 'off'
    b = btn(dash, 'climate.c')
    om.start_climate(b.slot, rect_of(dash, 'climate.c'), b.config)
    om.update_entity_state('climate.c', state)
    assert om.climate_overlay._current_hvac_mode == 'cool'
    om.update_entity_state('climate.other', {'state': 'heat', 'attributes': {}})
    assert om.climate_overlay._current_hvac_mode == 'cool'


def test_border_effect_propagates_to_overlays(om):
    om.set_border_effect('Prism Shard')
    assert om._border_effect == 'Prism Shard'
    assert om.dimmer_overlay._border_effect == 'Prism Shard'


def test_fade_opacity_for_coverage_bounds():
    f = om_mod.OverlayManager._fade_opacity_for_coverage
    full = f(QRect(0, 0, 100, 100), QRect(10, 10, 20, 20))
    none = f(QRect(0, 0, 100, 100), QRect(500, 500, 20, 20))
    assert 0.0 <= full <= 1.0 and none == 1.0
    assert full < none
