import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from services import auto_updater as au

ASSET = "PrismDesktop-x86_64.AppImage"
PAYLOAD = b"new-binary-content" * 100


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch, qapp):
    work = tmp_path / "tmp"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))
    monkeypatch.setattr(au, "_update_in_progress", False)
    forbidden = mock.Mock(side_effect=AssertionError("process launch outside test control"))
    monkeypatch.setattr(au.subprocess, "Popen", forbidden)
    monkeypatch.setattr(au.subprocess, "run", forbidden)
    monkeypatch.setattr(au.QApplication, "quit", mock.Mock())
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "unused.AppImage"))
    return work


@pytest.fixture
def thread(signal_log):
    t = au.AutoUpdateThread()
    t.log = signal_log(progress=t.progress, success=t.success, error=t.error)
    return t


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def release(http_stub, monkeypatch):
    def publish(assets=None, payload=PAYLOAD, sums=None):
        items = [{"name": ASSET, "size": len(payload), "browser_download_url": f"{http_stub.base}/dl/asset"}]
        http_stub.route("/dl/asset", payload)
        if sums is not None:
            items.append({"name": "SHA256SUMS", "browser_download_url": f"{http_stub.base}/dl/sums"})
            http_stub.route("/dl/sums", sums)
        http_stub.route("/latest", {"assets": assets if assets is not None else items})

    monkeypatch.setattr(au, "_API_LATEST", f"{http_stub.base}/latest")
    monkeypatch.setattr(au, "_platform_asset_name", lambda: ASSET)
    return publish


@pytest.mark.parametrize("platform_name,machine,expected", [
    ("win32", "AMD64", "PrismDesktopSetup.exe"),
    ("linux", "x86_64", "PrismDesktop-x86_64.AppImage"),
    ("linux", "aarch64", "PrismDesktop-aarch64.AppImage"),
    ("linux", "ARM64", "PrismDesktop-aarch64.AppImage"),
    ("darwin", "arm64", "PrismDesktop-macOS-arm64.zip"),
    ("darwin", "x86_64", "PrismDesktop-macOS-x86_64.zip"),
    ("freebsd13", "amd64", None),
])
def test_platform_asset_name(monkeypatch, platform_name, machine, expected):
    monkeypatch.setattr(au.sys, "platform", platform_name)
    monkeypatch.setattr(au.platform, "machine", lambda: machine)
    assert au._platform_asset_name() == expected


def test_run_refuses_second_concurrent_update(thread, monkeypatch):
    monkeypatch.setattr(au, "_update_in_progress", True)
    thread.run()
    assert thread.log["error"] == ["An update is already in progress."]


def test_run_dispatches_by_frozen_flag_and_releases_lock(thread, monkeypatch):
    source, frozen = mock.Mock(), mock.Mock()
    monkeypatch.setattr(thread, "_source_update", source)
    monkeypatch.setattr(thread, "_frozen_update", frozen)
    thread.run()
    source.assert_called_once()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    thread.run()
    frozen.assert_called_once()
    assert au._update_in_progress is False


