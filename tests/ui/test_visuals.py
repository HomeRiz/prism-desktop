import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QWidget

from ui.constants import PAGE_INDICATOR_WIDTH, FOOTER_HEIGHT
from ui.utils.glass_effect import draw_frosted_pill
from ui.visuals import dashboard_effects as fx
from ui.visuals.background_generator import BackgroundGenerator as BG
from ui.widgets.effect_combobox import EffectComboBox
from ui.widgets.footer_button import FooterButton
from ui.widgets.page_indicator_button import PageIndicatorButton
from ui.widgets.toggle_switch import ToggleSwitch
from ui.widgets.welcome_banner import WelcomeBanner, _DotsWidget


def new_image(w=160, h=100):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    return img


def alpha_count(img):
    return sum(1 for y in range(img.height()) for x in range(img.width()) if QColor.fromRgba(img.pixel(x, y)).alpha() > 0)


def solid(w, h, color):
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    return pm


def test_generate_layers_is_deterministic_for_seed(qapp):
    a = BG.generate_layers(100, 80, seed=7)
    b = BG.generate_layers(100, 80, seed=7)
    assert a["seed"] == b["seed"] == 7
    assert [x["color"].name() for x in a["anchors"]] == [x["color"].name() for x in b["anchors"]]
    assert a["base_color"] == b["base_color"]


def test_generate_layers_different_seeds_differ(qapp):
    a = BG.generate_layers(100, 80, seed=1)
    b = BG.generate_layers(100, 80, seed=2)
    assert [x["phase_x"] for x in a["anchors"]] != [x["phase_x"] for x in b["anchors"]]


def test_generate_layers_random_seed_is_returned(qapp):
    layers = BG.generate_layers(10, 10)
    assert 0 <= layers["seed"] <= 1_000_000


def test_generate_layers_anchor_count_and_alpha_ranges(qapp):
    for seed in range(10):
        dark = BG.generate_layers(50, 50, seed=seed)
        light = BG.generate_layers(50, 50, seed=seed, light_mode=True)
        assert 4 <= len(dark["anchors"]) <= 5
        assert all(90 <= a["color"].alpha() <= 130 for a in dark["anchors"])
        assert all(70 <= a["color"].alpha() <= 110 for a in light["anchors"])


def test_light_mode_base_color_is_bright_and_dark_mode_is_dark(qapp):
    assert BG.generate_layers(50, 50, seed=3, light_mode=True)["base_color"].value() > 200
    assert BG.generate_layers(50, 50, seed=3)["base_color"].value() < 60


def test_custom_palette_accepts_strings_and_qcolors(qapp):
    layers = BG.generate_layers(50, 50, seed=1, palette=["#ff0000", QColor("#0000ff")])
    assert layers["anchors"][0]["color"].red() == 255
    assert layers["anchors"][1]["color"].blue() == 255


@pytest.mark.parametrize("w,h", [(0, 0), (-5, 10), (1, 1), (90, 80), (300, 250)])
def test_generate_returns_requested_size_even_for_degenerate_input(qapp, w, h):
    pm = BG.generate(w, h, seed=5)
    assert (pm.width(), pm.height()) == (max(1, w), max(1, h))


@pytest.mark.parametrize("light", [False, True])
def test_render_frame_changes_over_time_and_reuses_tiny_pixmap(qapp, light):
    layers = BG.generate_layers(90, 80, seed=11, light_mode=light)
    tiny = QPixmap(20, 16)
    f0 = BG.render_frame(90, 80, layers, 0, tiny_pixmap=tiny).toImage()
    f1 = BG.render_frame(90, 80, layers, 400).toImage()
    assert f0 != f1


def test_all_builtin_palettes_are_valid_hex():
    for pal in BG.PRISM_PALETTES:
        assert pal and all(QColor(c).isValid() for c in pal)


@pytest.mark.parametrize("name", ["draw_aurora_border", "draw_rainbow_border", "draw_prism_shard_border", "draw_liquid_mercury_border"])
@pytest.mark.parametrize("progress", [0.0, 0.5, 0.8, 0.95, 1.0])
def test_border_effects_paint(qapp, name, progress):
    img = new_image()
    p = QPainter(img)
    getattr(fx, name)(p, QRectF(10, 10, 140, 80), progress, width=2)
    p.end()
    assert alpha_count(img) > 0 or progress == 1.0


def test_border_effect_fades_out_near_end(qapp):
    def count(progress):
        img = new_image()
        p = QPainter(img)
        fx.draw_rainbow_border(p, QRectF(10, 10, 140, 80), progress, width=3)
        p.end()
        return sum(QColor.fromRgba(img.pixel(x, y)).alpha() for y in range(100) for x in range(160))
    assert count(0.5) > count(0.95)


def test_border_effect_reactivates_inactive_painter(qapp):
    img = new_image()
    p = QPainter(img)
    p.end()
    fx.draw_aurora_border(p, QRectF(10, 10, 140, 80), 0.3)
    assert alpha_count(img) > 0
    p.end()


