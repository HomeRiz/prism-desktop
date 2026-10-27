import pytest
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QColor, QPixmap

from ui.widgets import overlays as ov
from ui.widgets.overlays import (
    BaseOverlay, DimmerOverlay, ClimateOverlay, PrinterOverlay, WeatherOverlay,
    CameraOverlay, MowerOverlay, VacuumOverlay, AlarmOverlay,
)

START = QRect(10, 10, 90, 80)
TARGET = QRect(10, 10, 320, 220)
WIDE = QRect(10, 10, 520, 200)


@pytest.fixture(autouse=True)
def fast_animations(monkeypatch):
    monkeypatch.setattr(ov, 'MORPH_OPEN_DURATION', 20)
    monkeypatch.setattr(ov, 'MORPH_CLOSE_DURATION', 20)
    monkeypatch.setattr(ov, 'CONTENT_FADE_DURATION', 20)
    monkeypatch.setattr(ov, 'BORDER_SPIN_DURATION', 40)


def add(qtbot, widget):
    qtbot.addWidget(widget)
    return widget


def settle(qtbot, o):
    qtbot.waitUntil(lambda: o.get_content_opacity() >= 1.0, timeout=5000)
    assert not o.grab().isNull()


def click(qtbot, o, rect):
    qtbot.mouseClick(o, Qt.MouseButton.LeftButton, pos=rect.center())


@pytest.mark.parametrize("color,light", [("#2d2d2d", False), ("#f0f0f0", True), ("#8c8c8c", False), ("#909090", True)])
def test_light_background_threshold_and_fg_color(qtbot, color, light):
    o = add(qtbot, BaseOverlay())
    o._base_color = QColor(color)
    assert o._is_light_bg() is light
    assert o._fg_color(100).red() == (0 if light else 255)
    assert o._fg_color(100).alpha() == 100


def test_morph_progress_interpolates_geometry_and_emits(qtbot):
    o = add(qtbot, BaseOverlay())
    o._start_geom = QRect(0, 0, 100, 100)
    o._target_geom = QRect(100, 200, 300, 400)
    seen = []
    o.morph_changed.connect(seen.append)
    o.set_morph_progress(0.5)
    assert o.geometry() == QRect(50, 100, 200, 250)
    assert seen == [0.5]


def test_open_then_close_cycle_emits_finished_and_hides(qtbot):
    o = add(qtbot, DimmerOverlay())
    o.start_morph(START, TARGET, 40, "Lamp")
    assert o.isVisible()
    settle(qtbot, o)
    assert o.geometry() == TARGET
    with qtbot.waitSignal(o.finished, timeout=5000):
        o.close_morph()
    assert o.isHidden()
    assert o._is_closing is True


def test_close_fade_applies_only_while_closing_near_start(qtbot):
    class P:
        opacity = None

        def setOpacity(self, v):
            self.opacity = v
    o = add(qtbot, BaseOverlay())
    p = P()
    o._draw_close_fade(p)
    assert p.opacity is None
    o._is_closing = True
    o._morph_progress = ov.CLOSE_FADE_START / 4
    o._draw_close_fade(p)
    assert p.opacity == pytest.approx(0.5)


@pytest.mark.parametrize("effect", ["Rainbow", "Aurora Borealis", "Prism Shard", "Liquid Mercury", "None"])
def test_border_effects_render_while_opening(qtbot, effect):
    o = add(qtbot, DimmerOverlay())
    o.set_border_effect(effect)
    o.start_morph(START, TARGET, 10, "x")
    o.set_border_progress(0.9)
    assert not o.grab().isNull()
    assert o.get_border_progress() == 0.9


def test_dimmer_value_follows_horizontal_position(qtbot):
    o = add(qtbot, DimmerOverlay())
    o.start_morph(START, TARGET, 0, "Lamp", color=QColor("red"), base_color=QColor("#222222"))
    settle(qtbot, o)
    got = []
    o.value_changed.connect(got.append)
    qtbot.mousePress(o, Qt.MouseButton.LeftButton, pos=QPoint(160, 50))
    assert got == [50]
    qtbot.mouseMove(o, QPoint(320, 50))
    assert got[-1] == 99 or got[-1] == 100


