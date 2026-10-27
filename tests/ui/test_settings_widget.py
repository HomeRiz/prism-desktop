import copy
import sys

import pytest

from ui import settings_widget as sw_mod
from ui.settings_widget import SettingsWidget, _ShortcutRow
from ui.theme_manager import ThemeManager
from core import localization_manager as loc

CONFIG = {
    'home_assistant': {'url': 'http://ha.local:8123', 'token': 'secret-token'},
    'appearance': {'theme': 'light', 'tray_position': 'top', 'temperature_unit': 'fahrenheit',
                   'border_effect': 'Aurora Borealis', 'button_style': 'Flat', 'show_dimming': True,
                   'refresh_indicators': True, 'pin_window': True, 'pages': 2, 'language': 'en'},
    'mobile_app': {'send_logged_in': False, 'send_cpu': True, 'send_ram': True, 'send_system': True,
                   'send_presence': True},
    'shortcut': {'value': '<ctrl>+<alt>+p'},
    'assist': {'enabled': True, 'show_in_footer': False, 'auto_listen': True},
    'buttons': [
        {'type': 'switch', 'entity_id': 'light.a', 'row': 0, 'col': 0, 'custom_shortcut': {'enabled': True, 'value': '<ctrl>+k'}},
        {'type': 'switch', 'entity_id': 'light.b', 'row': 0, 'col': 1, 'custom_shortcut': {'enabled': False, 'value': 'x'}},
    ],
}


class FakeInput:
    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class Sig(QObject):
            recorded = pyqtSignal(dict)
        self._sig = Sig()
        self.recorded = self._sig.recorded
        self.calls = []

    def start_recording(self):
        self.calls.append('start')

    def restore_shortcut(self):
        self.calls.append('restore')

    def update_shortcut(self, sc):
        self.calls.append(('update', sc))


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(SettingsWidget, '_trigger_auto_test', lambda self: None)
    monkeypatch.setattr(sw_mod, 'is_kde_wayland_session', lambda: False)
    monkeypatch.setattr(sw_mod, 'is_wayland_session', lambda: False)
    monkeypatch.setattr(sw_mod, 'supports_wayland_global_shortcuts', lambda: False)
    monkeypatch.setattr(SettingsWidget, '_refresh_assist_devices', lambda self: None)
    yield
    loc.init_localization('en')


@pytest.fixture
def make(qtbot):
    def _make(config=None, **kw):
        w = SettingsWidget(copy.deepcopy(CONFIG if config is None else config), **kw)
        qtbot.addWidget(w)
        return w
    return _make


def test_load_config_populates_controls(make):
    w = make()
    assert w.url_input.text() == 'http://ha.local:8123' and w.token_input.text() == 'secret-token'
    assert w.theme_combo.currentIndex() == 1 and w.tray_position_combo.currentIndex() == 1
    assert w.temperature_unit_combo.currentIndex() == 1 and w.button_style_combo.currentIndex() == 1
    assert w.border_effect_combo.currentText() == 'Aurora Borealis'
    assert w.show_dimming_check.isChecked() and w.refresh_indicator_check.isChecked() and w.pin_check.isChecked()
    assert w.pages_combo.currentIndex() == 1
    assert not w.send_logged_in_check.isChecked() and w.send_cpu_check.isChecked()
    assert w.shortcut_display.text() == '<ctrl>+<alt>+p'
    assert w.assist_enabled_check.isChecked() and not w.assist_show_footer_check.isChecked()


def test_empty_config_uses_defaults(make):
    w = make({})
    assert w.url_input.text() == '' and w.theme_combo.currentIndex() == 0
    assert w.border_effect_combo.currentText() == 'Rainbow'
    assert w.send_logged_in_check.isChecked() and not w.pin_check.isChecked()


def test_unknown_values_fall_back(make):
    w = make({'appearance': {'theme': 'neon', 'border_effect': 'Nope', 'button_style': 'weird', 'pages': 99, 'tray_position': 'left'}})
    assert w.theme_combo.currentIndex() == 0 and w.tray_position_combo.currentIndex() == 0
    assert w.button_style_combo.currentIndex() == 0
    assert w.pages_combo.currentIndex() == w.pages_combo.count() - 1


def test_save_round_trips_values_and_emits(make, qtbot):
    w = make()
    with qtbot.waitSignal(w.settings_saved) as sig:
        w.save_settings()
    saved = sig.args[0]
    assert saved is w.config
    assert saved['home_assistant'] == {'url': 'http://ha.local:8123', 'token': 'secret-token'}
    ap = saved['appearance']
    assert (ap['theme'], ap['tray_position'], ap['temperature_unit'], ap['button_style']) == ('light', 'top', 'fahrenheit', 'Flat')
    assert ap['border_effect'] == 'Aurora Borealis' and ap['pages'] == 2 and ap['pin_window'] is True
    assert saved['mobile_app']['send_logged_in'] is False and saved['mobile_app']['send_cpu'] is True
    assert saved['assist']['enabled'] is True and saved['assist']['show_in_footer'] is False


