import io
import json
import threading

import pytest

from ui import icons
from ui.icons import Icons, get_icon, get_icon_for_type


@pytest.fixture
def reset_icons(monkeypatch, tmp_path):
    monkeypatch.setattr(icons, '_mdi_cache', {})
    monkeypatch.setattr(icons, '_is_fetching', False)
    missing = tmp_path / "none.json"
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: missing)
    monkeypatch.setattr(icons, 'get_config_path', lambda name="x": tmp_path / name)
    return tmp_path


@pytest.fixture
def no_thread(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self)

    monkeypatch.setattr(threading, 'Thread', FakeThread)
    return started


def test_get_icon_empty_name_returns_placeholder(reset_icons):
    assert get_icon("") == Icons.CIRCLE_OUTLINE
    assert get_icon(None) == Icons.CIRCLE_OUTLINE


def test_get_icon_loads_bundled_mapping_and_strips_prefix(reset_icons, monkeypatch):
    bundled = reset_icons / "bundled.json"
    bundled.write_text(json.dumps({"home": "H", "lamp": "L"}), encoding="utf-8")
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: bundled)
    assert get_icon("mdi:home") == "H"
    assert get_icon("lamp") == "L"


def test_get_icon_unknown_name_returns_placeholder(reset_icons, monkeypatch):
    bundled = reset_icons / "bundled.json"
    bundled.write_text(json.dumps({"home": "H"}), encoding="utf-8")
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: bundled)
    assert get_icon("mdi:nonexistent") == Icons.CIRCLE_OUTLINE


def test_get_icon_corrupt_bundled_falls_back_to_cached_config(reset_icons, monkeypatch):
    bundled = reset_icons / "bundled.json"
    bundled.write_text("{not json", encoding="utf-8")
    cached = reset_icons / "mdi_mapping.json"
    cached.write_text(json.dumps({"star": "S"}), encoding="utf-8")
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: bundled)
    assert get_icon("star") == "S"


def test_get_icon_corrupt_everywhere_starts_background_fetch(reset_icons, monkeypatch, no_thread):
    bundled = reset_icons / "bundled.json"
    bundled.write_text("oops", encoding="utf-8")
    (reset_icons / "mdi_mapping.json").write_text("oops", encoding="utf-8")
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: bundled)
    assert get_icon("home") == Icons.CIRCLE_OUTLINE
    assert len(no_thread) == 1
    assert no_thread[0].daemon is True
    assert no_thread[0].target is icons.fetch_mdi_mapping_worker


def test_get_icon_fetch_started_only_once(reset_icons, no_thread):
    get_icon("a")
    get_icon("b")
    assert len(no_thread) == 1


def test_get_icon_uses_cache_without_touching_disk(reset_icons, monkeypatch):
    monkeypatch.setattr(icons, '_mdi_cache', {"x": "X"})
    monkeypatch.setattr(icons, 'get_resource_path', lambda n: (_ for _ in ()).throw(AssertionError))
    assert get_icon("x") == "X"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


CSS = (
    '.mdi-home::before { content: "\\F02DC"; }\n'
    '.mdi-lamp-2::before{content:"\\f06b5"}\n'
    '.mdi-bad::before { color: red; }\n'
)


def test_fetch_worker_parses_css_saves_and_emits(reset_icons, monkeypatch, qtbot):
    monkeypatch.setattr(icons.urllib.request, 'urlopen', lambda url, context=None: FakeResponse(CSS.encode()))
    with qtbot.waitSignal(icons.icon_signals.mapping_loaded, timeout=2000):
        icons.fetch_mdi_mapping_worker()
    assert icons._mdi_cache == {"home": chr(0xF02DC), "lamp-2": chr(0xF06B5)}
    saved = json.loads((reset_icons / "mdi_mapping.json").read_text(encoding="utf-8"))
    assert saved == icons._mdi_cache
    assert icons._is_fetching is False


