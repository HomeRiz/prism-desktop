import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["core", "services", "ui"]

NEEDS_MODULE = {
    "services.dbus_notifier": "dbus_next",
    "services.wayland_global_shortcut": "dbus_next",
}

DRIVER = """
import importlib
import importlib.util
import json
import sys
import traceback

results = {}
for name in sys.argv[1:]:
    try:
        if name == "main":
            spec = importlib.util.spec_from_file_location("prism_main_under_test", "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            importlib.import_module(name)
        results[name] = None
    except BaseException:
        results[name] = traceback.format_exc()
print("RESULTS:" + json.dumps(results))
"""


def discover_modules():
    names = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            rel = path.relative_to(ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.append(".".join(parts))
    return names


MODULES = discover_modules() + ["main"]


def skip_reason(name):
    needed = NEEDS_MODULE.get(name)
    if needed and importlib.util.find_spec(needed) is None:
        return f"{needed} is not installed on this platform"
    return None


@pytest.fixture(scope="module")
def import_results(tmp_path_factory):
    home = tmp_path_factory.mktemp("import_home")
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home / "AppData"),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        QT_QPA_PLATFORM="offscreen",
        PYTHONDONTWRITEBYTECODE="1",
    )
    runnable = [m for m in MODULES if skip_reason(m) is None]
    proc = subprocess.run(
        [sys.executable, "-c", DRIVER, *runnable],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULTS:")), None)
    assert line is not None, f"import driver crashed: rc={proc.returncode}\n{proc.stderr[-2000:]}"
    return json.loads(line[len("RESULTS:"):])


def test_discovery_finds_each_package_and_main():
    assert "main" in MODULES
    for package in PACKAGES:
        assert any(m == package or m.startswith(package + ".") for m in MODULES)
    assert len(MODULES) > 40


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_cleanly(name, import_results):
    reason = skip_reason(name)
    if reason:
        pytest.skip(reason)
    assert import_results[name] is None, import_results[name]


def test_importing_main_does_not_start_the_application(import_results):
    assert import_results["main"] is None


def test_every_python_file_compiles():
    for path in ROOT.glob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for package in PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_every_package_directory_with_modules_is_importable_as_a_package():
    for package in PACKAGES:
        assert (ROOT / package / "__init__.py").exists()