def test_dimmer_release_closes(qtbot):
    o = add(qtbot, DimmerOverlay())
    o.start_morph(START, TARGET, 50, "Lamp")
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        qtbot.mouseRelease(o, Qt.MouseButton.LeftButton)


def test_climate_adjust_temp_clamps_and_emits(qtbot):
    o = add(qtbot, ClimateOverlay())
    o.configure_temperature_range(10, 12, 0.5, display_unit='F')
    o.start_morph(START, TARGET, 11.5, "Heat")
    got = []
    o.value_changed.connect(got.append)
    o.adjust_temp(0.5)
    o.adjust_temp(0.5)
    o.adjust_temp(-5)
    assert got == [12.0, 10]
    assert o._display_temp_unit == 'F'


def test_climate_non_positive_step_falls_back(qtbot):
    o = add(qtbot, ClimateOverlay())
    o.configure_temperature_range(0, 40, 0, None)
    o.configure_temperature_range(0, 40, -1)
    assert o._step == 0.5


def test_climate_update_state_reads_modes(qtbot):
    o = add(qtbot, ClimateOverlay())
    o.update_state({})
    o.update_state({'state': 'cool', 'attributes': {'fan_mode': 'high', 'hvac_modes': ['off', 'cool'], 'fan_modes': ['high']}})
    assert (o._current_hvac_mode, o._current_fan_mode) == ('cool', 'high')
    assert o._hvac_modes == ['off', 'cool'] and o._fan_modes == ['high']


@pytest.mark.parametrize("geo", [TARGET, WIDE])
def test_climate_renders_and_buttons_work(qtbot, geo):
    o = add(qtbot, ClimateOverlay())
    o.start_morph(START, geo, 20.0, "Heat", current_state={'state': 'heat', 'attributes': {}})
    settle(qtbot, o)
    values, modes, fans = [], [], []
    o.value_changed.connect(values.append)
    o.mode_changed.connect(modes.append)
    o.fan_changed.connect(fans.append)
    click(qtbot, o, o._btn_plus_click)
    click(qtbot, o, o._btn_minus_click)
    assert values == [20.5, 20.0]
    if o._mode_btns:
        rect, mode = o._mode_btns[-1]
        click(qtbot, o, rect)
        assert modes == [mode] and o._current_hvac_mode == mode
    if o._fan_btns:
        rect, mode = o._fan_btns[-1]
        click(qtbot, o, rect)
        assert fans == [mode]


def test_climate_close_button_closes(qtbot):
    o = add(qtbot, ClimateOverlay())
    o.start_morph(START, TARGET, 20.0, "Heat")
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_close)


def test_printer_state_parsing_tolerates_garbage(qtbot):
    o = add(qtbot, PrinterOverlay())
    o.update_state({'state': 'printing', 'attributes': {'hotend_actual': 'abc', 'bed_actual': None,
                                                          'progress': '55.5', 'time_remaining': '1h', 'temperature_unit': 'C'}})
    assert (o._hotend_actual, o._bed_actual, o._progress) == (0.0, 0.0, 55.5)
    assert o._time_remaining == '1h' and o._printer_source_unit == 'C'


@pytest.mark.parametrize("state,color", [("printing", "#4caf50"), ("heating", "#4caf50"), ("paused", "#ff9800"),
                                           ("error", "#f44336"), ("offline", "#f44336"), ("idle", "#2196f3")])
def test_printer_state_colors(qtbot, state, color):
    o = add(qtbot, PrinterOverlay())
    o._state = state.upper()
    assert o._state_color().name() == color


