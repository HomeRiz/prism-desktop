import asyncio
import builtins
import io
import types
from pathlib import Path

import pytest

from services import location_manager as lm


@pytest.fixture
def home(isolated_home):
    return isolated_home


def set_platform(monkeypatch, name):
    monkeypatch.setattr(lm.sys, "platform", name)


async def test_get_location_dispatches_to_windows(monkeypatch):
    set_platform(monkeypatch, "win32")

    async def fake():
        return {"gps": [1, 2], "gps_accuracy": 3}

    monkeypatch.setattr(lm, "_get_windows_location", fake)
    assert await lm.get_location() == {"gps": [1, 2], "gps_accuracy": 3}


async def test_get_location_dispatches_to_linux(monkeypatch):
    set_platform(monkeypatch, "linux")

    async def fake():
        return {"gps": [4, 5], "gps_accuracy": 6}

    monkeypatch.setattr(lm, "_get_linux_location", fake)
    assert await lm.get_location() == {"gps": [4, 5], "gps_accuracy": 6}


async def test_get_location_unsupported_platform_returns_none(monkeypatch):
    set_platform(monkeypatch, "darwin")
    assert await lm.get_location() is None


class FakeStatus:
    ALLOWED = "allowed"
    DENIED = "denied"


class FakeGeolocator:
    status = FakeStatus.ALLOWED
    position_error = None

    @staticmethod
    async def request_access_async():
        return FakeGeolocator.status

    def __init__(self):
        self.desired_accuracy = None
        FakeGeolocator.last = self

    async def get_geoposition_async(self):
        if FakeGeolocator.position_error:
            raise FakeGeolocator.position_error
        coord = types.SimpleNamespace(latitude=48.85, longitude=2.35, accuracy=25.0)
        return types.SimpleNamespace(coordinate=coord)


@pytest.fixture
def winrt(monkeypatch):
    FakeGeolocator.status = FakeStatus.ALLOWED
    FakeGeolocator.position_error = None
    monkeypatch.setattr(lm, "_WINRT_AVAILABLE", True)
    monkeypatch.setattr(lm, "Geolocator", FakeGeolocator, raising=False)
    monkeypatch.setattr(lm, "GeolocationAccessStatus", FakeStatus, raising=False)
    monkeypatch.setattr(lm, "PositionAccuracy", types.SimpleNamespace(HIGH="high"), raising=False)


async def test_windows_location_success(winrt):
    result = await lm._get_windows_location()
    assert result == {"gps": [48.85, 2.35], "gps_accuracy": 25.0}
    assert FakeGeolocator.last.desired_accuracy == "high"


async def test_windows_location_without_winrt_package(monkeypatch):
    monkeypatch.setattr(lm, "_WINRT_AVAILABLE", False)
    assert await lm._get_windows_location() is None


async def test_windows_location_access_denied(winrt):
    FakeGeolocator.status = FakeStatus.DENIED
    assert await lm._get_windows_location() is None


async def test_windows_location_api_error_is_swallowed(winrt):
    FakeGeolocator.position_error = RuntimeError("no fix")
    assert await lm._get_windows_location() is None


class FakeProxyInterface:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def __getattr__(self, attr):
        return getattr(self.owner, f"{self.name}_{attr}")


class FakeGeoClueBus:
    instances = []

    def __init__(self, bus_type=None):
        self.bus_type = bus_type
        self.disconnected = False
        self.sets = []
        self.fire = True
        self.started = False
        self.stopped = False
        self.callback = None
        self.fail_at = None
        FakeGeoClueBus.instances.append(self)

    async def connect(self):
        if self.fail_at == "connect":
            raise OSError("no bus")
        return self

    async def introspect(self, name, path):
        if self.fail_at == "introspect":
            raise RuntimeError("no geoclue")
        return path

    def get_proxy_object(self, name, path, introspection):
        bus = self

        class Proxy:
            def get_interface(self, iface):
                short = iface.rsplit(".", 1)[-1]
                return FakeProxyInterface(bus, short)

        return Proxy()

    def disconnect(self):
        self.disconnected = True

    async def Manager_call_get_client(self):
        return "/client/1"

    async def Properties_call_set(self, iface, prop, variant):
        self.sets.append((prop, variant.signature, variant.value))

    def Client_on_location_updated(self, cb):
        self.callback = cb

    async def Client_call_start(self):
        self.started = True
        if self.fire:
            self.callback("/old", "/loc/1")

    async def Client_call_stop(self):
        self.stopped = True

    async def Location_get_latitude(self):
        return 51.5

    async def Location_get_longitude(self):
        return -0.12

    async def Location_get_accuracy(self):
        return 10.0


@pytest.fixture
def geoclue(monkeypatch, fake_dbus_modules):
    FakeGeoClueBus.instances = []
    monkeypatch.setattr(lm, "_DBUS_NEXT_AVAILABLE", True)
    monkeypatch.setattr(lm, "MessageBus", FakeGeoClueBus, raising=False)
    monkeypatch.setattr(lm, "BusType", fake_dbus_modules.BusType, raising=False)
    monkeypatch.setattr(lm, "Variant", fake_dbus_modules.Variant, raising=False)
    return FakeGeoClueBus


async def test_geoclue_flow_returns_position_and_cleans_up(geoclue):
    result = await lm._get_linux_location()
    bus = geoclue.instances[0]
    assert result == {"gps": [51.5, -0.12], "gps_accuracy": 10.0}
    assert ("DesktopId", "s", "prism-desktop") in bus.sets
    assert ("RequestedAccuracyLevel", "u", 8) in bus.sets
    assert bus.started and bus.stopped and bus.disconnected
    assert bus.bus_type.name == "SYSTEM"


