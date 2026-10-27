import ctypes
import os
import subprocess
import sys
import types
from collections import namedtuple
from datetime import datetime, timezone

import pytest

from services import system_sensors as ss

Battery = namedtuple("Battery", "percent secsleft power_plugged")
Temp = namedtuple("Temp", "label current high critical")

def fake_run(output):
    calls = []

    def run(cmd, timeout=2.0):
        calls.append(cmd)
        if callable(output):
            return output(cmd)
        return output

    run.calls = calls
    return run

def set_platform(monkeypatch, name):
    monkeypatch.setattr(sys, "platform", name)

def test_run_returns_stdout_on_success(monkeypatch):
    result = subprocess.CompletedProcess([], 0, stdout="hello", stderr="")
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: result)
    assert ss._run(["x"]) == "hello"

def test_run_returns_none_on_nonzero_exit(monkeypatch):
    result = subprocess.CompletedProcess([], 1, stdout="partial", stderr="")
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: result)
    assert ss._run(["x"]) is None

@pytest.mark.parametrize("exc", [FileNotFoundError(), subprocess.TimeoutExpired("x", 1), PermissionError()])
def test_run_returns_none_when_command_fails_to_launch(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(ss.subprocess, "run", boom)
    assert ss._run(["x"]) is None

def test_battery_level_rounds_percent(monkeypatch):
    monkeypatch.setattr(ss.psutil, "sensors_battery", lambda: Battery(83.456, 100, True), raising=False)
    assert ss.get_battery_level() == 83.5

def test_battery_missing_returns_none(monkeypatch):
    monkeypatch.setattr(ss.psutil, "sensors_battery", lambda: None, raising=False)
    assert ss.get_battery_level() is None
    assert ss.get_battery_charging() is None

def test_battery_errors_return_none(monkeypatch):
    def boom():
        raise RuntimeError

    monkeypatch.setattr(ss.psutil, "sensors_battery", boom, raising=False)
    assert ss.get_battery_level() is None

@pytest.mark.parametrize("plugged,expected", [(True, True), (False, False), (None, None)])
def test_battery_charging(monkeypatch, plugged, expected):
    monkeypatch.setattr(ss.psutil, "sensors_battery", lambda: Battery(50, 10, plugged), raising=False)
    assert ss.get_battery_charging() is expected

def test_disk_usage_queries_root_and_rounds(monkeypatch):
    seen = []

    def usage(path):
        seen.append(path)
        return types.SimpleNamespace(percent=61.789)

    monkeypatch.setattr(ss.psutil, "disk_usage", usage)
    assert ss.get_disk_usage() == 61.8
    assert seen == [os.path.abspath(os.sep)]

def test_disk_usage_error_returns_none(monkeypatch):
    def boom(path):
        raise OSError

    monkeypatch.setattr(ss.psutil, "disk_usage", boom)
    assert ss.get_disk_usage() is None

def test_cpu_temperature_prefers_known_chip_order(monkeypatch):
    chips = {
        "acpitz": [Temp("", 30.0, None, None)],
        "k10temp": [Temp("Tctl", 55.4, None, None)],
        "weird": [Temp("", 99.0, None, None)],
    }
    monkeypatch.setattr(ss.psutil, "sensors_temperatures", lambda: chips, raising=False)
    assert ss.get_cpu_temperature() == 55.4

def test_cpu_temperature_skips_empty_chip(monkeypatch):
    chips = {"coretemp": [], "cpu_thermal": [Temp("", 41.0, None, None)]}
    monkeypatch.setattr(ss.psutil, "sensors_temperatures", lambda: chips, raising=False)
    assert ss.get_cpu_temperature() == 41.0

def test_cpu_temperature_unknown_chips_return_none(monkeypatch):
    monkeypatch.setattr(ss.psutil, "sensors_temperatures", lambda: {"nvme": [Temp("", 40, 0, 0)]}, raising=False)
    assert ss.get_cpu_temperature() is None

def test_cpu_temperature_unsupported_platform(monkeypatch):
    monkeypatch.delattr(ss.psutil, "sensors_temperatures", raising=False)
    assert ss.get_cpu_temperature() is None

def test_last_boot_is_utc_iso(monkeypatch):
    monkeypatch.setattr(ss.psutil, "boot_time", lambda: 1_700_000_000)
    value = ss.get_last_boot()
    assert value == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc).isoformat()
    assert value.endswith("+00:00")

