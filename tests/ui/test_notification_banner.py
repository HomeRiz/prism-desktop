import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ui.widgets.notification_banner import NotificationBanner, _CountdownButton, GAP
from ui.constants import BANNER_VERTICAL_MARGIN
from ui import notifications


@pytest.fixture
def make(qtbot):
    def _make(*args, **kwargs):
        banner = NotificationBanner(*args, **kwargs)
        qtbot.addWidget(banner)
        return banner
    return _make


def test_toast_has_close_button_and_no_confirm_buttons(make):
    b = make("hello")
    assert hasattr(b, 'btn_close')
    assert not hasattr(b, 'btn_yes')
    assert b._countdown_btn is b.btn_close
    assert b.label.text() == "hello"


def test_confirm_has_yes_no_buttons(make):
    b = make("sure?", banner_type="confirm")
    assert b.btn_yes.text() and b.btn_no.text()
    assert b._countdown_btn is b.btn_no
    assert not hasattr(b, 'btn_close')


def test_window_flags_are_frameless_tool_on_top(make):
    flags = make("x").windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool


def test_set_text_updates_label(make):
    b = make("a")
    b.set_text("b")
    assert b.label.text() == "b"


@pytest.mark.parametrize("kwargs", [
    {}, {"banner_type": "confirm"}, {"button_style": "Flat", "banner_type": "confirm"},
    {"glass_is_light": True, "banner_type": "confirm"},
    {"glass_is_light": True, "button_style": "Flat", "banner_type": "confirm"},
    {"text_color": "#101010", "glass_ui": True},
])
def test_constructs_with_style_variants(make, kwargs):
    assert make("msg", **kwargs).label.text() == "msg"


def test_compute_height_is_at_least_one_line_plus_margins(make):
    b = make("short")
    h = b._compute_content_height(400)
    assert h >= BANNER_VERTICAL_MARGIN * 2 + b.btn_close.height()


def test_compute_height_grows_for_long_text(make):
    short = make("x")
    long = make("word " * 80)
    assert long._compute_content_height(300) > short._compute_content_height(300)


def test_compute_height_for_confirm(make):
    b = make("word " * 40, banner_type="confirm")
    assert b._compute_content_height(320) > 0


def test_show_at_above_positions_banner_over_container(make, qtbot):
    b = make("hi", auto_dismiss_ms=0)
    b.show_at(10, 300, 500, above=True)
    assert b.width() == 300
    assert b._target_y == 500 - b.height() - GAP
    assert b.isVisible()
    assert b._timer_anim is None
    assert not b._dismiss_timer.isActive()


def test_show_at_below_positions_banner_under_container(make):
    b = make("hi", auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=False)
    assert b._target_y == 100 + GAP


def test_show_at_starts_dismiss_timer_and_countdown(make):
    b = make("hi", auto_dismiss_ms=5000)
    b.show_at(0, 300, 100, above=False)
    assert b._dismiss_timer.isActive()
    assert b._timer_anim is not None
    assert b._timer_anim.duration() == 5000


def test_toast_auto_dismiss_emits_dismissed(make, qtbot):
    b = make("hi", auto_dismiss_ms=40)
    b.show_at(0, 300, 100, above=False)
    with qtbot.waitSignal(b.dismissed, timeout=3000):
        pass


def test_confirm_timeout_emits_rejected_not_dismissed(make, qtbot):
    b = make("hi", banner_type="confirm", auto_dismiss_ms=40)
    b.show_at(0, 300, 100, above=True)
    with qtbot.waitSignal(b.rejected, timeout=3000):
        pass


def test_yes_click_emits_confirmed(make, qtbot):
    b = make("hi", banner_type="confirm", auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=True)
    with qtbot.waitSignal(b.confirmed, timeout=3000):
        qtbot.mouseClick(b.btn_yes, Qt.MouseButton.LeftButton)