async def test_geoclue_timeout_returns_none_and_disconnects(geoclue, monkeypatch):
    real_wait_for = asyncio.wait_for

    async def quick(fut, timeout):
        return await real_wait_for(fut, 0.05)

    monkeypatch.setattr(lm.asyncio, "wait_for", quick)
    original_init = geoclue.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.fire = False

    monkeypatch.setattr(geoclue, "__init__", init)
    assert await lm._get_linux_location() is None
    assert geoclue.instances[0].disconnected is True


@pytest.mark.parametrize("stage", ["connect", "introspect"])
async def test_geoclue_failures_return_none(geoclue, monkeypatch, stage):
    original_init = geoclue.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.fail_at = stage

    monkeypatch.setattr(geoclue, "__init__", init)
    assert await lm._get_linux_location() is None


async def test_linux_location_without_dbus_next(monkeypatch):
    monkeypatch.setattr(lm, "_DBUS_NEXT_AVAILABLE", False)
    assert await lm._get_linux_location() is None


async def test_geoclue_available_probe(geoclue, monkeypatch):
    assert await lm.is_geoclue2_available() is True
    assert geoclue.instances[0].disconnected is True
    original_init = geoclue.__init__

    def init(self, bus_type=None):
        original_init(self, bus_type)
        self.fail_at = "introspect"

    monkeypatch.setattr(geoclue, "__init__", init)
    assert await lm.is_geoclue2_available() is False


async def test_geoclue_available_false_without_dbus_next(monkeypatch):
    monkeypatch.setattr(lm, "_DBUS_NEXT_AVAILABLE", False)
    assert await lm.is_geoclue2_available() is False


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("APPIMAGELAUNCHER_DISABLE", "DESKTOPINTEGRATION", "APPIMAGE", "APPDIR"):
        monkeypatch.delenv(name, raising=False)


def desktop_file(home):
    return home / ".local" / "share" / "applications" / "prism-desktop.desktop"


def test_ensure_desktop_file_creates_entry(home, clean_env):
    lm.ensure_desktop_file()
    text = desktop_file(home).read_text()
    assert "[Desktop Entry]" in text and "Exec=prism-desktop\n" in text and "Icon=prism-desktop\n" in text
    assert text.count("Name=Prism Desktop") == 1


def test_ensure_desktop_file_uses_appimage_path(home, clean_env, monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/opt/Prism.AppImage")
    lm.ensure_desktop_file()
    assert "Exec=/opt/Prism.AppImage\n" in desktop_file(home).read_text()


def test_ensure_desktop_file_never_overwrites_existing(home, clean_env):
    target = desktop_file(home)
    target.parent.mkdir(parents=True)
    target.write_text("custom")
    lm.ensure_desktop_file()
    assert target.read_text() == "custom"


@pytest.mark.parametrize("name,value", [("APPIMAGELAUNCHER_DISABLE", "1"), ("DESKTOPINTEGRATION", "yes")])
def test_ensure_desktop_file_skipped_when_integration_is_external(home, clean_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    lm.ensure_desktop_file()
    assert not desktop_file(home).exists()


def test_launcher_disable_flag_other_than_one_does_not_skip(home, clean_env, monkeypatch):
    monkeypatch.setenv("APPIMAGELAUNCHER_DISABLE", "0")
    lm.ensure_desktop_file()
    assert desktop_file(home).exists()


def test_install_appimage_icon_copies_bundled_icon(home, tmp_path):
    src = tmp_path / "AppDir" / "usr/share/icons/hicolor/256x256/apps/prism-desktop.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"png")
    dest = lm._install_appimage_icon(str(tmp_path / "AppDir"))
    assert Path(dest) == home / ".local/share/icons/hicolor/256x256/apps/prism-desktop.png"
    assert Path(dest).read_bytes() == b"png"


def test_install_appimage_icon_missing_returns_theme_name(home, tmp_path):
    assert lm._install_appimage_icon(str(tmp_path)) == "prism-desktop"


def test_ensure_desktop_file_with_appdir_uses_copied_icon(home, clean_env, monkeypatch, tmp_path):
    src = tmp_path / "AppDir" / "usr/share/icons/hicolor/256x256/apps/prism-desktop.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"png")
    monkeypatch.setenv("APPDIR", str(tmp_path / "AppDir"))
    lm.ensure_desktop_file()
    assert f"Icon={home}/.local/share/icons/hicolor/256x256/apps/prism-desktop.png" in desktop_file(home).read_text()


def test_distro_info_parses_os_release(monkeypatch):
    content = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\n'
    monkeypatch.setattr(builtins, "open", lambda *a, **k: io.StringIO(content))
    assert lm.get_distro_info() == {"id": "ubuntu", "name": "Ubuntu"}


def test_distro_info_defaults_when_file_missing(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(builtins, "open", missing)
    assert lm.get_distro_info() == {"id": "linux", "name": "Linux"}


@pytest.mark.parametrize("distro,fragment", [
    ("ubuntu", "apt install geoclue-2.0"),
    ("debian", "apt install geoclue-2.0"),
    ("fedora", "dnf install geoclue2"),
    ("arch", "pacman -S geoclue"),
    ("opensuse-tumbleweed", "zypper install geoclue2"),
    ("gentoo", "package manager"),
])
def test_install_hint(distro, fragment):
    assert fragment in lm.get_geoclue2_install_hint(distro)
