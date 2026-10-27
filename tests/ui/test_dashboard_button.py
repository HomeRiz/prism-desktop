import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QPixmap

from ui.icons import Icons
from ui.theme_manager import ThemeManager
from ui.widgets import dashboard_button as db
from ui.widgets.dashboard_button import (
    DashboardButton, _parse_sensor_value, _compute_fraction, MIME_TYPE,
)


@pytest.fixture
def make(make_button):
    return make_button


def cfg(btype='switch', **extra):
    return {'type': btype, 'entity_id': f'{btype}.x', 'label': 'Thing', **extra}


@pytest.mark.parametrize("raw,precision,expected", [
    ("21.456 C", 1, (21.456, " C", "21.5 C")),
    ("21.456", 0, (21.456, "", "21")),
    ("-3", 2, (-3.0, "", "-3.00")),
    ("1e3 W", 0, (1000.0, " W", "1000 W")),
    (".5%", 1, (0.5, "%", "0.5%")),
    ("12:34", 1, (None, "", "12:34")),
    ("2024-05-01", 1, (None, "", "2024-05-01")),
    ("1.2.3", 1, (None, "", "1.2.3")),
    ("unavailable", 1, (None, "", "unavailable")),
    ("", 1, (None, "", "")),
    (None, 1, (None, "", "--")),
    (42, 1, (42.0, "", "42.0")),
])
def test_parse_sensor_value(raw, precision, expected):
    assert _parse_sensor_value(raw, precision) == expected


@pytest.mark.parametrize("num,vmin,vmax,expected", [
    (50, 0, 100, 0.5), (-5, 0, 100, 0.0), (500, 0, 100, 1.0), (5, 10, 10, None),
    (5, 10, 0, None), (None, 0, 100, None), (5, "a", 100, None), (5, 0, None, None),
    (5, "0", "10", 0.5),
])
def test_compute_fraction(num, vmin, vmax, expected):
    assert _compute_fraction(num, vmin, vmax) == expected


def test_empty_button_shows_add(make):
    b = make()
    assert b.config == {}
    assert b.value_label.text() == Icons.PLUS
    assert b.name_label.text()


def test_forbidden_button_is_inert(make, qtbot):
    b = make({'type': 'forbidden'})
    got = []
    b.clicked.connect(got.append)
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
    assert got == []
    assert not b.name_label.isVisibleTo(b)
    b.show_context_menu(QPoint(1, 1))


@pytest.mark.parametrize("sx,sy,w,h", [(1, 1, 90, 80), (2, 1, 188, 80), (1, 2, 90, 168), (3, 2, 286, 168)])
def test_size_follows_spans(make, sx, sy, w, h):
    b = make({**cfg(), 'span_x': sx, 'span_y': sy})
    assert (b.width(), b.height()) == (w, h)


def test_set_spans_resizes_and_updates_content(make):
    b = make(cfg('widget'))
    b.set_spans(2, 2)
    assert (b.span_x, b.span_y) == (2, 2)
    assert (b.width(), b.height()) == (188, 168)


def test_set_spans_animated_starts_morph_and_restores_labels(make, qtbot):
    b = make(cfg('widget'))
    b.set_spans(2, 1, animate=True)
    assert b._relabel_after_morph is True
    b.morph_x_anim.stop()
    b.morph_y_anim.stop()
    b._on_morph_finished()
    assert b._relabel_after_morph is False
    assert b._morph_eff._sx == 1.0


def test_labels_render_plain_text_not_html(make):
    b = make(cfg('widget', label='<b>x</b>'))
    b.set_value("<i>1</i>")
    assert b.name_label.textFormat() == Qt.TextFormat.PlainText
    assert b.value_label.textFormat() == Qt.TextFormat.PlainText
    assert b.name_label.text() == '<b>x</b>'


def test_set_state_changes_icon_for_switch(make):
    b = make(cfg('switch'))
    off = b.value_label.text()
    b.set_state('on')
    assert b.value_label.text() != off
    assert b.value_label.text() == Icons.LIGHTBULB


def test_custom_icon_overrides_default(make, monkeypatch):
    monkeypatch.setattr(db, 'get_icon', lambda name: "ICON" if name else None)
    b = make(cfg('switch', icon='mdi:star'))
    assert b.value_label.text() == "ICON"


def test_ha_icon_used_when_no_custom_icon(make, monkeypatch):
    monkeypatch.setattr(db, 'get_icon', lambda name: "HA:" + name)
    b = make(cfg('switch'))
    b.set_ha_icon('mdi:foo')
    assert b.value_label.text() == "HA:mdi:foo"