def test_save_reflects_edits(make, qtbot):
    w = make()
    w.url_input.setText('  http://other:8123  ')
    w.token_input.setText(' tok ')
    w.theme_combo.setCurrentIndex(2)
    w.tray_position_combo.setCurrentIndex(0)
    w.temperature_unit_combo.setCurrentIndex(0)
    w.button_style_combo.setCurrentIndex(0)
    w.pages_combo.setCurrentIndex(0)
    w.send_ram_check.setChecked(False)
    w.assist_auto_listen_check.setChecked(False)
    with qtbot.waitSignal(w.settings_saved) as sig:
        w.save_settings()
    cfg = sig.args[0]
    assert cfg['home_assistant'] == {'url': 'http://other:8123', 'token': 'tok'}
    assert cfg['appearance']['theme'] == 'dark' and cfg['appearance']['pages'] == 1
    assert cfg['appearance']['tray_position'] == 'bottom' and cfg['appearance']['button_style'] == 'Gradient'
    assert cfg['mobile_app']['send_ram'] is False and cfg['assist']['auto_listen'] is False


def test_save_applies_theme_to_theme_manager(make):
    tm = ThemeManager()
    w = make(theme_manager=tm)
    w.theme_combo.setCurrentIndex(1)
    w.save_settings()
    assert tm.get_effective_theme() == 'light'


def test_language_change_shows_restart_note(make):
    w = make()
    idx = next(i for i, c in enumerate(w._language_codes) if c != 'en')
    w.language_combo.setCurrentIndex(idx)
    assert not w._language_restart_note.isHidden()


def test_save_with_new_language_schedules_restart_toast(make, qtbot, monkeypatch):
    from ui import notifications
    toasts = []
    monkeypatch.setattr(notifications, 'notify_language_restart', lambda win: toasts.append(win))
    w = make()
    other = next(i for i, c in enumerate(w._language_codes) if c != 'en')
    w.language_combo.blockSignals(True)
    w.language_combo.setCurrentIndex(other)
    w.language_combo.blockSignals(False)
    w.save_settings()
    qtbot.waitUntil(lambda: bool(toasts), timeout=3000)


@pytest.mark.skipif(not sys.platform.startswith(('win', 'linux')), reason="location setting exists only on Windows and Linux")
def test_location_flag_round_trip(make, monkeypatch):
    monkeypatch.setattr(SettingsWidget, '_check_geoclue2_and_setup', lambda self: None)
    w = make({'mobile_app': {'location_enabled': True}})
    assert w.location_check.isChecked()
    w.save_settings()
    assert w.config['mobile_app']['location_enabled'] is True


def test_connection_status_labels(make):
    w = make()
    w._set_conn_status('ok')
    assert 'Connected' in w._conn_status_label.text() and not w._conn_status_label.isHidden()
    w._set_conn_status('error', 'bad token')
    assert 'bad token' in w._conn_status_label.text()
    w._set_conn_status('error')
    assert 'failed' in w._conn_status_label.text()
    w._set_conn_status('checking')
    assert 'Checking' in w._conn_status_label.text()
    w._set_conn_status('idle')
    assert w._conn_status_label.isHidden()


def test_test_complete_updates_status_and_notifies_failure(make, monkeypatch):
    from ui import notifications
    seen = []
    monkeypatch.setattr(notifications, 'notify_connection_test_result', lambda d, ok, msg: seen.append((ok, msg)))

    class Dash:
        pass
    w = make(dashboard=Dash())
    w.on_test_complete(True, 'fine')
    assert seen == []
    w.on_test_complete(False, 'unauthorized')
    assert seen == [(False, 'unauthorized')] and 'unauthorized' in w._conn_status_label.text()


def test_credential_edit_debounces_and_clearing_hides_status(make):
    w = make()
    w._debounce_timer.stop()
    w.url_input.setText('http://x')
    assert w._debounce_timer.isActive()
    w.token_input.setText('')
    assert not w._debounce_timer.isActive() and w._conn_status_label.isHidden()


@pytest.mark.parametrize("raw,expected", [
    ('', ''), ('<ctrl>+<alt>+p', 'Ctrl+Alt+p'), ('<cmd>+<shift>+a', 'Cmd+Shift+a'),
    ('<super>+<f5>', 'Super+f5'), ('<meta>+x', 'Meta+x'),
])
def test_format_shortcut(raw, expected):
    assert SettingsWidget._format_shortcut(raw) == expected


def test_switching_panels_shows_one_and_refreshes_shortcuts(make, qtbot):
    w = make()
    w.show()
    n = len(w._panels)
    assert n >= 3
    with qtbot.waitSignal(w.content_height_changed, timeout=2000):
        w._switch_panel(2)
    assert [p.isVisibleTo(w) for p in w._panels].count(True) == 1
    assert w._active_panel_idx == 2


