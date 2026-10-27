import os
import sys
from pathlib import Path

import certifi
import pytest

from core import utils


@pytest.fixture
def clean_ssl_env(monkeypatch):
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    return monkeypatch


def test_ssl_cert_file_env_var_wins(clean_ssl_env, tmp_path):
    bundle = tmp_path / "custom.pem"
    clean_ssl_env.setenv("SSL_CERT_FILE", str(bundle))
    clean_ssl_env.setattr(utils.platform, "system", lambda: "Linux")
    utils.configure_ssl()
    assert os.environ["SSL_CERT_FILE"] == str(bundle)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(bundle)


def test_linux_prefers_first_existing_system_bundle(clean_ssl_env, tmp_path):
    first = tmp_path / "debian.crt"
    second = tmp_path / "rhel.crt"
    second.write_text("x")
    first.write_text("x")
    clean_ssl_env.setattr(utils, "_LINUX_CA_BUNDLES", [str(tmp_path / "missing.crt"), str(first), str(second)])
    clean_ssl_env.setattr(utils.platform, "system", lambda: "Linux")
    utils.configure_ssl()
    assert os.environ["SSL_CERT_FILE"] == str(first)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(first)


def test_linux_without_system_bundle_falls_back_to_certifi(clean_ssl_env, tmp_path):
    clean_ssl_env.setattr(utils, "_LINUX_CA_BUNDLES", [str(tmp_path / "nope.crt")])
    clean_ssl_env.setattr(utils.platform, "system", lambda: "Linux")
    utils.configure_ssl()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()


@pytest.mark.parametrize("system", ["Darwin", "Windows"])
def test_non_linux_uses_certifi_even_if_system_bundle_exists(clean_ssl_env, tmp_path, system):
    present = tmp_path / "present.crt"
    present.write_text("x")
    clean_ssl_env.setattr(utils, "_LINUX_CA_BUNDLES", [str(present)])
    clean_ssl_env.setattr(utils.platform, "system", lambda: system)
    utils.configure_ssl()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()
    assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()


def test_existing_requests_bundle_is_not_overridden(clean_ssl_env):
    clean_ssl_env.setenv("REQUESTS_CA_BUNDLE", "/corp/ca.pem")
    clean_ssl_env.setattr(utils.platform, "system", lambda: "Darwin")
    utils.configure_ssl()
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/corp/ca.pem"
    assert os.environ["SSL_CERT_FILE"] == certifi.where()


def test_certifi_bundle_exists():
    assert Path(certifi.where()).is_file()


@pytest.mark.parametrize("system,font", [
    ("Windows", "Segoe UI"),
    ("Darwin", "SF Pro Display"),
    ("Linux", "Ubuntu"),
    ("FreeBSD", "Ubuntu"),
])
def test_system_font_per_platform(monkeypatch, system, font):
    monkeypatch.setattr(utils.platform, "system", lambda: system)
    assert utils.get_system_font() == font


def test_resource_path_in_dev_points_into_repo(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    path = utils.get_resource_path("translations/en.json")
    assert path.is_file()
    assert path.parent.name == "translations"


def test_resource_path_uses_pyinstaller_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert utils.get_resource_path("a/b.txt") == tmp_path / "a" / "b.txt"


def test_platform_config_dir_windows_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert utils.get_platform_config_dir() == tmp_path / "PrismDesktop"


def test_platform_config_dir_macos(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Darwin")
    expected = Path.home() / "Library" / "Application Support" / "PrismDesktop"
    assert utils.get_platform_config_dir() == expected


def test_platform_config_dir_linux_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert utils.get_platform_config_dir() == tmp_path / "xdg" / "PrismDesktop"


def test_platform_config_dir_linux_defaults_to_dot_config(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert utils.get_platform_config_dir() == Path.home() / ".config" / "PrismDesktop"


def test_config_path_in_dev_is_repo_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    path = utils.get_config_path("config.json")
    assert path == Path(utils.__file__).parent.parent / "config.json"


def test_config_path_frozen_prefers_portable_file(monkeypatch, tmp_path):
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    (exe_dir / "config.json").write_text("{}")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "prism.exe"))
    assert utils.get_config_path() == exe_dir / "config.json"


def test_config_path_frozen_falls_back_to_platform_dir_and_creates_it(monkeypatch, tmp_path):
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    platform_dir = tmp_path / "platform" / "PrismDesktop"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "prism.exe"))
    monkeypatch.setattr(utils, "get_platform_config_dir", lambda: platform_dir)
    result = utils.get_config_path("x.json")
    assert result == platform_dir / "x.json"
    assert platform_dir.is_dir()
