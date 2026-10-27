import ast
import importlib.util
import json
import plistlib
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["build_macos.py", "build_linux.py", "build_exe.py", "generate_mdi_mapping.py"]


def load_script(filename):
    name = "script_under_test_" + filename[:-3]
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_macos():
    return load_script("build_macos.py")


@pytest.fixture(scope="module")
def build_linux():
    return load_script("build_linux.py")


@pytest.fixture(scope="module")
def build_exe():
    return load_script("build_exe.py")


@pytest.fixture(scope="module")
def mdi():
    return load_script("generate_mdi_mapping.py")


@pytest.fixture
def project(tmp_path):
    (tmp_path / "core").mkdir()
    return tmp_path


def fake_git(outputs):
    def check_output(cmd, **kwargs):
        return outputs[cmd[1]]
    return check_output


def read_generated(project):
    namespace = {}
    exec((project / "core" / "_generated_build_info.py").read_text(), namespace)
    return namespace


@pytest.mark.parametrize("filename", SCRIPTS)
def test_script_parses(filename):
    ast.parse((ROOT / filename).read_text(encoding="utf-8"), filename=filename)


@pytest.mark.parametrize("filename", SCRIPTS)
def test_script_has_no_syntax_issues_when_compiled(filename):
    compile((ROOT / filename).read_text(encoding="utf-8"), filename, "exec")


@pytest.mark.parametrize("module_fixture", ["build_macos", "build_linux", "build_exe"])
def test_write_build_info_records_commit_and_clean_state(module_fixture, request, project, monkeypatch):
    module = request.getfixturevalue(module_fixture)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        fake_git({"rev-parse": "abc123def456\n", "status": ""}),
    )
    module.write_build_info(project)
    values = read_generated(project)
    assert values["BUILD_COMMIT"] == "abc123def456"
    assert values["BUILD_DIRTY"] is False


@pytest.mark.parametrize("module_fixture", ["build_macos", "build_linux", "build_exe"])
def test_write_build_info_marks_dirty_tree(module_fixture, request, project, monkeypatch):
    module = request.getfixturevalue(module_fixture)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        fake_git({"rev-parse": "abc123def456\n", "status": " M file.py\n"}),
    )
    module.write_build_info(project)
    assert read_generated(project)["BUILD_DIRTY"] is True


@pytest.mark.parametrize("error", [FileNotFoundError("git"), subprocess.CalledProcessError(128, "git")])
@pytest.mark.parametrize("module_fixture", ["build_macos", "build_linux", "build_exe"])
def test_write_build_info_without_git_writes_empty_values(module_fixture, error, request, project, monkeypatch):
    module = request.getfixturevalue(module_fixture)

    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(module.subprocess, "check_output", boom)
    module.write_build_info(project)
    values = read_generated(project)
    assert values["BUILD_COMMIT"] == ""
    assert values["BUILD_DIRTY"] is False


def test_write_build_info_output_is_not_code_injectable(build_linux, project, monkeypatch):
    payload = "x'\nimport os; os.system('true')\n'"
    monkeypatch.setattr(
        build_linux.subprocess,
        "check_output",
        fake_git({"rev-parse": payload, "status": ""}),
    )
    build_linux.write_build_info(project)
    tree = ast.parse((project / "core" / "_generated_build_info.py").read_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom, ast.Call))]
    assert read_generated(project)["BUILD_COMMIT"] == payload.strip()


@pytest.mark.parametrize(
    "machine,expected",
    [("x86_64", "x86_64"), ("AMD64", "x86_64"), ("aarch64", "aarch64"), ("arm64", "aarch64"), ("riscv64", "riscv64")],
)
def test_get_arch_normalizes_machine_names(build_linux, monkeypatch, machine, expected):
    monkeypatch.setattr(build_linux.platform, "machine", lambda: machine)
    assert build_linux.get_arch() == expected


def test_find_appimagetool_prefers_path_lookup(build_linux, monkeypatch):
    monkeypatch.setattr(build_linux.shutil, "which", lambda name: "/opt/bin/appimagetool")
    assert build_linux.find_appimagetool("x86_64") == "/opt/bin/appimagetool"