def test_last_boot_error_returns_none(monkeypatch):
    def boom():
        raise OSError

    monkeypatch.setattr(ss.psutil, "boot_time", boom)
    assert ss.get_last_boot() is None

def test_idle_time_macos_parses_hid_idle_time(monkeypatch):
    set_platform(monkeypatch, "darwin")
    out = '  | |   "HIDIdleTime" = 5000000000\n'
    monkeypatch.setattr(ss, "_run", fake_run(out))
    assert ss.get_idle_time() == 5

def test_idle_time_macos_unparseable_and_missing(monkeypatch):
    set_platform(monkeypatch, "darwin")
    monkeypatch.setattr(ss, "_run", fake_run('"HIDIdleTime" = abc'))
    assert ss.get_idle_time() is None
    monkeypatch.setattr(ss, "_run", fake_run("nothing here"))
    assert ss.get_idle_time() is None
    monkeypatch.setattr(ss, "_run", fake_run(None))
    assert ss.get_idle_time() is None

def test_idle_time_linux_gnome_busctl(monkeypatch):
    set_platform(monkeypatch, "linux")
    run = fake_run("t 7500\n")
    monkeypatch.setattr(ss, "_run", run)
    assert ss.get_idle_time() == 7
    assert run.calls[0][0] == "busctl"

def test_idle_time_linux_falls_back_to_xprintidle(monkeypatch):
    set_platform(monkeypatch, "linux")
    run = fake_run(lambda cmd: "12000\n" if cmd[0] == "xprintidle" else None)
    monkeypatch.setattr(ss, "_run", run)
    assert ss.get_idle_time() == 12
    assert [c[0] for c in run.calls] == ["busctl", "xprintidle"]

def test_idle_time_linux_bad_output_returns_none(monkeypatch):
    set_platform(monkeypatch, "linux")
    monkeypatch.setattr(ss, "_run", fake_run(lambda cmd: "t abc" if cmd[0] == "busctl" else None))
    assert ss.get_idle_time() is None
    monkeypatch.setattr(ss, "_run", fake_run(lambda cmd: None if cmd[0] == "busctl" else "oops"))
    assert ss.get_idle_time() is None
    monkeypatch.setattr(ss, "_run", fake_run(None))
    assert ss.get_idle_time() is None

class FakeUser32:
    def __init__(self, idle_ticks=None, desktop=1, switch=1):
        self.idle_ticks = idle_ticks
        self.desktop = desktop
        self.switch = switch
        self.closed = []

    def GetLastInputInfo(self, ref):
        if self.idle_ticks is None:
            return 0
        ref._obj.dwTime = self.idle_ticks
        return 1

    def OpenInputDesktop(self, *a):
        return self.desktop

    def SwitchDesktop(self, desk):
        return self.switch

    def CloseDesktop(self, desk):
        self.closed.append(desk)

def install_windll(monkeypatch, user32, tick=0):
    kernel32 = types.SimpleNamespace(GetTickCount=lambda: tick)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)

def test_idle_time_windows_computes_seconds(monkeypatch):
    set_platform(monkeypatch, "win32")
    install_windll(monkeypatch, FakeUser32(idle_ticks=1000), tick=6000)
    assert ss.get_idle_time() == 5

def test_idle_time_windows_tick_wraparound(monkeypatch):
    set_platform(monkeypatch, "win32")
    install_windll(monkeypatch, FakeUser32(idle_ticks=0xFFFFFC18), tick=2000)
    assert ss.get_idle_time() == 3

