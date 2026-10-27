import pytest
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

from ui.button_edit_widget import ButtonEditWidget, HueSlider

ENTITIES = [
    {'entity_id': 'light.kitchen', 'attributes': {'friendly_name': 'Kitchen Light'}},
    {'entity_id': 'switch.fan', 'attributes': {'friendly_name': 'Fan'}},
    {'entity_id': 'sensor.temp', 'attributes': {'friendly_name': 'Temp'}},
    {'entity_id': 'sensor.print_state', 'attributes': {}},
    {'entity_id': 'script.go', 'attributes': {'friendly_name': 'Go'}},
    {'entity_id': 'climate.hall', 'attributes': {'friendly_name': 'Hall'}},
    {'entity_id': '', 'attributes': {}},
]


class FakeInput:
    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class Sig(QObject):
            recorded = pyqtSignal(dict)
        self._s = Sig()
        self.recorded = self._s.recorded
        self.calls = []

    def start_recording(self):
        self.calls.append('start')

    def restore_shortcut(self):
        self.calls.append('restore')


@pytest.fixture(autouse=True)
def reset_display_pref():
    ButtonEditWidget._global_show_friendly_names = True
    yield
    ButtonEditWidget._global_show_friendly_names = True


@pytest.fixture
def make(qtbot):
    def _make(config=None, entities=ENTITIES, **kw):
        w = ButtonEditWidget(entities, config, slot=3, **kw)
        qtbot.addWidget(w)
        return w
    return _make


def saved_of(w, qtbot):
    with qtbot.waitSignal(w.saved) as sig:
        w.save()
    return sig.args[0]


def set_type(w, type_name):
    idx = next(i for i, d in enumerate(w.TYPE_DEFINITIONS) if d[1] == type_name)
    w.type_combo.setCurrentIndex(idx)


def test_new_button_defaults_to_light_switch(make, qtbot):
    w = make()
    assert w._current_type() == 'switch' and w.selected_color == '#4285F4'
    cfg = saved_of(w, qtbot)
    assert cfg['slot'] == 3 and cfg['type'] == 'switch' and cfg['entity_id'] == ''
    assert cfg['custom_shortcut'] == {'enabled': False, 'value': ''}


def test_type_definitions_match_translated_list(make):
    pairs = ButtonEditWidget._get_type_definitions()
    assert [p[1] for p in pairs] == [d[1] for d in ButtonEditWidget.TYPE_DEFINITIONS]
    assert len({d[1] for d in ButtonEditWidget.TYPE_DEFINITIONS}) == len(pairs)


def test_entity_combo_filtered_by_type_and_sorted(make):
    w = make()
    ids = [w.entity_combo.itemData(i) for i in range(w.entity_combo.count())]
    assert ids == ['light.kitchen', 'switch.fan']
    set_type(w, 'widget')
    w.populate_entities()
    assert [w.entity_combo.itemData(i) for i in range(w.entity_combo.count())] == ['sensor.print_state', 'sensor.temp']


def test_entity_without_friendly_name_uses_id_and_empty_ids_skipped(make):
    w = make()
    set_type(w, 'widget')
    w.populate_entities()
    assert 'sensor.print_state' in [w.entity_combo.itemText(i) for i in range(w.entity_combo.count())]


def test_toggle_display_switches_names_and_ids_preserving_selection(make):
    w = make({'type': 'switch', 'entity_id': 'light.kitchen'})
    assert w.entity_combo.currentText() == 'Kitchen Light'
    w._toggle_entity_display()
    assert w.entity_combo.currentText() == 'light.kitchen'
    assert w._get_combo_entity_id(w.entity_combo) == 'light.kitchen'


def test_update_entities_keeps_selection(make):
    w = make({'type': 'switch', 'entity_id': 'switch.fan'})
    w.update_entities(ENTITIES + [{'entity_id': 'light.new', 'attributes': {}}])
    assert w._get_combo_entity_id(w.entity_combo) == 'switch.fan'
    w.update_entities([])
    assert w.entity_combo.count() == 0


def test_custom_typed_entity_is_kept(make, qtbot):
    w = make()
    w.entity_combo.setCurrentText('light.typed_by_hand')
    assert saved_of(w, qtbot)['entity_id'] == 'light.typed_by_hand'


def test_get_combo_entity_id_empty_text(make):
    w = make()
    w.entity_combo.setCurrentIndex(-1)
    w.entity_combo.setCurrentText('')
    assert w._get_combo_entity_id(w.entity_combo) == ''


def test_switch_service_saved_with_domain_prefix(make, qtbot):
    w = make({'type': 'switch', 'entity_id': 'light.kitchen', 'label': ' Kitchen '})
    w.service_combo.setCurrentIndex(w.service_combo.findText('turn_on'))
    cfg = saved_of(w, qtbot)
    assert cfg['service'] == 'light.turn_on' and cfg['label'] == 'Kitchen'