def test_no_click_emits_rejected(make, qtbot):
    b = make("hi", banner_type="confirm", auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=True)
    with qtbot.waitSignal(b.rejected, timeout=3000):
        b.btn_no.click()


def test_close_click_emits_dismissed(make, qtbot):
    b = make("hi", auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=False)
    with qtbot.waitSignal(b.dismissed, timeout=3000):
        b.btn_close.click()


def test_double_click_emits_once(make, qtbot):
    b = make("hi", banner_type="confirm", auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=True)
    hits = []
    b.confirmed.connect(lambda: hits.append(1))
    b.btn_yes.click()
    b.btn_yes.click()
    qtbot.waitUntil(lambda: bool(hits), timeout=3000)
    qtbot.wait(400)
    assert hits == [1]


def test_hover_cancels_auto_dismiss_and_countdown(make, qtbot):
    b = make("hi", auto_dismiss_ms=5000)
    b.show_at(0, 300, 100, above=False)
    b.btn_close.set_countdown(0.8)
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtCore import QPointF
    b.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert b._hovered is True
    assert not b._dismiss_timer.isActive()
    assert b.btn_close.get_countdown() == 0.0


def test_leave_event_keeps_hovered_state(make):
    from PyQt6.QtCore import QEvent
    b = make("hi")
    b._hovered = True
    b.leaveEvent(QEvent(QEvent.Type.Leave))
    assert b._hovered is True


@pytest.mark.parametrize("effect", ["None", "Rainbow", "Aurora Borealis", "Prism Shard", "Liquid Mercury", "Unknown"])
def test_border_effects_render(make, effect):
    b = make("hi", border_effect=effect, auto_dismiss_ms=0)
    b.show_at(0, 300, 100, above=False)
    b.set_glow_progress(0.5)
    assert b.get_glow_progress() == 0.5
    pix = b.grab()
    assert not pix.isNull()


def test_border_animation_runs_only_with_effect(make):
    plain = make("a", border_effect="None", auto_dismiss_ms=0)
    plain.show_at(0, 300, 100, above=False)
    assert plain.border_anim.state() != plain.border_anim.State.Running
    fancy = make("a", border_effect="Rainbow", auto_dismiss_ms=0)
    fancy.show_at(0, 300, 100, above=False)
    assert fancy.border_anim.state() == fancy.border_anim.State.Running


@pytest.mark.parametrize("light", [False, True])
def test_render_solid_background(make, light):
    b = make("hi", glass_is_light=light)
    b.setFixedSize(300, 60)
    assert b.grab().width() == 300


def test_render_glass_background_with_pixmap(make):
    b = make("hi", glass_ui=True, glass_is_light=True)
    b.setFixedSize(300, 60)
    pm = QPixmap(280, 56)
    pm.fill(Qt.GlobalColor.blue)
    b._glass_pixmap = pm
    assert not b.grab().isNull()


def test_capture_glass_background_rejects_empty_region(make):
    b = make("hi")
    assert b._capture_glass_background(0, 0, 0, 10) is None
    assert b._capture_glass_background(0, 0, 10, -1) is None


def test_capture_glass_background_handles_null_grab(make, monkeypatch):
    from ui.widgets import notification_banner as nb

    class Screen:
        def grabWindow(self, *a):
            return QPixmap()
    monkeypatch.setattr(nb.QApplication, 'primaryScreen', staticmethod(lambda: Screen()))
    assert make("hi")._capture_glass_background(0, 0, 10, 10) is None


def test_capture_glass_background_scales_back_to_target(make, monkeypatch):
    from ui.widgets import notification_banner as nb
    src = QPixmap(100, 40)
    src.fill(Qt.GlobalColor.red)

    class Screen:
        def grabWindow(self, wid, x, y, w, h):
            return src
    monkeypatch.setattr(nb.QApplication, 'primaryScreen', staticmethod(lambda: Screen()))
    out = make("hi")._capture_glass_background(0, 0, 100, 40)
    assert (out.width(), out.height()) == (100, 40)