class FakeScreen:
    def __init__(self, pixmap):
        self.pixmap = pixmap
        self.args = None

    def geometry(self):
        from PyQt6.QtCore import QRect
        return QRect(0, 0, 1920, 1080)

    def grabWindow(self, wid, x, y, w, h):
        self.args = (wid, x, y, w, h)
        return self.pixmap


class FakeTarget:
    class container:
        @staticmethod
        def x():
            return 10

        @staticmethod
        def width():
            return 300

    def x(self):
        return 100

    def width(self):
        return 320


def test_capture_glass_background_no_screen(monkeypatch):
    monkeypatch.setattr(fx.QApplication, 'primaryScreen', staticmethod(lambda: None))
    assert fx.capture_glass_background(FakeTarget()) == (None, None)


def test_capture_glass_background_null_grab(monkeypatch):
    monkeypatch.setattr(fx.QApplication, 'primaryScreen', staticmethod(lambda: FakeScreen(QPixmap())))
    assert fx.capture_glass_background(FakeTarget()) == (None, None)


def test_capture_glass_background_returns_blurred_pixmap_and_origin(qapp, monkeypatch):
    screen = FakeScreen(solid(300, 1080, "#3050a0"))
    monkeypatch.setattr(fx.QApplication, 'primaryScreen', staticmethod(lambda: screen))
    pm, origin = fx.capture_glass_background(FakeTarget())
    assert screen.args == (0, 110, 0, 300, 1080)
    assert (pm.width(), pm.height()) == (300, 1080)
    assert origin == QPoint(110, 0)


def test_frosted_pill_without_background_returns_light_text(qapp):
    img = new_image()
    p = QPainter(img)
    color = draw_frosted_pill(p, QRectF(10, 10, 100, 28))
    p.end()
    assert color.red() == 255 and alpha_count(img) > 0


def test_frosted_pill_dark_background_uses_light_text(qapp):
    img = new_image(200, 100)
    p = QPainter(img)
    color = draw_frosted_pill(p, QRectF(10, 10, 100, 28), solid(200, 100, "#101010"))
    p.end()
    assert color.red() == 255


def test_frosted_pill_light_background_uses_dark_text(qapp):
    img = new_image(200, 100)
    p = QPainter(img)
    color = draw_frosted_pill(p, QRectF(10, 10, 100, 28), solid(200, 100, "#f0f0f0"))
    p.end()
    assert color.red() == 0


def test_frosted_pill_force_dark_overrides_light_background(qapp):
    img = new_image(200, 100)
    p = QPainter(img)
    color = draw_frosted_pill(p, QRectF(10, 10, 100, 28), solid(200, 100, "#f0f0f0"), force_dark=True)
    p.end()
    assert color.red() == 255


def test_frosted_pill_offsets_shift_sampled_region(qapp):
    bg = solid(200, 100, "#000000")
    p0 = QPainter(bg)
    p0.fillRect(100, 0, 100, 100, QColor("#ffffff"))
    p0.end()
    img = new_image(200, 100)
    p = QPainter(img)
    dark = draw_frosted_pill(p, QRectF(0, 10, 50, 28), bg, bg_x_offset=0)
    light = draw_frosted_pill(p, QRectF(0, 10, 50, 28), bg, bg_x_offset=120)
    p.end()
    assert dark.red() == 255 and light.red() == 0


def test_toggle_switch_toggles_and_animates(qtbot):
    sw = ToggleSwitch("Label")
    qtbot.addWidget(sw)
    with qtbot.waitSignal(sw.toggled) as sig:
        sw.setChecked(True)
    assert sig.args == [True]
    qtbot.waitUntil(lambda: sw._pos == 1.0, timeout=3000)
    sw.setChecked(False)
    qtbot.waitUntil(lambda: sw._pos == 0.0, timeout=3000)


def test_toggle_switch_size_hint_includes_label(qtbot):
    plain, labelled = ToggleSwitch(), ToggleSwitch("Some label")
    qtbot.addWidget(plain)
    qtbot.addWidget(labelled)
    assert plain.sizeHint().width() == ToggleSwitch.W
    assert labelled.sizeHint().width() > ToggleSwitch.W


@pytest.mark.parametrize("enabled", [True, False])
def test_toggle_switch_renders(qtbot, enabled):
    sw = ToggleSwitch("Label", accent_color="#ff8800")
    qtbot.addWidget(sw)
    sw.setEnabled(enabled)
    sw.setChecked(True)
    sw.resize(sw.sizeHint())
    assert not sw.grab().isNull()


def test_toggle_switch_click_toggles(qtbot):
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.show()
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton)
    assert sw.isChecked()


def test_footer_button_renders_for_both_styles(qtbot):
    btn = FooterButton("x")
    qtbot.addWidget(btn)
    btn.resize(40, 26)
    assert not btn.grab().isNull()
    btn.button_style = 'Flat'
    assert not btn.grab().isNull()


@pytest.fixture
def pager(qtbot):
    w = PageIndicatorButton(page_count=4, current_page=1)
    qtbot.addWidget(w)
    return w