def test_ha_icon_ignored_when_custom_icon_set(make, monkeypatch):
    monkeypatch.setattr(db, 'get_icon', lambda name: "I:" + name)
    b = make(cfg('switch', icon='mdi:mine'))
    b.set_ha_icon('mdi:ha')
    assert b.value_label.text() == "I:mdi:mine"


def press_release(qtbot, b, pos=QPoint(10, 10)):
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=pos)
    qtbot.mouseRelease(b, Qt.MouseButton.LeftButton, pos=pos)


def test_click_switch_emits_config(make, qtbot):
    b = make(cfg('switch'))
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b)
    assert got == [b.config]


def test_click_empty_button_emits_empty_config(make, qtbot):
    b = make()
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b)
    assert got == [{}]


@pytest.mark.parametrize("btype,signal", [
    ('climate', 'climate_requested'), ('weather', 'weather_requested'),
    ('lawn_mower', 'mower_requested'), ('vacuum', 'vacuum_requested'),
    ('alarm_control_panel', 'alarm_requested'),
])
def test_click_opens_overlay_for_type(make, qtbot, btype, signal):
    b = make(cfg(btype))
    got = []
    getattr(b, signal).connect(lambda *a: got.append(a))
    clicked = []
    b.clicked.connect(clicked.append)
    press_release(qtbot, b)
    assert len(got) == 1 and got[0][0] == b.slot
    assert clicked == []


def test_click_camera_and_printer_pass_config(make, qtbot):
    for btype, signal in (('camera', 'camera_requested'), ('3d_printer', 'printer_requested')):
        b = make(cfg(btype))
        got = []
        getattr(b, signal).connect(lambda *a: got.append(a))
        press_release(qtbot, b)
        assert got[0][2] == b.config


def test_click_sun_emits_nothing(make, qtbot):
    b = make(cfg('sun'))
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b)
    assert got == []


def test_script_click_starts_pulse(make, qtbot):
    b = make(cfg('script'))
    press_release(qtbot, b)
    assert b.pulse_anim.state() == b.pulse_anim.State.Running


@pytest.mark.parametrize("span,pos,action", [
    ((1, 1), QPoint(45, 40), 'media_play_pause'),
    ((2, 1), QPoint(5, 40), 'media_previous_track'),
    ((2, 1), QPoint(180, 40), 'media_next_track'),
    ((2, 1), QPoint(94, 40), 'media_play_pause'),
    ((1, 2), QPoint(45, 10), 'media_play_pause'),
    ((1, 2), QPoint(5, 150), 'media_previous_track'),
    ((1, 2), QPoint(85, 150), 'media_next_track'),
    ((2, 2), QPoint(5, 84), 'media_previous_track'),
    ((2, 2), QPoint(180, 84), 'media_next_track'),
    ((2, 2), QPoint(94, 5), 'media_play_pause'),
])
def test_media_player_click_zones(make, qtbot, span, pos, action):
    b = make(cfg('media_player', span_x=span[0], span_y=span[1]))
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b, pos)
    assert got[0]['action'] == action


def test_lock_lock_action_is_instant(make, qtbot):
    b = make(cfg('lock'))
    b.set_state('unlocked')
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b)
    assert got[0]['action'] == 'lock'


def test_lock_unlock_requires_hold_and_short_tap_cancels(make, qtbot):
    b = make(cfg('lock'))
    b.set_state('locked')
    got = []
    b.clicked.connect(got.append)
    press_release(qtbot, b)
    assert got == []
    assert b._lock_holding is False


def test_lock_unlock_after_hold_completes(make, qtbot):
    b = make(cfg('lock'))
    b.set_state('locked')
    got = []
    b.clicked.connect(got.append)
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    assert got[0]['action'] == 'unlock'


def test_lock_configured_action_wins(make):
    b = make(cfg('lock', action='lock'))
    b.set_state('locked')
    assert b._lock_resolve_action() == 'lock'
    assert make(cfg('switch'))._lock_resolve_action() is None
    assert make()._lock_resolve_action() is None


