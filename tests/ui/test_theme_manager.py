import subprocess
from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from ui import theme_manager as tm_mod
from ui.theme_manager import ThemeManager


def completed(rc=0, out=""):
    return SimpleNamespace(returncode=rc, stdout=out)


@pytest.fixture
def tm(qtbot):
    return ThemeManager()


@pytest.fixture(autouse=True)
def restore_palette(qapp):
    saved = qapp.palette()
    yield
    qapp.setPalette(saved)


def test_defaults(tm):
    assert tm.get_effective_theme() == 'dark'
    assert tm.get_colors() is ThemeManager.DARK_COLORS


def test_palettes_have_identical_keys():
    assert set(ThemeManager.DARK_COLORS) == set(ThemeManager.LIGHT_COLORS)


def test_palette_values_are_valid_colors():
    for palette in (ThemeManager.DARK_COLORS, ThemeManager.LIGHT_COLORS):
        for value in palette.values():
            assert QColor(value).isValid()


def test_set_light_emits_and_applies_palette(tm, qtbot, qapp):
    with qtbot.waitSignal(tm.theme_changed) as blocker:
        tm.set_theme('light')
    assert blocker.args == ['light']
    assert tm.get_effective_theme() == 'light'
    assert tm.get_colors() is ThemeManager.LIGHT_COLORS
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(ThemeManager.LIGHT_COLORS['window'])


def test_set_same_theme_does_not_emit(tm, qtbot):
    with qtbot.assertNotEmitted(tm.theme_changed):
        tm.set_theme('dark')


def test_set_dark_after_light_applies_dark_palette(tm, qapp):
    tm.set_theme('light')
    tm.set_theme('dark')
    assert qapp.palette().color(QPalette.ColorRole.Base) == QColor(ThemeManager.DARK_COLORS['base'])


def test_system_theme_resolved_through_detector(tm, monkeypatch):
    monkeypatch.setattr(tm, 'get_system_theme', lambda: 'light')
    tm.set_theme('system')
    assert tm.get_effective_theme() == 'light'
    assert tm._current_theme == 'system'


def test_apply_theme_without_app_is_noop(tm, monkeypatch):
    monkeypatch.setattr(tm_mod.QApplication, 'instance', staticmethod(lambda: None))
    tm._apply_theme('light')


def test_unknown_platform_defaults_to_dark(tm, monkeypatch):
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Plan9')
    assert tm.get_system_theme() == 'dark'


@pytest.mark.parametrize("rc,out,expected", [(0, "Dark\n", 'dark'), (1, "", 'light')])
def test_macos_detection(tm, monkeypatch, rc, out, expected):
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(tm_mod.subprocess, 'run', lambda *a, **k: completed(rc, out))
    assert tm.get_system_theme() == expected


def test_macos_missing_defaults_binary_falls_back_to_light(tm, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(tm_mod.subprocess, 'run', boom)
    assert tm.get_system_theme() == 'light'


def test_linux_kde_scheme_wins(tm, monkeypatch):
    calls = []

    def run(cmd, **k):
        calls.append(cmd[0])
        return completed(0, "BreezeDark")
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tm_mod.subprocess, 'run', run)
    assert tm.get_system_theme() == 'dark'
    assert calls == ['kreadconfig5']


def test_linux_gnome_when_kde_missing(tm, monkeypatch):
    def run(cmd, **k):
        if cmd[0] == 'kreadconfig5':
            raise FileNotFoundError
        return completed(0, "'prefer-light'")
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tm_mod.subprocess, 'run', run)
    assert tm.get_system_theme() == 'light'


def test_linux_gtk_theme_fallback(tm, monkeypatch):
    def run(cmd, **k):
        if cmd[0] == 'kreadconfig5':
            raise FileNotFoundError
        if 'color-scheme' in cmd:
            return completed(1, "")
        return completed(0, "'Adwaita-dark'")
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tm_mod.subprocess, 'run', run)
    assert tm.get_system_theme() == 'dark'


def test_linux_all_detectors_timeout_defaults_dark(tm, monkeypatch):
    def run(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 2)
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(tm_mod.subprocess, 'run', run)
    assert tm.get_system_theme() == 'dark'


def test_windows_registry_failure_defaults_dark(tm, monkeypatch):
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Windows')
    assert tm.get_system_theme() == 'dark'


def test_windows_registry_light_value(tm, monkeypatch):
    fake = SimpleNamespace(
        HKEY_CURRENT_USER=0,
        OpenKey=lambda *a: object(),
        QueryValueEx=lambda key, name: (1, 4),
        CloseKey=lambda key: None,
    )
    monkeypatch.setitem(__import__('sys').modules, 'winreg', fake)
    monkeypatch.setattr(tm_mod.platform, 'system', lambda: 'Windows')
    assert tm.get_system_theme() == 'light'
    fake.QueryValueEx = lambda key, name: (0, 4)
    assert tm.get_system_theme() == 'dark'