def test_page_indicator_fixed_size(pager):
    assert (pager.width(), pager.height()) == (PAGE_INDICATOR_WIDTH, FOOTER_HEIGHT)


def test_page_indicator_dot_hit_testing(pager):
    start = (pager.width() - 3 * pager.DOT_SPACING) / 2
    for i in range(4):
        assert pager._dot_index_at(start + i * pager.DOT_SPACING) == i
    assert pager._dot_index_at(-50) == -1
    pager.set_page_count(0)
    assert pager._dot_index_at(10) == -1


def test_page_indicator_click_jumps_to_other_dot_only(qtbot, pager):
    start = (pager.width() - 3 * pager.DOT_SPACING) / 2
    got = []
    pager.page_jumped.connect(got.append)
    qtbot.mouseClick(pager, Qt.MouseButton.LeftButton, pos=QPoint(int(start + 2 * pager.DOT_SPACING), 10))
    qtbot.mouseClick(pager, Qt.MouseButton.LeftButton, pos=QPoint(int(start + 1 * pager.DOT_SPACING), 10))
    assert got == [2]


def test_page_indicator_wheel_direction(pager):
    got = []
    pager.page_scrolled.connect(got.append)
    for dy in (120, -120, 0):
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        pager.wheelEvent(ev)
    assert got == [-1, 1]


def test_page_indicator_set_page_bounces_and_renders(pager):
    pager.set_page(2)
    assert pager._current_page == 2
    pager.set_light_mode(True)
    assert pager._is_light is True
    assert not pager.grab().isNull()
    pager.set_page_count(0)
    assert not pager.grab().isNull()


@pytest.mark.parametrize("effect", ["None", "Rainbow", "Aurora Borealis", "Prism Shard", "Liquid Mercury"])
def test_effect_combobox_modes(qtbot, effect):
    cb = EffectComboBox()
    qtbot.addWidget(cb)
    cb.addItems(["a", "b"])
    cb.set_effect(effect)
    animated = effect != "None"
    assert (cb.anim.state() == cb.anim.State.Running) is animated
    assert (cb.display_timer.isActive()) is animated
    assert not cb.grab().isNull()


def test_effect_combobox_silent_update_hides_border(qtbot):
    cb = EffectComboBox()
    qtbot.addWidget(cb)
    cb.set_effect("Rainbow", animate=False)
    assert cb.get_border_opacity() == 0.0
    assert cb.anim.state() != cb.anim.State.Running


def test_effect_combobox_fades_out_then_stops(qtbot):
    cb = EffectComboBox()
    qtbot.addWidget(cb)
    cb.set_effect("Aurora Borealis")
    qtbot.waitUntil(lambda: cb.anim.state() != cb.anim.State.Running, timeout=5000)
    assert cb.get_border_opacity() == 0.0


def test_effect_combobox_switching_to_none_stops_everything(qtbot):
    cb = EffectComboBox()
    qtbot.addWidget(cb)
    cb.set_effect("Rainbow")
    cb.set_effect("None")
    assert cb.anim.state() != cb.anim.State.Running
    assert not cb.display_timer.isActive()


@pytest.fixture
def welcome(qtbot):
    w = WelcomeBanner()
    qtbot.addWidget(w)
    w.show_at(0, 360, 400, above=True)
    return w


def test_welcome_banner_walks_through_steps_then_finishes(qtbot, welcome):
    n = len(welcome._steps)
    assert n >= 2
    for i in range(n - 1):
        welcome.btn_next.click()
        assert welcome._step == i + 1
        assert welcome.dot_widget._step == i + 1
    with qtbot.waitSignal(welcome.finished, timeout=3000):
        welcome.btn_next.click()


def test_welcome_banner_skip_emits_finished_once(qtbot, welcome):
    hits = []
    welcome.finished.connect(lambda: hits.append(1))
    welcome.btn_skip.click()
    welcome.btn_skip.click()
    qtbot.waitUntil(lambda: bool(hits), timeout=3000)
    qtbot.wait(300)
    assert hits == [1]


def test_welcome_banner_height_follows_text_and_keeps_bottom_anchor(welcome):
    welcome._steps[1] = ("T", "long body " * 120)
    top_before = welcome._target_y + welcome.height()
    welcome.btn_next.click()
    assert welcome._target_y + welcome.height() == top_before


@pytest.mark.parametrize("kwargs", [{}, {"glass_ui": True, "glass_is_light": True}, {"border_effect": "Rainbow"}, {"button_style": "Flat"}])
def test_welcome_banner_renders(qtbot, kwargs):
    w = WelcomeBanner(**kwargs)
    qtbot.addWidget(w)
    w.show_at(0, 360, 400, above=False)
    assert not w.grab().isNull()


def test_dots_widget_paint_and_size(qtbot):
    d = _DotsWidget(5, is_light=True)
    qtbot.addWidget(d)
    d.resize(d.sizeHint())
    d.set_step(3)
    assert d.sizeHint().width() == 5 * 6 + 4 * 4
    assert not d.grab().isNull()
