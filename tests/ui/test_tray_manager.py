import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QSystemTrayIcon

from ui import tray_manager as tm_mod
from ui.tray_manager import TrayManager


class FakeTray:
    instances = []

    def __init__(self, icon):
        self.icon = icon
        self.tooltip = None
        self.menu = None
        self.shown = False
        self.hidden = False
        self.handlers = []
        FakeTray.instances.append(self)

        class Sig:
            def connect(inner, fn):
                self.handlers.append(fn)
        self.activated = Sig()

    def setToolTip(self, text):
        self.tooltip = text

    def setContextMenu(self, menu):
        self.menu = menu

    def show(self):
        self.shown = True

    def hide(self):
        self.hidden = True

    def setIcon(self, icon):
        self.icon = icon

    def geometry(self):
        return QRect(1, 2, 3, 4)


@pytest.fixture
def tray(qapp, monkeypatch):
    FakeTray.instances = []
    monkeypatch.setattr(tm_mod, 'QSystemTrayIcon', type('Q', (FakeTray,), {'ActivationReason': QSystemTrayIcon.ActivationReason}))
    return TrayManager()


def test_icon_image_is_rgba_of_requested_size(tray):
    img = tray.create_icon_image(48)
    assert img.size == (48, 48) and img.mode == 'RGBA'


def test_icon_differs_between_dark_and_light(qapp):
    dark = TrayManager(theme='dark').create_icon_image(32)
    light = TrayManager(theme='light').create_icon_image(32)
    assert dark.getpixel((4, 16)) != light.getpixel((4, 16))
    assert dark.getpixel((16, 16))[3] == 255


def test_icon_corners_are_transparent_background_rounded(tray):
    assert tray.create_icon_image(64).getpixel((0, 0))[3] == 0


def test_to_qicon_is_not_null(tray):
    assert not tray._to_qicon(tray.create_icon_image(32)).isNull()


def test_start_creates_tray_with_tooltip_and_menu(tray, monkeypatch):
    monkeypatch.setattr(tm_mod.sys, 'platform', 'linux')
    tray.start()
    fake = FakeTray.instances[0]
    assert fake.shown and fake.tooltip
    assert fake.menu is tray._menu
    assert [a.isSeparator() for a in tray._menu.actions()] == [False, True, False]


def test_start_on_macos_does_not_set_context_menu(tray, monkeypatch):
    monkeypatch.setattr(tm_mod.sys, 'platform', 'darwin')
    tray.start()
    assert FakeTray.instances[0].menu is None


def test_menu_actions_emit_signals(qapp, monkeypatch):
    FakeTray.instances = []
    monkeypatch.setattr(tm_mod, 'QSystemTrayIcon', FakeTray)
    shown, quit_ = [], []
    t = TrayManager(on_left_click=lambda: shown.append(1), on_quit=lambda: quit_.append(1))
    t.start()
    acts = [a for a in t._menu.actions() if not a.isSeparator()]
    acts[0].trigger()
    acts[1].trigger()
    assert shown == [1] and quit_ == [1]


@pytest.mark.parametrize("name,emits", [("Trigger", True), ("DoubleClick", True), ("MiddleClick", True),
                                         ("Context", False), ("Unknown", False)])
def test_activation_reasons(tray, monkeypatch, qtbot, name, emits):
    tray.start()
    popped = []
    monkeypatch.setattr(tray._menu, 'popup', lambda pos: popped.append(pos))
    reason = getattr(QSystemTrayIcon.ActivationReason, name)
    if emits:
        with qtbot.waitSignal(tray.signals.left_clicked, timeout=1000):
            tray._on_activated(reason)
    else:
        with qtbot.assertNotEmitted(tray.signals.left_clicked):
            tray._on_activated(reason)
    assert bool(popped) is (name == "Context")


def test_context_activation_without_menu_is_safe(tray):
    tray._on_activated(QSystemTrayIcon.ActivationReason.Context)


def test_set_theme_updates_icon_and_stylesheet(tray):
    tray.start()
    before = tray._menu.styleSheet()
    tray.set_theme('light')
    assert tray.theme == 'light'
    assert tray._menu.styleSheet() != before
    assert '#ffffff' in tray._menu.styleSheet()


def test_set_theme_before_start_is_safe(tray):
    tray.set_theme('light')
    assert tray.theme == 'light'


def test_geometry_before_and_after_start(tray):
    assert tray.geometry() == QRect()
    tray.start()
    assert tray.geometry() == QRect(1, 2, 3, 4)


def test_stop_hides_and_clears(tray):
    tray.start()
    fake = FakeTray.instances[0]
    tray.stop()
    assert fake.hidden and tray._tray is None and tray._menu is None
    tray.stop()
    assert tray.geometry() == QRect()


def test_callbacks_wired_to_signals(qapp, qtbot):
    hits = []
    t = TrayManager(on_left_click=lambda: hits.append("l"), on_quit=lambda: hits.append("q"))
    t.signals.left_clicked.emit()
    t.signals.quit_clicked.emit()
    assert hits == ["l", "q"]


def test_menu_stylesheet_per_theme(qapp):
    assert '#1e1e1e' in TrayManager(theme='dark')._menu_stylesheet()
    assert '#d1d1d1' in TrayManager(theme='light')._menu_stylesheet()