def test_countdown_button_renders_with_arc_and_x(qtbot):
    btn = _CountdownButton("", is_light=True, x_icon=True)
    qtbot.addWidget(btn)
    btn.resize(30, 30)
    btn.set_countdown(0.5)
    assert btn.countdown == 0.5
    assert not btn.grab().isNull()
    btn.set_countdown(0.0)
    assert not btn.grab().isNull()


class FakeDashboard:
    def __init__(self):
        self.toasts = []
        self.confirms = []

    def show_toast(self, message, duration_ms=None):
        self.toasts.append((message, duration_ms))

    def show_confirm(self, message, on_confirm=None):
        self.confirms.append((message, on_confirm))


@pytest.fixture(autouse=True)
def stub_t(monkeypatch):
    monkeypatch.setattr(notifications, 't', lambda key, **kw: key + "|" + ",".join(f"{k}={v}" for k, v in sorted(kw.items())))


def test_notify_entity_unavailable_toast_contains_label():
    d = FakeDashboard()
    notifications.notify_entity_unavailable(d, "Lamp")
    assert "label=Lamp" in d.toasts[0][0]
    assert "<span" in d.toasts[0][0]


def test_notify_page_full_plain_toast():
    d = FakeDashboard()
    notifications.notify_page_full(d, 3)
    assert d.toasts == [("notifications.page_full|page_num=3", None)]


def test_notify_move_as_1x1_confirm_forwards_callback():
    d = FakeDashboard()
    cb = lambda: None
    notifications.notify_move_as_1x1(d, 2, 3, 4, cb)
    msg, got = d.confirms[0]
    assert "orig_h=3" in msg and "orig_w=2" in msg and "page_num=4" in msg
    assert got is cb


def test_notify_delete_shortcut_named_and_unnamed():
    d = FakeDashboard()
    notifications.notify_delete_shortcut(d, "Kitchen", None)
    notifications.notify_delete_shortcut(d, "", None)
    assert d.confirms[0][0].startswith("notifications.delete_shortcut|")
    assert d.confirms[1][0].startswith("notifications.delete_shortcut_unnamed")


def test_notify_update_available_and_simple_toasts():
    d = FakeDashboard()
    notifications.notify_update_available(d, "1.2.3", None)
    notifications.notify_update_restart(d)
    notifications.notify_update_success(d, "1.2.3")
    notifications.notify_update_sanity_failed(d, "1.2.4")
    notifications.notify_geoclue2_missing(d, "apt install x")
    notifications.notify_language_restart(d)
    assert "version=1.2.3" in d.confirms[0][0]
    assert len(d.toasts) == 5


def test_notify_update_error_with_and_without_detail():
    d = FakeDashboard()
    notifications.notify_update_error(d)
    notifications.notify_update_error(d, "boom")
    assert not d.toasts[0][0].endswith(": ")
    assert d.toasts[1][0].endswith(": boom")
    assert d.toasts[1][1] == 8000


def test_notify_download_error_links_to_releases_page():
    d = FakeDashboard()
    notifications.notify_download_error(d, "net")
    msg, dur = d.toasts[0]
    assert notifications._GH_RELEASES_URL in msg
    assert msg.startswith("notifications.update_error|: net") or ": net" in msg
    assert dur == 12000


def test_notify_connection_test_result_success_and_failure():
    d = FakeDashboard()
    notifications.notify_connection_test_result(d, True, "ignored")
    notifications.notify_connection_test_result(d, False, "bad token")
    assert "notifications.connected" in d.toasts[0][0]
    assert "ignored" not in d.toasts[0][0]
    assert "bad token" in d.toasts[1][0]


def test_notify_glass_ui_warning_is_delayed(qtbot):
    d = FakeDashboard()
    notifications.notify_glass_ui_warning(d)
    assert d.toasts == []
    qtbot.waitUntil(lambda: bool(d.toasts), timeout=3000)
    assert d.toasts[0][1] == 8000