def test_load_existing_config_round_trips(make, qtbot):
    original = {'type': 'widget', 'entity_id': 'sensor.temp', 'label': 'T', 'icon': 'mdi:home', 'color': '#34A853',
                'precision': 2, 'display_style': 'gauge', 'sensor_min': 5.0, 'sensor_max': 50.0,
                'entry_animation': False, 'row': 1, 'col': 2, 'span_x': 2,
                'custom_shortcut': {'enabled': True, 'value': '<ctrl>+t'}}
    w = make(dict(original))
    cfg = saved_of(w, qtbot)
    for key, value in original.items():
        assert cfg[key] == value, key
    assert cfg['slot'] == 3


def test_changing_type_drops_stale_type_specific_keys(make, qtbot):
    w = make({'type': 'switch', 'entity_id': 'light.kitchen', 'service': 'light.toggle', 'precision': 3})
    set_type(w, 'scene')
    cfg = saved_of(w, qtbot)
    assert cfg['type'] == 'scene' and 'service' not in cfg and 'precision' not in cfg


def test_every_type_key_is_declared_for_a_known_type(make):
    known = {d[1] for d in ButtonEditWidget.TYPE_DEFINITIONS}
    for key, types in ButtonEditWidget.TYPE_SPECIFIC_KEYS.items():
        assert types <= known, key


@pytest.mark.parametrize("type_name", [d[1] for d in ButtonEditWidget.TYPE_DEFINITIONS])
def test_every_type_can_be_selected_and_saved(make, qtbot, type_name):
    w = make()
    set_type(w, type_name)
    cfg = saved_of(w, qtbot)
    assert cfg['type'] == type_name
    assert not w.grab().isNull()


def test_media_player_flags(make, qtbot):
    w = make({'type': 'media_player', 'entity_id': 'media_player.tv', 'show_album_art': False, 'animated_bg': False})
    cfg = saved_of(w, qtbot)
    assert cfg['show_album_art'] is False and cfg['animated_bg'] is False


def test_camera_defaults_span_and_size(make, qtbot):
    cfg = saved_of(make({'type': 'camera', 'entity_id': 'camera.door'}), qtbot)
    assert (cfg['span_x'], cfg['span_y'], cfg['camera_size'], cfg['camera_mode']) == (1, 1, 1, 'stream')
    cfg = saved_of(make({'type': 'camera', 'entity_id': 'camera.door', 'span_x': 2, 'span_y': 2}), qtbot)
    assert cfg['camera_size'] == 2


def test_script_arguments_typed_and_empty_keys_skipped(make, qtbot):
    w = make({'type': 'script', 'entity_id': 'script.go', 'script_variables': {'count': 3, 'ratio': 1.5, 'name': 'bob'}})
    assert len(w.script_arg_rows) == 3
    w._add_script_arg_row('', 'ignored')
    cfg = saved_of(w, qtbot)
    assert cfg['script_variables'] == {'count': 3, 'ratio': 1.5, 'name': 'bob'}


def test_script_args_removed_entirely(make, qtbot):
    w = make({'type': 'script', 'entity_id': 'script.go', 'script_variables': {'a': 1}})
    w._remove_script_arg_row(w.script_arg_rows[0])
    w._remove_script_arg_row({'widget': None})
    assert 'script_variables' not in saved_of(w, qtbot)
    w._add_script_arg_row('x', '7')
    w._clear_script_arg_rows()
    assert w.script_arg_rows == []


@pytest.mark.parametrize("btype,idx,expected", [("automation", 1, "trigger"), ("automation", 0, "toggle"),
                                                  ("lock", 0, "toggle"), ("lock", 1, "lock"), ("lock", 2, "unlock")])
def test_action_combos(make, qtbot, btype, idx, expected):
    w = make({'type': btype, 'entity_id': f'{btype}.x'})
    combo = w.automation_action_combo if btype == 'automation' else w.lock_action_combo
    combo.setCurrentIndex(idx)
    assert saved_of(w, qtbot)['action'] == expected


def test_printer_entities_round_trip_and_state_entity_becomes_entity_id(make, qtbot):
    cfg_in = {'type': '3d_printer', 'entity_id': 'sensor.print_state', 'printer_state_entity': 'sensor.print_state',
              'printer_nozzle_entity': 'sensor.temp'}
    w = make(cfg_in)
    cfg = saved_of(w, qtbot)
    assert cfg['printer_state_entity'] == 'sensor.print_state'
    assert cfg['printer_nozzle_entity'] == 'sensor.temp'
    assert cfg['entity_id'] == 'sensor.print_state'
    assert cfg['printer_bed_entity'] == ''