def completed(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


def test_source_update_already_up_to_date(thread, monkeypatch):
    monkeypatch.setattr(thread, "_run_cmd", mock.Mock(return_value=completed(out="Already up to date.\n")))
    thread._source_update()
    assert thread.log["success"] == ["already_up_to_date"]


def test_source_update_pulls_then_reinstalls_requirements(thread, monkeypatch):
    run_cmd = mock.Mock(return_value=completed(out="Updating abc..def"))
    monkeypatch.setattr(thread, "_run_cmd", run_cmd)
    thread._source_update()
    assert run_cmd.call_args_list[0].args[0] == ["git", "pull", "--ff-only"]
    pip = run_cmd.call_args_list[1].args[0]
    assert pip[:4] == [sys.executable, "-m", "pip", "install"] and pip[-1] == "--quiet"
    assert thread.log["success"] == ["updated"]


@pytest.mark.parametrize("result,message", [
    (completed(1, "", "fatal: not a fast-forward"), "fatal: not a fast-forward"),
    (completed(1, "stdout msg", ""), "stdout msg"),
    (completed(1, "", ""), "git pull failed."),
])
def test_source_update_git_failure(thread, monkeypatch, result, message):
    monkeypatch.setattr(thread, "_run_cmd", mock.Mock(return_value=result))
    thread._source_update()
    assert thread.log["error"] == [message] and thread.log["success"] == []


@pytest.mark.parametrize("exc,fragment", [
    (subprocess.TimeoutExpired("git", 1), "timed out"),
    (FileNotFoundError(), "git is not available"),
    (RuntimeError("weird"), "weird"),
])
def test_source_update_error_mapping(thread, monkeypatch, exc, fragment):
    monkeypatch.setattr(thread, "_run_cmd", mock.Mock(side_effect=exc))
    thread._source_update()
    assert fragment in thread.log["error"][0]


def frozen(thread, monkeypatch):
    apply = mock.Mock()
    monkeypatch.setattr(thread, "_apply_frozen", apply)
    return apply


def test_frozen_update_downloads_verifies_and_applies(thread, monkeypatch, release, sandbox):
    sums = f"{sha(PAYLOAD)}  {ASSET}\n{'0' * 64}  other.zip\n"
    release(sums=sums)
    apply = frozen(thread, monkeypatch)
    thread._frozen_update()
    applied = apply.call_args.args[0]
    assert applied.name == ASSET and Path(applied).parent.parent == sandbox
    assert thread.log["success"] == ["updated"] and thread.log["error"] == []
    assert any(m.endswith("100%") for m in thread.log["progress"])
    assert list(sandbox.iterdir()) == []


def test_frozen_update_applies_exact_downloaded_bytes(thread, monkeypatch, release):
    release()
    captured = {}
    monkeypatch.setattr(thread, "_apply_frozen", lambda p: captured.update(data=Path(p).read_bytes()))
    thread._frozen_update()
    assert captured["data"] == PAYLOAD


def test_frozen_update_checksum_mismatch_aborts_and_cleans(thread, monkeypatch, release, sandbox):
    release(sums=f"{'f' * 64}  {ASSET}\n")
    apply = frozen(thread, monkeypatch)
    thread._frozen_update()
    apply.assert_not_called()
    assert "Checksum mismatch" in thread.log["error"][0]
    assert thread.log["success"] == [] and list(sandbox.iterdir()) == []


def test_frozen_update_missing_asset(thread, monkeypatch, release, sandbox):
    release(assets=[{"name": "other.zip", "browser_download_url": "http://127.0.0.1:1/x"}])
    apply = frozen(thread, monkeypatch)
    thread._frozen_update()
    apply.assert_not_called()
    assert ASSET in thread.log["error"][0] and list(sandbox.iterdir()) == []


def test_frozen_update_http_errors_reported(thread, monkeypatch, release, http_stub, sandbox):
    release()
    http_stub.route("/latest", {"message": "no"}, status=500)
    apply = frozen(thread, monkeypatch)
    thread._frozen_update()
    apply.assert_not_called()
    assert thread.log["error"][0].startswith("Download failed")
    assert list(sandbox.iterdir()) == []


def test_frozen_update_apply_failure_reported_and_cleaned(thread, monkeypatch, release, sandbox):
    release()
    monkeypatch.setattr(thread, "_apply_frozen", mock.Mock(side_effect=OSError("read-only")))
    thread._frozen_update()
    assert thread.log["error"] == ["Could not apply update: read-only"]
    assert list(sandbox.iterdir()) == []


def test_frozen_update_keeps_installer_on_windows_after_apply(thread, monkeypatch, release, sandbox):
    release()
    monkeypatch.setattr(au.sys, "platform", "win32")
    frozen(thread, monkeypatch)
    thread._frozen_update()
    assert [p.name for p in sandbox.iterdir() if p.name.startswith("prism_update_")]
    assert thread.log["success"] == ["updated"]


def test_checksum_without_sums_asset_passes(thread, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"x")
    assert thread._verify_checksum(f, ASSET, [{"name": ASSET}]) is True


@pytest.mark.parametrize("line_fmt", ["{h}  {n}", "{h} *{n}", "{H}  {n}"])
def test_checksum_accepts_common_sum_formats(thread, http_stub, tmp_path, line_fmt):
    f = tmp_path / "a"
    f.write_bytes(b"data")
    h = sha(b"data")
    http_stub.route("/sums", line_fmt.format(h=h, H=h.upper(), n=ASSET) + "\n")
    assets = [{"name": "sha256sums.txt", "browser_download_url": f"{http_stub.base}/sums"}]
    assert thread._verify_checksum(f, ASSET, assets) is True


def test_checksum_rejects_wrong_hash(thread, http_stub, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"data")
    http_stub.route("/sums", f"{sha(b'other')}  {ASSET}\n")
    assets = [{"name": "SHA256SUMS", "browser_download_url": f"{http_stub.base}/sums"}]
    assert thread._verify_checksum(f, ASSET, assets) is False


@pytest.mark.xfail(strict=True, reason="a checksum file that does not list the asset is accepted instead of rejected")
def test_checksum_rejects_sums_file_missing_the_asset(thread, http_stub, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"data")
    http_stub.route("/sums", f"{sha(b'data')}  unrelated.zip\n")
    assets = [{"name": "SHA256SUMS", "browser_download_url": f"{http_stub.base}/sums"}]
    assert thread._verify_checksum(f, ASSET, assets) is False


def test_apply_windows_launches_silent_installer_only(thread, monkeypatch, tmp_path):
    popen = mock.Mock(return_value=mock.Mock(pid=1))
    monkeypatch.setattr(au.subprocess, "Popen", popen)
    monkeypatch.setattr(au.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    thread._apply_windows(tmp_path / "Setup.exe")
    assert popen.call_args.args[0] == [str(tmp_path / "Setup.exe"), "/VERYSILENT", "/NORESTART", "/NOCANCEL"]
    assert "shell" not in popen.call_args.kwargs


def test_apply_linux_replaces_target_atomically(thread, tmp_path, monkeypatch):
    target = tmp_path / "bin" / "Prism.AppImage"
    target.parent.mkdir()
    target.write_bytes(b"old")
    download = tmp_path / "dl.AppImage"
    download.write_bytes(b"new")
    monkeypatch.setenv("APPIMAGE", str(target))
    thread._apply_linux(download)
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert sorted(p.name for p in target.parent.iterdir()) == ["Prism.AppImage"]
    assert download.read_bytes() == b"new"


def test_apply_linux_permission_error_leaves_old_file_and_no_staging(thread, tmp_path, monkeypatch):
    target = tmp_path / "Prism.AppImage"
    target.write_bytes(b"old")
    download = tmp_path / "dl"
    download.write_bytes(b"new")
    monkeypatch.setenv("APPIMAGE", str(target))
    monkeypatch.setattr(au.os, "replace", mock.Mock(side_effect=PermissionError))
    with pytest.raises(OSError, match="Cannot replace"):
        thread._apply_linux(download)
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".new")] == []