def test_long_press_light_requests_dimmer(make, qtbot):
    b = make({'type': 'switch', 'entity_id': 'light.k'})
    got = []
    b.dimmer_requested.connect(lambda *a: got.append(a))
    clicked = []
    b.clicked.connect(clicked.append)
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    qtbot.mouseRelease(b, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert clicked == []


def test_long_press_plain_switch_does_nothing(make):
    b = make(cfg('switch'))
    got = []
    b.dimmer_requested.connect(lambda *a: got.append(a))
    b._on_long_press()
    assert got == []


@pytest.mark.parametrize("btype,signal", [
    ('curtain', 'dimmer_requested'), ('media_player', 'volume_requested'),
    ('lawn_mower', 'mower_requested'), ('vacuum', 'vacuum_requested'),
])
def test_long_press_by_type(make, btype, signal):
    b = make(cfg(btype))
    got = []
    getattr(b, signal).connect(lambda *a: got.append(a))
    b._on_long_press()
    assert len(got) == 1
    assert b._ignore_release is True


def make_number(make, state='5', **attrs):
    b = make({'type': 'input_number', 'entity_id': 'input_number.x', 'span_x': 2})
    b.apply_ha_state({'state': state, 'attributes': {'min': 0, 'max': 10, 'step': 1, **attrs}})
    return b


def test_input_number_step_clamps_to_range(make):
    b = make_number(make, state='10')
    got = []
    b.clicked.connect(got.append)
    b._step_input_number(1)
    assert got == []
    b._step_input_number(-1)
    assert got[0]['value'] == 9.0 and got[0]['action'] == 'set_input_number'
    assert b._value['state'] == '9.0'


def test_input_number_arrow_click_zones(make, qtbot):
    b = make_number(make)
    got = []
    b.clicked.connect(got.append)
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=QPoint(5, 40))
    qtbot.mouseRelease(b, Qt.MouseButton.LeftButton, pos=QPoint(5, 40))
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=QPoint(b.width() - 5, 40))
    qtbot.mouseRelease(b, Qt.MouseButton.LeftButton, pos=QPoint(b.width() - 5, 40))
    assert [g['value'] for g in got] == [4.0, 5.0]


def test_input_number_non_numeric_step_is_ignored(make):
    b = make({'type': 'input_number', 'entity_id': 'input_number.x'})
    b.apply_ha_state({'state': 'unknown', 'attributes': {}})
    got = []
    b.clicked.connect(got.append)
    b._step_input_number(1)
    assert got == []


def test_wheel_on_media_player_emits_volume_scroll(make):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    b = make(cfg('media_player'))
    b.set_media_state({'state': 'playing', 'attributes': {'volume_level': 0.5}})
    got = []
    b.volume_scroll.connect(lambda e, v: got.append((e, v)))
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    b.wheelEvent(ev)
    assert got == [('media_player.x', pytest.approx(0.55))]


def test_context_menu_actions_for_configured_button(make, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    seen = {}

    def fake_exec(self, *a):
        seen['texts'] = [a.text() for a in self.actions()]
        seen['actions'] = self.actions()
    monkeypatch.setattr(QMenu, 'exec', fake_exec)
    b = make(cfg())
    edits = []
    b.edit_requested.connect(edits.append)
    b.show_context_menu(QPoint(1, 1))
    assert len(seen['texts']) == 4
    seen['actions'][0].trigger()
    assert edits == [b.slot]


def test_context_menu_move_submenu_lists_other_pages(make, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    seen = {}
    monkeypatch.setattr(QMenu, 'exec', lambda self, *a: seen.update(menu=self))
    b = make(cfg())
    b._page_count = 3
    b._current_page = 1
    moves = []
    b.move_to_page_requested.connect(lambda s, p: moves.append((s, p)))
    b.show_context_menu(QPoint(1, 1))
    sub = [a for a in seen['menu'].actions() if a.menu()][0].menu()
    assert len(sub.actions()) == 2
    sub.actions()[1].trigger()
    assert moves == [(b.slot, 2)]


def test_simulate_click_paths(make):
    b = make(cfg('switch'))
    got = []
    b.clicked.connect(got.append)
    b.simulate_click()
    assert got == [b.config]
    make().simulate_click()
    c = make(cfg('climate'))
    cl = []
    c.climate_requested.connect(lambda *a: cl.append(a))
    c.simulate_click()
    assert len(cl) == 1


def test_resize_handle_click_in_corner_emits_resize(make, qtbot):
    b = make(cfg())
    b._resize_handle_opacity = 1.0
    got = []
    b.resize_requested.connect(lambda *a: got.append(a))
    fin = []
    b.resize_finished.connect(lambda: fin.append(1))
    corner = QPoint(b.width() - 5, b.height() - 5)
    qtbot.mousePress(b, Qt.MouseButton.LeftButton, pos=corner)
    assert b._is_resizing is True
    from PyQt6.QtTest import QTest
    QTest.mouseMove(b, QPoint(corner.x() + 95, corner.y()))
    qtbot.mouseRelease(b, Qt.MouseButton.LeftButton, pos=corner)
    assert fin == [1]


def test_mime_type_constant():
    assert MIME_TYPE == "application/x-hatray-slot"