def test_screen_locked_windows_when_desktop_cannot_be_opened(monkeypatch):
    set_platform(monkeypatch, "win32")
    install_windll(monkeypatch, FakeUser32(desktop=0))
    assert ss.get_screen_locked() is True

@pytest.mark.parametrize("switch,expected", [(1, False), (0, True)])
def test_screen_locked_windows_switch_result(monkeypatch, switch, expected):
    set_platform(monkeypatch, "win32")
    user32 = FakeUser32(desktop=7, switch=switch)
    install_windll(monkeypatch, user32)
    assert ss.get_screen_locked() is expected
    assert user32.closed == [7]

@pytest.mark.parametrize("out,expected", [
    ('"CGSSessionScreenIsLocked" = Yes', True),
    ('"CGSSessionScreenIsLocked"=Yes', True),
    ('"OtherKey" = Yes', False),
    (None, None),
])
def test_screen_locked_macos(monkeypatch, out, expected):
    set_platform(monkeypatch, "darwin")
    monkeypatch.setattr(ss, "_run", fake_run(out))
    assert ss.get_screen_locked() is expected

@pytest.mark.parametrize("out,expected", [("yes\n", True), ("no\n", False), (None, None)])
def test_screen_locked_linux(monkeypatch, out, expected):
    set_platform(monkeypatch, "linux")
    monkeypatch.setattr(ss, "_run", fake_run(out))
    assert ss.get_screen_locked() is expected

def test_mic_in_use_macos_is_unsupported(monkeypatch):
    set_platform(monkeypatch, "darwin")
    assert ss.get_mic_in_use() is None
    assert ss.get_camera_in_use() is None

@pytest.mark.parametrize("out,expected", [("12\tsrc\n", True), ("  \n", False), ("", False), (None, None)])
def test_mic_in_use_linux(monkeypatch, out, expected):
    set_platform(monkeypatch, "linux")
    monkeypatch.setattr(ss, "_run", fake_run(out))
    assert ss.get_mic_in_use() is expected

class FakeFs:
    def __init__(self, devices, procs):
        self.devices = devices
        self.procs = procs

    def isdir(self, path):
        return True

    def listdir(self, path):
        if path == "/dev":
            return self.devices
        if path == "/proc":
            return list(self.procs) + ["self", "cpuinfo"]
        pid = path.split("/")[2]
        if pid not in self.procs:
            raise FileNotFoundError(path)
        fds = self.procs[pid]
        if fds is None:
            raise PermissionError(path)
        return list(fds)

    def readlink(self, path):
        parts = path.split("/")
        target = self.procs[parts[2]][parts[4]]
        if target is None:
            raise OSError
        return target

def install_fs(monkeypatch, fs):
    set_platform(monkeypatch, "linux")
    monkeypatch.setattr(ss.os.path, "isdir", fs.isdir)
    monkeypatch.setattr(ss.os, "listdir", fs.listdir)
    monkeypatch.setattr(ss.os, "readlink", fs.readlink)
    monkeypatch.setattr(ss.os, "getpid", lambda: 999)

def test_camera_in_use_detects_video_device_holder(monkeypatch):
    fs = FakeFs(["video0", "tty"], {"100": {"0": "/dev/null"}, "200": {"3": "/dev/video0"}})
    install_fs(monkeypatch, fs)
    assert ss.get_camera_in_use() is True

def test_camera_in_use_false_when_nobody_holds_device(monkeypatch):
    fs = FakeFs(["video0"], {"100": {"0": "/dev/null"}, "300": None, "400": {"1": None}})
    install_fs(monkeypatch, fs)
    assert ss.get_camera_in_use() is False

def test_camera_in_use_none_without_video_devices(monkeypatch):
    install_fs(monkeypatch, FakeFs(["tty0"], {}))
    assert ss.get_camera_in_use() is None