def test_find_appimagetool_returns_none_when_missing(build_linux, monkeypatch, tmp_path):
    monkeypatch.setattr(build_linux.shutil, "which", lambda name: None)
    monkeypatch.setattr(build_linux, "__file__", str(tmp_path / "build_linux.py"))
    assert build_linux.find_appimagetool("x86_64") is None


def test_find_appimagetool_uses_local_file_and_makes_it_executable(build_linux, monkeypatch, tmp_path):
    tool = tmp_path / "appimagetool-aarch64.AppImage"
    tool.write_text("binary")
    tool.chmod(0o644)
    monkeypatch.setattr(build_linux.shutil, "which", lambda name: None)
    monkeypatch.setattr(build_linux, "__file__", str(tmp_path / "build_linux.py"))
    found = build_linux.find_appimagetool("aarch64")
    assert Path(found) == tool
    assert tool.stat().st_mode & 0o111


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Architectures in the fat file: x86_64 arm64", True),
        ("Architectures in the fat file: x86_64 arm64e", True),
        ("Non-fat file: python is architecture: arm64", False),
        ("Non-fat file: python is architecture: x86_64", False),
    ],
)
def test_is_python_universal_reads_lipo_output(build_macos, monkeypatch, output, expected):
    monkeypatch.setattr(build_macos.subprocess, "check_output", lambda *a, **k: output)
    assert build_macos.is_python_universal(Path("/x/python")) is expected