def test_printer_pause_resume_and_stop_confirmation(qtbot):
    o = add(qtbot, PrinterOverlay())
    o.start_morph(START, TARGET, "Printer", current_state={'state': 'printing', 'attributes': {'progress': 10}})
    settle(qtbot, o)
    got = []
    o.action_requested.connect(got.append)
    click(qtbot, o, o._btn_pause)
    o.update_state({'state': 'paused', 'attributes': {}})
    o.grab()
    click(qtbot, o, o._btn_pause)
    assert got == ['pause', 'resume']
    click(qtbot, o, o._btn_stop)
    assert o._confirm_stop_mode is True and 'stop' not in got
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_stop)
    assert got[-1] == 'stop'


def test_printer_stop_confirmation_times_out(qtbot):
    o = add(qtbot, PrinterOverlay())
    o.start_morph(START, TARGET, "Printer", current_state={'state': 'printing', 'attributes': {}})
    settle(qtbot, o)
    click(qtbot, o, o._btn_stop)
    assert o._confirm_timer.isActive()
    o._confirm_timer.timeout.emit()
    assert o._confirm_stop_mode is False


def test_weather_overlay_renders_with_and_without_forecast(qtbot):
    o = add(qtbot, WeatherOverlay())
    o.set_temperature_unit_preference("celsius")
    o.update_state({})
    state = {'state': 'sunny', 'attributes': {'temperature': 20, 'temperature_unit': '°C'}}
    forecasts = [{'datetime': '2030-01-0%dT12:00:00+00:00' % d, 'condition': 'rainy', 'temperature': 15, 'templow': 5} for d in range(1, 6)]
    o.start_morph(START, WIDE, state, forecasts, "Home")
    settle(qtbot, o)
    o.close_morph()
    o2 = add(qtbot, WeatherOverlay())
    o2.start_morph(START, TARGET, state, None, "Home")
    settle(qtbot, o2)


def test_weather_close_button(qtbot):
    o = add(qtbot, WeatherOverlay())
    o.start_morph(START, TARGET, {'state': 'cloudy', 'attributes': {}}, [], "Home")
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_close)


def test_camera_overlay_paints_pixmap_and_clears_after_close(qtbot):
    o = add(qtbot, CameraOverlay())
    pm = QPixmap(640, 360)
    pm.fill(QColor("green"))
    o.start_morph(START, TARGET, "Cam")
    o.set_camera_pixmap(pm)
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        o.close_morph()
    assert o._camera_pixmap is None


def test_camera_overlay_close_button(qtbot):
    o = add(qtbot, CameraOverlay())
    o.start_morph(START, TARGET, "Cam")
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_close)


@pytest.mark.parametrize("cls,active,start", [(MowerOverlay, 'mowing', 'start_mowing'), (VacuumOverlay, 'cleaning', 'start')])
def test_robot_overlay_actions(qtbot, cls, active, start):
    o = add(qtbot, cls())
    o.start_morph(START, TARGET, "Bot", current_state={'state': 'docked', 'attributes': {'battery_level': '80'}})
    settle(qtbot, o)
    got = []
    o.action_requested.connect(got.append)
    click(qtbot, o, o._btn_start_pause)
    click(qtbot, o, o._btn_dock)
    o.update_state({'state': active, 'attributes': {}})
    o.grab()
    click(qtbot, o, o._btn_start_pause)
    assert got == [start, cls.DOCK_ACTION, 'pause']
    assert o._battery_level == -1.0


def test_robot_overlay_invalid_battery_and_hover(qtbot):
    o = add(qtbot, MowerOverlay())
    o.update_state({'state': 'mowing', 'attributes': {'battery_level': 'x'}})
    assert o._battery_level == -1.0
    o.start_morph(START, TARGET, "Bot")
    settle(qtbot, o)
    qtbot.mouseMove(o, o._btn_dock.center())
    assert o._hover_dock is True
    o.leaveEvent(None)
    assert o._hover_dock is False


def test_robot_overlay_close_button(qtbot):
    o = add(qtbot, VacuumOverlay())
    o.start_morph(START, TARGET, "Bot")
    settle(qtbot, o)
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_close)