def test_shortcut_list_contains_only_enabled_assigned_buttons(make):
    w = make()
    w._refresh_button_shortcuts()
    rows = [w._btn_shortcuts_layout.itemAt(i).widget() for i in range(w._btn_shortcuts_layout.count())]
    assert len(rows) == 1 and isinstance(rows[0], _ShortcutRow)
    assert rows[0].btn_cfg['entity_id'] == 'light.a'


def test_shortcut_list_hint_when_none_assigned(make):
    w = make({'buttons': []})
    w._refresh_button_shortcuts()
    assert w._btn_shortcuts_layout.count() == 1


def test_row_buttons_forward_to_open_editor_and_delete_request(make, qtbot):
    w = make()
    w._refresh_button_shortcuts()
    row = w._btn_shortcuts_layout.itemAt(0).widget()
    with qtbot.waitSignal(w.open_button_editor_requested) as s1:
        row.edit_clicked.emit(row.btn_cfg)
    with qtbot.waitSignal(w.request_delete_shortcut) as s2:
        row.delete_clicked.emit(row.btn_cfg)
    assert s1.args[0] is row.btn_cfg and s2.args[0] is row.btn_cfg


def test_apply_shortcut_delete_clears_matching_button_only(make, qtbot):
    w = make()
    w._refresh_button_shortcuts()
    target = w.config['buttons'][0]
    with qtbot.waitSignal(w.shortcut_deleted):
        w.apply_shortcut_delete(dict(target))
    assert target['custom_shortcut'] == {'enabled': False, 'value': ''}
    assert w.config['buttons'][1]['custom_shortcut']['value'] == 'x'
    qtbot.waitUntil(lambda: not w._delete_anims, timeout=3000)


def test_apply_shortcut_delete_unknown_button_just_refreshes(make, qtbot):
    w = make()
    with qtbot.waitSignal(w.shortcut_deleted):
        w.apply_shortcut_delete({'row': 9, 'col': 9})
    assert w.config['buttons'][0]['custom_shortcut']['enabled'] is True


def test_recording_flow_updates_config_and_input_manager(make):
    im = FakeInput()
    w = make(input_manager=im)
    w.record_btn.setEnabled(True)
    w.record_btn.click()
    assert im.calls == ['start'] and w.record_btn.isChecked()
    im.recorded.emit({'value': '<ctrl>+j', 'enabled': True})
    assert w.config['shortcut']['value'] == '<ctrl>+j'
    assert ('update', {'value': '<ctrl>+j', 'enabled': True}) in im.calls
    assert not w.record_btn.isChecked()


def test_recorded_shortcut_ignored_when_not_recording(make):
    im = FakeInput()
    w = make(input_manager=im)
    w.record_btn.setChecked(False)
    before = copy.deepcopy(w.config['shortcut'])
    w.on_shortcut_recorded({'value': 'z'})
    assert w.config['shortcut'] == before and im.calls == []


def test_recording_without_input_manager_unchecks(make):
    w = make()
    w.toggle_recording(True)
    assert not w.record_btn.isChecked()
    w.toggle_assist_recording(True)
    assert not w.assist_record_btn.isChecked()


def test_assist_recording_flow(make):
    im = FakeInput()
    w = make(assist_input_manager=im)
    w.assist_record_btn.setEnabled(True)
    w.assist_record_btn.click()
    assert im.calls == ['start']
    im.recorded.emit({'value': '<alt>+a'})
    assert w.config['assist_shortcut'] == {'value': '<alt>+a'}


def test_kde_wayland_delegates_shortcuts(make, monkeypatch):
    monkeypatch.setattr(sw_mod, 'is_kde_wayland_session', lambda: True)
    monkeypatch.setattr(sw_mod, 'supports_wayland_global_shortcuts', lambda: True)
    monkeypatch.setattr(sw_mod.sys, 'platform', 'linux')
    w = make(input_manager=FakeInput())
    assert w._should_delegate_shortcuts_to_kde() is True
    w.record_btn.setChecked(True)
    w.toggle_recording(True)
    assert not w.record_btn.isChecked()


def test_content_height_positive_and_max_not_smaller(make):
    w = make()
    assert w.get_content_height() > 0
    assert w.get_max_content_height() >= w.get_content_height() - 1


def test_widget_renders(make):
    w = make()
    w.resize(380, 600)
    assert not w.grab().isNull()


def test_cleanup_threads_stops_timers(make):
    w = make()
    w._debounce_timer.start()
    w._poll_timer.start()
    w._cleanup_threads()
    assert not w._debounce_timer.isActive() and not w._poll_timer.isActive()


def test_version_label_toggle(make):
    w = make()
    w._set_version_label_collapsed()
    w._set_version_label_expanded()
