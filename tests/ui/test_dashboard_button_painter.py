import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPixmap

from ui.icons import Icons
from ui.theme_manager import ThemeManager
from ui.widgets import dashboard_button as db


@pytest.fixture
def make(make_button):
    return make_button


def cfg(btype='switch', **extra):
    return {'type': btype, 'entity_id': f'{btype}.x', 'label': 'Thing', **extra}


@pytest.mark.parametrize("btype", [
    'switch', 'light', 'lock', 'script', 'automation', 'scene', 'fan', 'curtain', 'climate',
    'widget', 'weather', 'media_player', 'camera', '3d_printer', 'lawn_mower', 'vacuum',
    'alarm_control_panel', 'input_number', 'sun', 'pin_window', 'unknown_type',
])
def test_every_type_builds_and_renders(make, btype):
    b = make(cfg(btype))
    b.resize(b.size())
    assert not b.grab().isNull()


def test_widget_numeric_value_formatting(make):
    b = make(cfg('widget', precision=1))
    b.set_value("21.456C")
    assert b.value_label.text() == "21.5C"
    b.set_value("unavailable")
    assert b.value_label.text() == "unavailable"


def test_widget_without_value_shows_dashes(make):
    assert make(cfg('widget')).value_label.text() == "--"


def test_widget_fraction_from_sensor_range(make):
    b = make(cfg('widget', sensor_min=0, sensor_max=200, display_style='gauge'))
    b.set_value("50")
    assert b._sensor_fraction == 0.25


@pytest.mark.parametrize("style,span", [('bar', (1, 1)), ('gauge', (1, 1)), ('gauge', (1, 2)), ('gauge', (2, 1)), ('perimeter', (1, 1)), ('normal', (1, 1))])
def test_widget_display_styles_render(make, style, span):
    b = make(cfg('widget', display_style=style, span_x=span[0], span_y=span[1]))
    b.set_value("42")
    b.play_entry_animation()
    assert not b.grab().isNull()


def test_gauge_2x_reserves_left_margin(make):
    b = make(cfg('widget', display_style='gauge', span_x=2))
    assert b.layout().contentsMargins().left() > 8


def test_apply_ha_state_none_and_empty_are_noops(make):
    b = make(cfg('switch'))
    b.apply_ha_state(None)
    b.apply_ha_state({})
    assert b._state == 'off'


def test_apply_ha_state_switch(make):
    b = make(cfg('switch'))
    b.apply_ha_state({'state': 'on', 'attributes': {'brightness': 100}})
    assert b._state == 'on'
    assert b._brightness == 100


def test_apply_ha_state_widget_unit_only_for_numbers(make):
    b = make(cfg('widget'))
    b.apply_ha_state({'state': '12', 'attributes': {'unit_of_measurement': 'W'}})
    assert b._value == '12W'
    b.apply_ha_state({'state': 'unavailable', 'attributes': {'unit_of_measurement': 'W'}})
    assert b._value == 'unavailable'


def test_apply_ha_state_climate_sets_state_and_target(make):
    b = make(cfg('climate'))
    b.apply_ha_state({'state': 'heat', 'attributes': {'temperature': 21, 'temperature_unit': '°C'}})
    assert b._state == 'on'
    assert '21' in b.value_label.text()
    b.apply_ha_state({'state': 'off', 'attributes': {}})
    assert b._state == 'off'


@pytest.mark.parametrize("ha,expected", [('open', 'open'), ('closed', 'closed'), ('opening', 'closed')])
def test_apply_ha_state_curtain(make, ha, expected):
    b = make(cfg('curtain'))
    b.apply_ha_state({'state': ha, 'attributes': {}})
    assert b._state == expected


@pytest.mark.parametrize("btype,ha,expected", [
    ('lawn_mower', 'mowing', 'mowing'), ('vacuum', 'cleaning', 'cleaning'),
    ('alarm_control_panel', 'armed_home', 'armed_home'), ('automation', 'on', 'on'),
    ('3d_printer', 'printing', 'printing'),
])
def test_apply_ha_state_passthrough_types(make, btype, ha, expected):
    b = make(cfg(btype))
    b.apply_ha_state({'state': ha, 'attributes': {}})
    assert b._state == expected