def test_fetch_worker_swallows_network_errors_and_resets_flag(reset_icons, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(icons.urllib.request, 'urlopen', boom)
    monkeypatch.setattr(icons, '_is_fetching', True)
    icons.fetch_mdi_mapping_worker()
    assert icons._is_fetching is False
    assert icons._mdi_cache == {}
    assert not (reset_icons / "mdi_mapping.json").exists()


def test_fetch_worker_uses_https_url():
    assert icons.MDI_CSS_URL.startswith("https://")


@pytest.mark.xfail(strict=True, reason="fetch_mdi_mapping_worker disables TLS certificate verification via ssl._create_unverified_context")
def test_fetch_worker_verifies_tls(reset_icons, monkeypatch):
    seen = {}

    def fake_urlopen(url, context=None):
        seen['ctx'] = context
        return FakeResponse(b"")
    monkeypatch.setattr(icons.urllib.request, 'urlopen', fake_urlopen)
    icons.fetch_mdi_mapping_worker()
    import ssl
    assert seen['ctx'] is None or seen['ctx'].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("etype,state,expected", [
    ("switch", "on", Icons.LIGHTBULB),
    ("switch", "off", Icons.LIGHTBULB_OFF),
    ("script", "off", Icons.SCRIPT),
    ("automation", "on", Icons.AUTOMATION),
    ("curtain", "open", Icons.BLINDS_OPEN),
    ("curtain", "closed", Icons.BLINDS),
    ("climate", "heat", Icons.FIRE),
    ("climate", "cool", Icons.SNOWFLAKE),
    ("climate", "on", Icons.THERMOMETER_HIGH),
    ("climate", "off", Icons.THERMOMETER),
    ("widget", "any", Icons.GAUGE),
    ("fan", "on", Icons.FAN),
    ("fan", "off", Icons.FAN),
    ("lock", "locked", Icons.LOCK),
    ("lock", "unlocked", Icons.LOCK_OPEN),
    ("sun", "above_horizon", Icons.WEATHER_SUNNY),
    ("unknown", "off", Icons.PLUS_CIRCLE),
    ("", "", Icons.PLUS_CIRCLE),
])
def test_get_icon_for_type(etype, state, expected):
    assert get_icon_for_type(etype, state) == expected


def test_get_icon_for_type_default_state_is_off():
    assert get_icon_for_type("switch") == Icons.LIGHTBULB_OFF


def test_lock_jammed_uses_mapping_lookup(reset_icons, monkeypatch):
    monkeypatch.setattr(icons, '_mdi_cache', {"lock-alert": "JAM"})
    assert get_icon_for_type("lock", "jammed") == "JAM"


def test_alarm_states_use_map_and_fallback(reset_icons, monkeypatch):
    monkeypatch.setattr(icons, '_mdi_cache', dict.fromkeys(set(icons._ALARM_ICON_MAP.values()) | {"shield-off-outline"}, "?"))
    for state, name in icons._ALARM_ICON_MAP.items():
        monkeypatch.setattr(icons, '_mdi_cache', {name: "ICON:" + name})
        assert get_icon_for_type("alarm_control_panel", state) == "ICON:" + name
    monkeypatch.setattr(icons, '_mdi_cache', {"shield-off-outline": "DEF"})
    assert get_icon_for_type("alarm_control_panel", "weird") == "DEF"


def test_alarm_map_covers_core_states():
    for state in ("disarmed", "armed_home", "armed_away", "armed_night", "triggered", "arming", "pending"):
        assert state in icons._ALARM_ICON_MAP


def test_icon_constants_are_single_private_use_chars():
    consts = {k: v for k, v in vars(Icons).items() if k.isupper() and isinstance(v, str)}
    assert consts
    for name, value in consts.items():
        assert len(value) == 1, name
        assert ord(value) >= 0xE000, name


def test_get_mdi_font_returns_requested_size(qtbot):
    font = icons.get_mdi_font(18)
    assert font.pointSize() == 18
    assert font.family() == icons.MDI_FONT_FAMILY


def test_load_mdi_font_success_and_idempotent(qapp, monkeypatch):
    monkeypatch.setattr(icons, '_font_loaded', False)
    monkeypatch.setattr(icons, 'MDI_FONT_FAMILY', "Material Design Icons")
    assert icons.load_mdi_font() is True
    assert icons._font_loaded is True
    assert icons.load_mdi_font() is True


def test_load_mdi_font_missing_file(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(icons, '_font_loaded', False)
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: tmp_path / "missing.ttf")
    assert icons.load_mdi_font() is False
    assert icons._font_loaded is False


def test_load_mdi_font_invalid_font_file(qapp, monkeypatch, tmp_path):
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not a font")
    monkeypatch.setattr(icons, '_font_loaded', False)
    monkeypatch.setattr(icons, 'get_resource_path', lambda name: bad)
    assert icons.load_mdi_font() is False