def make_alarm(qtbot, state='disarmed', code_arm=False, code_disarm=False, geo=TARGET):
    o = add(qtbot, AlarmOverlay())
    o.configure_modes(['arm_home', 'arm_away', 'bogus'])
    o.configure_code(code_arm, code_disarm)
    o.start_morph(START, geo, "Alarm", current_state={'state': state})
    settle(qtbot, o)
    return o


def test_alarm_arm_without_code_emits_immediately(qtbot):
    o = make_alarm(qtbot)
    got = []
    o.action_requested.connect(lambda a, c: got.append((a, c)))
    click(qtbot, o, o._mode_btns[0][0])
    assert got == [(o._mode_btns[0][1], '')]


def test_alarm_disarm_without_code(qtbot):
    o = make_alarm(qtbot, state='armed_home')
    got = []
    o.action_requested.connect(lambda a, c: got.append((a, c)))
    click(qtbot, o, o._btn_disarm)
    assert got == [('disarm', '')]


def test_alarm_keypad_flow_collects_code_and_submits(qtbot):
    o = make_alarm(qtbot, state='armed_home', code_disarm=True)
    got, toggles = [], []
    o.action_requested.connect(lambda a, c: got.append((a, c)))
    o.keypad_toggled.connect(toggles.append)
    click(qtbot, o, o._btn_disarm)
    assert o._pending_action == 'disarm' and toggles == [True] and got == []
    o.resize_to(QRect(10, 10, 320, 420))
    settle(qtbot, o)
    digits = {v: r for r, k, v in o._keypad_btns if k == 'digit'}
    for d in "1234":
        click(qtbot, o, digits[d])
    back = [r for r, k, v in o._keypad_btns if k == 'back'][0]
    click(qtbot, o, back)
    assert o._entered_code == "123"
    click(qtbot, o, digits["9"])
    submit = [r for r, k, v in o._keypad_btns if k == 'submit'][0]
    click(qtbot, o, submit)
    assert got == [('disarm', '1239')]
    assert o._pending_action is None and toggles == [True, False]


def test_alarm_keypad_back_on_empty_cancels_and_submit_needs_code(qtbot):
    o = make_alarm(qtbot, code_arm=True)
    click(qtbot, o, o._mode_btns[0][0])
    o.resize_to(QRect(10, 10, 320, 420))
    settle(qtbot, o)
    o.resize_to(QRect(10, 10, 320, 420))
    settle(qtbot, o)
    got = []
    o.action_requested.connect(lambda a, c: got.append((a, c)))
    submit = [r for r, k, v in o._keypad_btns if k == 'submit'][0]
    click(qtbot, o, submit)
    assert got == [] and o._pending_action
    back = [r for r, k, v in o._keypad_btns if k == 'back'][0]
    click(qtbot, o, back)
    assert o._pending_action is None


def test_alarm_code_length_is_capped(qtbot):
    o = make_alarm(qtbot, code_arm=True)
    click(qtbot, o, o._mode_btns[0][0])
    o.resize_to(QRect(10, 10, 320, 420))
    settle(qtbot, o)
    o.resize_to(QRect(10, 10, 320, 420))
    settle(qtbot, o)
    digit = [r for r, k, v in o._keypad_btns if k == 'digit' and v == '5'][0]
    for _ in range(12):
        click(qtbot, o, digit)
    assert o._entered_code == '5' * 8


def test_alarm_state_change_drops_pending_entry(qtbot):
    o = make_alarm(qtbot, code_arm=True)
    o._request_action('arm_home')
    o._entered_code = '12'
    o.update_state({'state': 'armed_home'})
    assert o._pending_action is None and o._entered_code == ''
    o.update_state({})


def test_alarm_close_button(qtbot):
    o = make_alarm(qtbot)
    with qtbot.waitSignal(o.finished, timeout=5000):
        click(qtbot, o, o._btn_close)


@pytest.mark.parametrize("state", ["triggered", "arming", "unknown", "armed_away"])
def test_alarm_renders_each_state(qtbot, state):
    make_alarm(qtbot, state=state)