@pytest.fixture
def mac_env(tmp_path, monkeypatch):
    app = tmp_path / "Apps" / "PrismDesktop.app"
    exe = app / "Contents" / "MacOS" / "prism"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"old")
    monkeypatch.setattr(au.sys, "executable", str(exe))
    monkeypatch.setattr(au.subprocess, "run", mock.Mock(side_effect=OSError("no ditto")))
    return app


def make_zip(base, members):
    path = base / "up" / "u.zip"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_apply_macos_replaces_bundle_and_removes_backup(thread, tmp_path, mac_env):
    archive = make_zip(tmp_path, {"PrismDesktop.app/Contents/MacOS/prism": b"new"})
    thread._apply_macos(archive)
    assert (mac_env / "Contents" / "MacOS" / "prism").read_bytes() == b"new"
    assert not (mac_env.parent / "PrismDesktop.app.old").exists()


def test_apply_macos_zip_traversal_cannot_escape_extract_dir(thread, tmp_path, mac_env):
    archive = make_zip(tmp_path, {
        "PrismDesktop.app/Contents/MacOS/prism": b"new",
        "../../escaped.txt": b"evil",
    })
    thread._apply_macos(archive)
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_apply_macos_archive_without_app_leaves_install_untouched(thread, tmp_path, mac_env):
    archive = make_zip(tmp_path, {"readme.txt": b"hi"})
    with pytest.raises(OSError, match="did not contain"):
        thread._apply_macos(archive)
    assert (mac_env / "Contents" / "MacOS" / "prism").read_bytes() == b"old"