def test_apply_ha_state_sun_updates_attributes(make):
    b = make(cfg('sun'))
    b.apply_ha_state({'state': 'above_horizon', 'attributes': {'elevation': '12.5', 'rising': True, 'next_rising': 'a', 'next_setting': 'b'}})
    assert (b.sun_state, b.sun_elevation, b.sun_rising) == ('above_horizon', 12.5, True)
    assert (b.sun_next_rising, b.sun_next_setting) == ('a', 'b')


def test_apply_ha_state_input_number_shows_formatted_value(make):
    b = make(cfg('input_number'))
    b.apply_ha_state({'state': '5', 'attributes': {'step': 0.5, 'unit_of_measurement': 'x'}})
    assert b.value_label.text() == "5.0x"


def test_input_number_non_numeric_state_shown_raw(make):
    b = make(cfg('input_number'))
    b.apply_ha_state({'state': 'unknown', 'attributes': {'unit_of_measurement': 'x'}})
    assert b.value_label.text() == "unknownx"


def test_media_state_sets_tooltip(make, monkeypatch):
    monkeypatch.setattr(db, 't', lambda key, **kw: kw.get('info', key))
    b = make(cfg('media_player'))
    b.set_media_state({'state': 'playing', 'attributes': {'media_title': 'T', 'media_artist': 'A'}})
    assert b.toolTip() == 'A \u2014 T'
    b.set_media_state({'state': 'idle', 'attributes': {'media_title': 'Only'}})
    assert b.toolTip() == 'Only'
    b.set_media_state({'state': 'idle', 'attributes': {}})
    assert b.toolTip() == ''


def test_weather_state_stored_and_rendered(make):
    b = make(cfg('weather'))
    b.set_weather_state({'state': 'sunny', 'attributes': {'temperature': 20}})
    assert b._value['state'] == 'sunny'
    assert not b.grab().isNull()


def test_weather_emoji_known_and_unknown(make):
    b = make(cfg('weather'))
    assert b._get_weather_emoji('sunny')
    assert b._get_weather_emoji('definitely-not-weather')


def test_reset_state_restores_defaults(make):
    b = make(cfg('switch'))
    b.apply_ha_state({'state': 'on', 'attributes': {'brightness': 10}})
    b.reset_state()
    assert (b._state, b._value, b._brightness) == ('off', None, 255)


def test_camera_image_cover_scaled_to_button(make):
    b = make(cfg('camera'))
    pm = QPixmap(400, 100)
    pm.fill(Qt.GlobalColor.green)
    b.set_camera_image(pm)
    assert b._cached_display_pixmap.size() == b.size()
    b.set_camera_image(QPixmap())
    assert b._last_camera_pixmap.isNull()


def test_flash_refresh_only_when_enabled(make):
    b = make(cfg())
    b.flash_refresh_indicator()
    assert b.refresh_flash_anim.state() != b.refresh_flash_anim.State.Running
    b.refresh_indicators_enabled = True
    b.flash_refresh_indicator()
    assert b.refresh_flash_anim.state() == b.refresh_flash_anim.State.Running


def test_style_cache_skips_unchanged_and_invalidates(make):
    b = make(cfg())
    fp = b._style_fp
    b.update_style()
    assert b._style_fp == fp
    b.invalidate_style_cache()
    assert b._style_fp is None
    b.update_style()
    assert b._style_fp is not None


def test_style_uses_theme_manager_colors(make, qapp):
    tm = ThemeManager()
    tm._effective_theme = 'light'
    b = make(cfg(), theme_manager=tm)
    assert b._style_fp[-1] == 'light'
    assert 'background' in b.styleSheet()


from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage, QPainter

from ui.widgets.dashboard_button_painter import DashboardButtonPainter as P
from ui.widgets.dashboard_button_styles import DashboardButtonStyleManager as SM