def test_display_style_controls_range_rows(make):
    w = make({'type': 'widget', 'entity_id': 'sensor.temp'})
    sizes = []
    w.size_changed.connect(lambda: sizes.append(1))
    w.display_style_combo.setCurrentIndex(2)
    assert sizes
    assert w.form.isRowVisible(w.sensor_min_spin) and not w.form.isRowVisible(w.entry_animation_toggle)
    w.display_style_combo.setCurrentIndex(1)
    assert w.form.isRowVisible(w.entry_animation_toggle)
    w.display_style_combo.setCurrentIndex(0)
    assert not w.form.isRowVisible(w.sensor_min_spin)


def test_select_color_preset_and_custom(make, qtbot):
    w = make()
    preset = w.color_buttons[1][1]
    w.select_color(preset)
    assert w.selected_color == preset and not w.rainbow_btn.isChecked()
    w.select_color('#123456')
    assert w.rainbow_btn.isChecked() and w.hex_input.text() == '#123456'
    assert saved_of(w, qtbot)['color'] == '#123456'


def test_hue_slider_sets_color(make):
    w = make()
    w.rainbow_btn.setChecked(True)
    w.hue_slider.set_hue(120)
    w.hue_slider.hue_changed.emit(120)
    assert w.selected_color == '#00FF00'


def test_hex_input_accepts_valid_and_ignores_invalid(make):
    w = make()
    w.hex_input.setText('#abcdef')
    w._on_hex_input_finished()
    assert w.selected_color == '#ABCDEF'
    w.hex_input.setText('zzzzzz')
    w._on_hex_input_finished()
    w.hex_input.setText('abc')
    w._on_hex_input_finished()
    assert w.selected_color == '#ABCDEF'


def test_custom_color_save_dedupe_and_delete(make, qtbot):
    w = make()
    got = []
    w.custom_colors_changed.connect(got.append)
    w.select_color('#102030')
    w._on_save_custom_color()
    w._on_save_custom_color()
    assert w.custom_colors == ['#102030'] and got == [['#102030']]
    w._delete_custom_color('#102030')
    assert w.custom_colors == [] and got[-1] == []
    assert w.selected_color != '#102030'


def test_edit_custom_color_replaces_old_swatch(make):
    w = make()
    w.set_custom_colors(['#111111'])
    assert w.custom_colors == ['#111111'] and len(w._custom_swatch_btns) == 1
    w._edit_custom_color('#111111')
    w.select_color('#222222')
    w._on_save_custom_color()
    assert w.custom_colors == ['#222222']
    w.set_custom_colors([])
    assert w._custom_swatch_btns == []


def test_shortcut_toggle_enables_recording_controls(make):
    im = FakeInput()
    w = make(input_manager=im)
    w.on_custom_shortcut_toggled(True)
    assert w.record_btn.isEnabled() and w.shortcut_display.isEnabled()
    w.on_custom_shortcut_toggled(False)
    assert not w.record_btn.isEnabled() and im.calls == ['restore']


def test_recording_flow_and_save_aborts_recording(make, qtbot):
    im = FakeInput()
    w = make({'type': 'switch', 'entity_id': 'light.kitchen', 'custom_shortcut': {'enabled': True, 'value': '<ctrl>+k'}},
             input_manager=im)
    w.record_btn.click()
    assert im.calls == ['start'] and w.record_btn.isChecked()
    im.recorded.emit({'value': '<alt>+z'})
    assert w.shortcut_display.text() == '<alt>+z' and not w.record_btn.isChecked()
    w.record_btn.click()
    cfg = saved_of(w, qtbot)
    assert not w.record_btn.isChecked()
    assert cfg['custom_shortcut'] == {'enabled': True, 'value': '<ctrl>+k'}


def test_recorded_shortcut_ignored_when_idle(make):
    im = FakeInput()
    w = make(input_manager=im)
    im.recorded.emit({'value': 'x'})
    assert w.shortcut_display.text() == ''


def test_recording_without_input_manager_unchecks(make):
    w = make()
    w.on_custom_shortcut_toggled(True)
    w.toggle_recording(True)
    assert not w.record_btn.isChecked()


def test_enter_saves_and_escape_cancels(make, qtbot):
    w = make()
    with qtbot.waitSignal(w.saved):
        qtbot.keyClick(w, Qt.Key.Key_Return)
    with qtbot.waitSignal(w.cancelled):
        qtbot.keyClick(w, Qt.Key.Key_Escape)
    qtbot.keyClick(w, Qt.Key.Key_A)


def test_hue_slider_maps_x_to_hue(qtbot):
    s = HueSlider()
    qtbot.addWidget(s)
    s.resize(360, 18)
    got = []
    s.hue_changed.connect(got.append)
    s._set_from_x(0)
    s._set_from_x(359)
    s._set_from_x(359)
    s._set_from_x(10000)
    assert got[-1] == 359 and got.count(359) == 1
    s.set_hue(1000)
    assert s.get_hue() == 359
    s.set_hue(-5)
    assert s.get_hue() == 0
    assert not s.grab().isNull()


def test_content_height_positive(make):
    assert make().get_content_height() > 0