def test_camera_in_use_ignores_own_process(monkeypatch):
    fs = FakeFs(["video0"], {"999": {"3": "/dev/video0"}})
    install_fs(monkeypatch, fs)
    assert ss.get_camera_in_use() is False

class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree):
        self.tree = tree

    class Key:
        def __init__(self, node):
            self.node = node

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, parent, name=None):
        if name is None:
            return parent
        node = parent.node if isinstance(parent, FakeWinreg.Key) else self.tree
        if parent == "HKCU":
            if name not in self.tree:
                raise OSError
            return FakeWinreg.Key(self.tree[name])
        if name not in node["children"]:
            raise OSError
        return FakeWinreg.Key(node["children"][name])

    def EnumKey(self, key, i):
        names = list(key.node["children"])
        if i >= len(names):
            raise OSError
        return names[i]

    def QueryValueEx(self, key, name):
        if name not in key.node["values"]:
            raise OSError
        return (key.node["values"][name], 4)

def leaf(start, stop):
    return {"children": {}, "values": {"LastUsedTimeStart": start, "LastUsedTimeStop": stop}}

def consent_tree(children):
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    return {base: {"children": children, "values": {}}}

def install_winreg(monkeypatch, tree):
    set_platform(monkeypatch, "win32")
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg(tree))

def test_mic_in_use_windows_active_app(monkeypatch):
    install_winreg(monkeypatch, consent_tree({"app_a": leaf(100, 0), "app_b": leaf(100, 200)}))
    assert ss.get_mic_in_use() is True

def test_mic_in_use_windows_finished_apps(monkeypatch):
    install_winreg(monkeypatch, consent_tree({"app_b": leaf(100, 200), "app_c": leaf(0, 0)}))
    assert ss.get_mic_in_use() is False

def test_mic_in_use_windows_nonpackaged_apps_are_scanned(monkeypatch):
    nested = {"children": {"exe": leaf(5, 0)}, "values": {}}
    install_winreg(monkeypatch, consent_tree({"NonPackaged": nested}))
    assert ss.get_mic_in_use() is True

def test_mic_in_use_windows_missing_key(monkeypatch):
    install_winreg(monkeypatch, {})
    assert ss.get_mic_in_use() is None

def test_collect_drops_none_and_raising_collectors(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setitem(ss.COLLECTORS, "battery_level", lambda: 10.0)
    monkeypatch.setitem(ss.COLLECTORS, "battery_charging", lambda: None)
    monkeypatch.setitem(ss.COLLECTORS, "disk_usage", boom)
    result = ss.collect(["battery_level", "battery_charging", "disk_usage", "unknown_id"])
    assert result == {"battery_level": 10.0}

def test_collect_keeps_false_and_zero_values(monkeypatch):
    monkeypatch.setitem(ss.COLLECTORS, "battery_charging", lambda: False)
    monkeypatch.setitem(ss.COLLECTORS, "idle_time", lambda: 0)
    assert ss.collect(["battery_charging", "idle_time"]) == {"battery_charging": False, "idle_time": 0}

def test_enabled_sensor_ids_by_group():
    assert ss.enabled_sensor_ids({}) == set()
    assert ss.enabled_sensor_ids({"send_system": True}) == set(ss.GROUPS["system"])
    assert ss.enabled_sensor_ids({"send_presence": True}) == set(ss.GROUPS["presence"])
    both = ss.enabled_sensor_ids({"send_system": True, "send_presence": True})
    assert both == set(ss.GROUPS["system"]) | set(ss.GROUPS["presence"])

def test_definitions_collectors_and_groups_are_consistent():
    def_ids = {d["unique_id"] for d in ss.SENSOR_DEFS}
    grouped = {i for ids in ss.GROUPS.values() for i in ids}
    assert def_ids == set(ss.COLLECTORS) == grouped
    assert set(ss.FAST_SENSORS) <= def_ids
    assert all(d["state"] is None for d in ss.SENSOR_DEFS)