def test_apply_macos_rolls_back_when_second_move_fails(thread, tmp_path, mac_env, monkeypatch):
    archive = make_zip(tmp_path, {"PrismDesktop.app/Contents/MacOS/prism": b"new"})
    real_move = au.shutil.move
    calls = []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("disk full")
        return real_move(src, dst)

    monkeypatch.setattr(au.shutil, "move", flaky)
    with pytest.raises(OSError, match="previous version has been restored"):
        thread._apply_macos(archive)
    assert (mac_env / "Contents" / "MacOS" / "prism").read_bytes() == b"old"


def test_apply_macos_reports_backup_location_when_rollback_fails(thread, tmp_path, mac_env, monkeypatch):
    archive = make_zip(tmp_path, {"PrismDesktop.app/Contents/MacOS/prism": b"new"})
    real_move = au.shutil.move
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) >= 2:
            raise OSError("fail")
        return real_move(src, dst)

    monkeypatch.setattr(au.shutil, "move", flaky)
    with pytest.raises(OSError, match="PrismDesktop.app.old"):
        thread._apply_macos(archive)


def test_update_flag_round_trip_and_consumption(sandbox):
    assert au.consume_update_flag() is None
    au.write_update_flag()
    assert (sandbox / "prism_desktop_just_updated").read_text() == au.APP_VERSION
    assert au.consume_update_flag() == au.APP_VERSION
    assert au.consume_update_flag() is None


@pytest.mark.parametrize("is_frozen,plat,expected", [
    (False, "linux", [sys.executable] + sys.argv),
    (True, "linux", ["/tmp/new.AppImage"]),
])
def test_restart_app_launch_command(monkeypatch, sandbox, is_frozen, plat, expected):
    popen = mock.Mock()
    monkeypatch.setattr(au.subprocess, "Popen", popen)
    monkeypatch.setattr(au.sys, "platform", plat)
    monkeypatch.setattr(au.sys, "frozen", is_frozen, raising=False)
    monkeypatch.setenv("APPIMAGE", "/tmp/new.AppImage")
    au.restart_app()
    assert popen.call_args.args[0] == expected
    au.QApplication.quit.assert_called_once()
    assert (sandbox / "prism_desktop_just_updated").exists()


def test_restart_app_windows_does_not_launch_second_instance(monkeypatch, sandbox):
    popen = mock.Mock()
    monkeypatch.setattr(au.subprocess, "Popen", popen)
    monkeypatch.setattr(au.sys, "platform", "win32")
    monkeypatch.setattr(au.sys, "frozen", True, raising=False)
    au.restart_app()
    popen.assert_not_called()
    au.QApplication.quit.assert_called_once()


def test_restart_app_macos_opens_bundle(monkeypatch, sandbox, tmp_path):
    popen = mock.Mock()
    monkeypatch.setattr(au.subprocess, "Popen", popen)
    monkeypatch.setattr(au.sys, "platform", "darwin")
    monkeypatch.setattr(au.sys, "frozen", True, raising=False)
    monkeypatch.setattr(au.sys, "executable", str(tmp_path / "P.app" / "Contents" / "MacOS" / "p"))
    au.restart_app()
    assert popen.call_args.args[0] == ["open", "-n", str(tmp_path / "P.app")]
