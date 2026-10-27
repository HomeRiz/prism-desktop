import ast
import sys
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
APP_DIRS = ["core", "services", "ui"]

IMPORT_TO_DIST = {
    "PyQt6": "PyQt6",
    "PIL": "Pillow",
    "yarl": "yarl",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "certifi": "certifi",
    "cryptography": "cryptography",
    "keyring": "keyring",
    "psutil": "psutil",
    "pynput": "pynput",
    "pystray": "pystray",
    "qasync": "qasync",
    "dbus_next": "dbus-next",
    "secretstorage": "secretstorage",
    "win11toast": "win11toast",
    "winrt": "winrt-runtime",
    "CoreFoundation": "pyobjc-framework-Cocoa",
    "ApplicationServices": "pyobjc-framework-ApplicationServices",
}

LOCAL_PACKAGES = {"core", "services", "ui", "main", "generate_mdi_mapping"}


def requirement_lines(path):
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #")[0].strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def parse_requirements():
    return [Requirement(line) for line in requirement_lines(ROOT / "requirements.txt")]


def applies(req):
    return req.marker is None or req.marker.evaluate()


def source_files():
    files = [ROOT / "main.py"]
    for name in APP_DIRS:
        files.extend(sorted((ROOT / name).rglob("*.py")))
    return files


def imported_top_levels():
    found = {}
    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


def transitive_dists(roots):
    seen = set()
    stack = [canonicalize_name(r) for r in roots]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for text in requires:
            req = Requirement(text)
            if req.marker is not None and not any(
                req.marker.evaluate({"extra": "", "sys_platform": plat, "platform_system": system})
                for plat, system in (("darwin", "Darwin"), ("linux", "Linux"), ("win32", "Windows"))
            ):
                continue
            stack.append(canonicalize_name(req.name))
    return seen


def test_requirements_file_is_not_empty():
    assert len(parse_requirements()) >= 10


def test_every_line_is_a_valid_pep508_requirement():
    for line in requirement_lines(ROOT / "requirements.txt"):
        try:
            Requirement(line)
        except InvalidRequirement as exc:
            pytest.fail(f"invalid requirement {line!r}: {exc}")


def test_every_requirement_declares_a_minimum_version():
    for req in parse_requirements():
        assert any(spec.operator in (">=", "==", "~=", ">") for spec in req.specifier), req.name


def test_no_duplicate_packages_per_marker_environment():
    seen = {}
    for req in parse_requirements():
        key = canonicalize_name(req.name)
        marker = str(req.marker) if req.marker else ""
        assert (key, marker) not in seen, f"duplicate requirement for {req.name}"
        seen[(key, marker)] = req
    unconditional = [canonicalize_name(r.name) for r in parse_requirements() if r.marker is None]
    assert len(unconditional) == len(set(unconditional))


def test_platform_markers_use_known_variables_and_evaluate():
    for req in parse_requirements():
        if req.marker is not None:
            assert isinstance(req.marker.evaluate(), bool)
            assert "sys_platform" in str(req.marker)


def test_installed_versions_satisfy_every_applicable_floor():
    checked = 0
    for req in parse_requirements():
        if not applies(req):
            continue
        try:
            installed = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            if canonicalize_name(req.name) in {"keyring", "secretstorage", "dbus-next"}:
                continue
            pytest.fail(f"{req.name} is required on this platform but not installed")
        assert req.specifier.contains(installed, prereleases=True), f"{req.name} {installed}"
        checked += 1
    assert checked >= 8


def test_required_packages_that_are_missing_are_platform_specific_only():
    missing = []
    for req in parse_requirements():
        if applies(req):
            try:
                metadata.version(req.name)
            except metadata.PackageNotFoundError:
                missing.append(canonicalize_name(req.name))
    assert set(missing) <= {"keyring", "secretstorage", "dbus-next"}


def test_every_third_party_import_maps_to_a_known_distribution():
    stdlib = set(sys.stdlib_module_names)
    third_party = {
        name for name in imported_top_levels()
        if name not in stdlib and name not in LOCAL_PACKAGES and not name.startswith("_")
    }
    assert third_party
    unknown = sorted(third_party - set(IMPORT_TO_DIST))
    assert not unknown, f"third party imports without a distribution mapping: {unknown}"


def test_every_third_party_import_is_covered_by_requirements_txt():
    stdlib = set(sys.stdlib_module_names)
    direct = {canonicalize_name(r.name) for r in parse_requirements()}
    covered = transitive_dists(direct)
    missing = {}
    for name, files in imported_top_levels().items():
        if name in stdlib or name in LOCAL_PACKAGES or name.startswith("_"):
            continue
        if name in {"CoreFoundation", "ApplicationServices"} and sys.platform != "darwin":
            continue
        dist = canonicalize_name(IMPORT_TO_DIST.get(name, name))
        if dist not in covered:
            missing[name] = sorted(files)
    assert not missing, f"imports not covered by requirements.txt: {missing}"


def test_yarl_import_is_provided_transitively_by_aiohttp():
    direct = {canonicalize_name(r.name) for r in parse_requirements()}
    assert "yarl" not in direct
    assert "yarl" in transitive_dists({"aiohttp"})


def test_requirements_dev_includes_runtime_requirements():
    lines = requirement_lines(ROOT / "requirements-dev.txt")
    assert "-r requirements.txt" in lines
    dev = [Requirement(line) for line in lines if not line.startswith("-")]
    names = {canonicalize_name(r.name) for r in dev}
    assert {"pytest", "pytest-asyncio", "pytest-qt", "pytest-aiohttp", "pytest-cov"} <= names