def test_is_python_universal_false_when_lipo_fails(build_macos, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("lipo")

    monkeypatch.setattr(build_macos.subprocess, "check_output", boom)
    assert build_macos.is_python_universal(Path("/x/python")) is False


def test_customize_info_plist_sets_agent_app_metadata(build_macos, tmp_path):
    bundle = tmp_path / "Prism Desktop.app"
    (bundle / "Contents").mkdir(parents=True)
    with open(bundle / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleName": "old"}, f)
    build_macos.customize_info_plist(bundle)
    with open(bundle / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)
    assert plist["CFBundleName"] == "Prism Desktop"
    assert plist["CFBundleShortVersionString"] == build_macos.APP_VERSION
    assert plist["CFBundleIdentifier"] == "io.prism.desktop"
    assert plist["LSUIElement"] is True
    assert plist["NSHighResolutionCapable"] is True


def test_customize_info_plist_ignores_missing_plist(build_macos, tmp_path):
    bundle = tmp_path / "Missing.app"
    bundle.mkdir()
    build_macos.customize_info_plist(bundle)
    assert not (bundle / "Contents").exists()


def test_customize_info_plist_survives_corrupt_plist(build_macos, tmp_path):
    bundle = tmp_path / "Broken.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(b"not a plist")
    build_macos.customize_info_plist(bundle)
    assert (bundle / "Contents" / "Info.plist").read_bytes() == b"not a plist"


def test_ad_hoc_codesign_signs_then_verifies(build_macos, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(build_macos.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert build_macos.ad_hoc_codesign(tmp_path / "A.app") is True
    assert calls[0][:5] == ["codesign", "--force", "--deep", "--sign", "-"]
    assert calls[1][:2] == ["codesign", "--verify"]


def test_ad_hoc_codesign_reports_failure(build_macos, monkeypatch, tmp_path):
    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"bad")

    monkeypatch.setattr(build_macos.subprocess, "run", boom)
    assert build_macos.ad_hoc_codesign(tmp_path / "A.app") is False


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip utility not installed")
def test_create_zip_archive_contains_bundle_files(build_macos, tmp_path):
    bundle = tmp_path / "Prism Desktop.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "marker.txt").write_text("hello")
    out = tmp_path / "out.zip"
    assert build_macos.create_zip_archive(bundle, out) is True
    import zipfile
    with zipfile.ZipFile(out) as z:
        assert "Prism Desktop.app/Contents/marker.txt" in z.namelist()


def test_create_zip_archive_replaces_existing_and_reports_failure(build_macos, monkeypatch, tmp_path):
    out = tmp_path / "out.zip"
    out.write_text("stale")

    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "zip")

    monkeypatch.setattr(build_macos.subprocess, "run", boom)
    assert build_macos.create_zip_archive(tmp_path / "A.app", out) is False
    assert not out.exists()


def test_create_dmg_package_skips_without_hdiutil(build_macos, monkeypatch, tmp_path):
    monkeypatch.setattr(build_macos.shutil, "which", lambda name: None)
    assert build_macos.create_dmg_package(tmp_path / "A.app", tmp_path / "A.dmg") is False


def test_generate_icns_returns_png_fallback_when_tools_missing(build_macos, monkeypatch, tmp_path):
    (tmp_path / "icon.png").write_bytes(b"png")

    def boom(*args, **kwargs):
        raise FileNotFoundError("sips")

    monkeypatch.setattr(build_macos.subprocess, "run", boom)
    assert build_macos.generate_icns_if_needed(tmp_path) == tmp_path / "icon.png"
    assert not (tmp_path / "icon.iconset").exists()


def test_generate_icns_returns_existing_up_to_date_icns(build_macos, tmp_path):
    (tmp_path / "icon.png").write_bytes(b"png")
    (tmp_path / "icon.icns").write_bytes(b"icns")
    assert build_macos.generate_icns_if_needed(tmp_path) == tmp_path / "icon.icns"


def test_generate_icns_without_png_returns_icns_path(build_macos, tmp_path):
    assert build_macos.generate_icns_if_needed(tmp_path) == tmp_path / "icon.icns"


def test_mdi_mapping_json_is_valid_and_non_empty():
    data = json.loads((ROOT / "mdi_mapping.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) > 1000


def test_mdi_mapping_values_are_single_codepoints_with_known_icons():
    data = json.loads((ROOT / "mdi_mapping.json").read_text(encoding="utf-8"))
    assert all(isinstance(k, str) and k and len(v) == 1 for k, v in data.items())
    assert {"home", "lightbulb", "thermometer"} <= set(data)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


CSS = (
    '.mdi-home::before { content: "\\F02DC"; }\n'
    '.mdi-ab-testing:before{content:"\\f01C9"}\n'
    '.mdi-bad::before { content: "nothex" }\n'
)


def test_generate_skips_when_output_exists(mdi, monkeypatch, tmp_path):
    out = tmp_path / "mdi_mapping.json"
    out.write_text("{}")
    monkeypatch.setattr(mdi, "OUTPUT", out)

    def fail(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(mdi.urllib.request, "urlopen", fail)
    assert mdi.generate() is True
    assert out.read_text() == "{}"


def test_generate_parses_css_into_mapping(mdi, monkeypatch, tmp_path):
    out = tmp_path / "mdi_mapping.json"
    monkeypatch.setattr(mdi, "OUTPUT", out)
    monkeypatch.setattr(mdi.urllib.request, "urlopen", lambda *a, **k: FakeResponse(CSS))
    assert mdi.generate(force=True) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"home": chr(0xF02DC), "ab-testing": chr(0xF01C9)}


def test_generate_returns_false_on_network_error(mdi, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mdi, "OUTPUT", tmp_path / "mdi_mapping.json")

    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(mdi.urllib.request, "urlopen", boom)
    assert mdi.generate(force=True) is False
    assert not (tmp_path / "mdi_mapping.json").exists()
    assert "offline" in capsys.readouterr().err


def test_generate_uses_https_url(mdi):
    assert mdi.MDI_CSS_URL.startswith("https://")


@pytest.mark.xfail(
    strict=True,
    reason="generate() downloads with ssl._create_unverified_context(), so TLS certificates are not verified",
)
def test_generate_downloads_with_certificate_verification(mdi, monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(url, context=None, timeout=None):
        captured["context"] = context
        return FakeResponse(CSS)

    monkeypatch.setattr(mdi, "OUTPUT", tmp_path / "mdi_mapping.json")
    monkeypatch.setattr(mdi.urllib.request, "urlopen", fake_urlopen)
    mdi.generate(force=True)
    context = captured["context"]
    assert context is None or (
        context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    )