@pytest.fixture
def canvas(qapp):
    img = QImage(120, 90, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    yield img, painter
    if painter.isActive():
        painter.end()


def painted_pixels(img):
    count = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if QColor.fromRgba(img.pixel(x, y)).alpha() > 0:
                count += 1
    return count


RECT = QRectF(10, 10, 100, 70)


def test_bottom_bar_ignores_non_positive_values(canvas):
    img, p = canvas
    P.draw_bottom_bar(p, RECT, 0, 100, QColor("red"))
    P.draw_bottom_bar(p, RECT, 5, 0, QColor("red"))
    P.draw_bottom_bar(p, RECT, -5, 100, QColor("red"))
    p.end()
    assert painted_pixels(img) == 0


def test_bottom_bar_fills_fraction_of_width_and_clamps(canvas):
    img, p = canvas
    P.draw_bottom_bar(p, RECT, 50, 100, QColor("red"), bar_height=4)
    p.end()
    assert QColor.fromRgba(img.pixel(30, 77)).alpha() == 255
    assert QColor.fromRgba(img.pixel(100, 77)).alpha() == 0
    img2 = QImage(120, 90, QImage.Format.Format_ARGB32)
    img2.fill(Qt.GlobalColor.transparent)
    p2 = QPainter(img2)
    P.draw_bottom_bar(p2, RECT, 500, 100, QColor("red"))
    p2.end()
    assert QColor.fromRgba(img2.pixel(108, 77)).alpha() == 255
    assert QColor.fromRgba(img2.pixel(112, 77)).alpha() == 0


@pytest.mark.parametrize("fraction", [None, 0.0, 0.4, 1.0, 5.0, -1.0])
def test_bar_pill_draws_track_for_any_fraction(canvas, fraction):
    img, p = canvas
    P.draw_horizontal_bar_pill(p, QRectF(10, 30, 100, 16), fraction, QColor("green"), QColor(80, 80, 80))
    p.end()
    assert painted_pixels(img) > 0


def test_bar_pill_with_text(canvas):
    img, p = canvas
    P.draw_horizontal_bar_pill(p, QRectF(10, 30, 100, 16), 0.5, QColor("green"), QColor(80, 80, 80),
                               text="50%", font=p.font(), text_color=QColor("white"))
    p.end()
    assert painted_pixels(img) > 0


def test_bar_pill_fill_grows_with_fraction(qapp):
    def fill_px(frac):
        img = QImage(120, 40, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        P.draw_horizontal_bar_pill(p, QRectF(10, 10, 100, 16), frac, QColor(0, 255, 0), QColor(0, 0, 0))
        p.end()
        return sum(1 for x in range(120) if QColor.fromRgba(img.pixel(x, 18)).green() > 100)
    assert fill_px(0.8) > fill_px(0.2)


def test_perimeter_path_is_closed_and_starts_top_center():
    path = P._perimeter_path(QRectF(0, 0, 80, 60), 8)
    assert path.currentPosition().x() == pytest.approx(40)
    assert path.currentPosition().y() == pytest.approx(0)
    assert path.length() > 2 * (80 + 60) - 8 * 8


def test_perimeter_progress_longer_fraction_paints_more(qapp):
    def count(frac):
        img = QImage(120, 90, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        P.draw_perimeter_progress(p, QRectF(0, 0, 120, 90), frac, QColor(0, 255, 0), QColor(0, 0, 0, 0))
        p.end()
        return painted_pixels(img)
    assert count(None) == 0
    assert count(0.0) == 0
    assert count(0.75) > count(0.25) > 0
    assert count(5.0) == count(1.0)


def test_perimeter_progress_with_degenerate_rect_does_not_raise(canvas):
    img, p = canvas
    P.draw_perimeter_progress(p, QRectF(0, 0, 10, 10), 0.5, QColor("red"), QColor("blue"), offset=8)
    p.end()


@pytest.mark.parametrize("fraction,thickness", [(None, None), (0.0, None), (0.5, None), (1.0, 6), (2.0, 4)])
def test_gauge_arc_variants(canvas, fraction, thickness):
    img, p = canvas
    P.draw_gauge_arc(p, QRectF(20, 10, 70, 70), fraction, QColor("green"), QColor(60, 60, 60), thickness=thickness)
    p.end()
    assert painted_pixels(img) > 0


@pytest.mark.parametrize("name", ["draw_rainbow_border", "draw_aurora_border", "draw_prism_shard_border", "draw_liquid_mercury_border"])
@pytest.mark.parametrize("angle", [0, 123.5, 360, -45])
def test_named_borders_paint_outline(canvas, name, angle):
    img, p = canvas
    getattr(P, name)(p, RECT, angle)
    p.end()
    assert painted_pixels(img) > 0


def test_gradient_border_colors_change_with_angle(qapp):
    def render(angle):
        img = QImage(120, 90, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        P.draw_rainbow_border(p, RECT, angle)
        p.end()
        return img
    assert render(0) != render(90)


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("clamped", [False, True])
def test_edge_effects_and_bevel_render(canvas, light, clamped):
    img, p = canvas
    P.draw_image_edge_effects(p, RECT, is_top_clamped=clamped, is_light=light)
    P.draw_button_bevel_edge(p, RECT, intensity_modifier=0.25, is_top_clamped=clamped, corner_radius=4, is_light=light)
    p.end()
    assert painted_pixels(img) > 0


def test_style_manager_gradient_for_dark_and_near_white():
    dark = SM._get_gradient("#202020", 120)
    white = SM._get_gradient("#ffffff", 120)
    assert dark.startswith("background: qlineargradient") and "rgba(" in dark
    assert dark != white
    top_stop = white.split("stop: 0 ")[1].split(",")[0:3]
    assert "255" in top_stop[0]


def test_style_manager_preserves_alpha():
    assert ", 0.50)" in SM._get_gradient(QColor(10, 20, 30, 128).name(QColor.NameFormat.HexArgb))


@pytest.mark.parametrize("config,state", [
    ({}, 'off'), ({'type': 'forbidden'}, 'off'), ({'type': 'sun', 'entity_id': 's'}, 'on'),
    ({'type': 'lock', 'entity_id': 'l'}, 'jammed'), ({'type': 'lock', 'entity_id': 'l'}, 'locked'),
    ({'type': 'switch', 'entity_id': 'x', 'color': '#ff0000'}, 'on'),
    ({'type': 'switch', 'entity_id': 'x'}, 'off'), ({'type': 'script', 'entity_id': 'x'}, 'off'),
    ({'type': 'media_player', 'entity_id': 'x'}, 'playing'),
])
@pytest.mark.parametrize("style", ['Gradient', 'Flat'])
def test_style_manager_applies_stylesheet_for_all_states(make, config, state, style):
    b = make(config)
    b.button_style = style
    b._state = state
    SM.apply_style(b)
    assert b.styleSheet().strip()
    assert "DashboardButton" in b.styleSheet()


def test_jammed_lock_uses_alert_color_regardless_of_config(make):
    b = make({'type': 'lock', 'entity_id': 'l', 'color': '#00ff00'})
    b._state = 'jammed'
    b.button_style = 'Flat'
    SM.apply_style(b)
    assert '#EA4335' in b.styleSheet()
    assert '#00ff00' not in b.styleSheet()


def test_flat_style_has_no_gradient(make):
    b = make({'type': 'switch', 'entity_id': 'x'})
    b.button_style = 'Flat'
    b._state = 'on'
    SM.apply_style(b)
    assert 'qlineargradient' not in b.styleSheet()
    b.button_style = 'Gradient'
    SM.apply_style(b)
    assert 'qlineargradient' in b.styleSheet()


def test_forbidden_style_has_no_hover_rule(make):
    b = make({'type': 'forbidden'})
    SM.apply_style(b)
    assert ':hover' not in b.styleSheet()
