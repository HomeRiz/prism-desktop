import subprocess
import sys

import pytest

from core import build_info as bi


@pytest.fixture
def no_embedded(monkeypatch):
    monkeypatch.setattr(bi, "BUILD_COMMIT", "")
    monkeypatch.setattr(bi, "BUILD_DIRTY", False)


def test_app_version_is_set():
    assert bi.APP_VERSION and bi.APP_VERSION[0].isdigit()


def test_embedded_commit_takes_precedence(monkeypatch):
    monkeypatch.setattr(bi, "BUILD_COMMIT", "abc123")
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: pytest.fail("git must not run"))
    assert bi.get_build_commit() == "abc123"


def test_embedded_dirty_flag_is_reported(monkeypatch):
    monkeypatch.setattr(bi, "BUILD_COMMIT", "abc123")
    monkeypatch.setattr(bi, "BUILD_DIRTY", True)
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: pytest.fail("git must not run"))
    assert bi.is_dirty_build() is True


def test_commit_comes_from_git_when_not_embedded(no_embedded, monkeypatch):
    seen = []
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: seen.append(a) or "deadbeef")
    assert bi.get_build_commit() == "deadbeef"
    assert seen == [("rev-parse", f"--short={bi.SHORT_COMMIT_LENGTH}", "HEAD")]


def test_dirty_when_git_status_has_output(no_embedded, monkeypatch):
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: " M file.py")
    assert bi.is_dirty_build() is True


def test_clean_when_git_status_is_empty(no_embedded, monkeypatch):
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: "")
    assert bi.is_dirty_build() is False


def test_display_version_without_commit(no_embedded, monkeypatch):
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: "")
    assert bi.get_display_version() == bi.APP_VERSION


def test_display_version_with_commit(no_embedded, monkeypatch):
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: "" if a[0] == "status" else "abc")
    assert bi.get_display_version() == f"{bi.APP_VERSION} (abc)"


def test_display_version_marks_dirty_builds(no_embedded, monkeypatch):
    monkeypatch.setattr(bi, "_run_git_command", lambda *a: "abc" if a[0] == "rev-parse" else " M x")
    assert bi.get_display_version() == f"{bi.APP_VERSION} (abc, dirty)"


def test_display_version_uses_embedded_metadata(monkeypatch):
    monkeypatch.setattr(bi, "BUILD_COMMIT", "feed")
    monkeypatch.setattr(bi, "BUILD_DIRTY", True)
    assert bi.get_display_version() == f"{bi.APP_VERSION} (feed, dirty)"


def test_git_is_skipped_in_frozen_builds(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: pytest.fail("git must not run"))
    assert bi._run_git_command("status") == ""


def test_git_output_is_stripped(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "  out\n")
    assert bi._run_git_command("status") == "out"


@pytest.mark.parametrize("error", [
    FileNotFoundError(),
    subprocess.CalledProcessError(1, "git"),
    OSError("denied"),
])
def test_git_failures_yield_empty_string(monkeypatch, error):
    monkeypatch.delattr(sys, "frozen", raising=False)

    def boom(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "check_output", boom)
    assert bi._run_git_command("status") == ""


def test_git_runs_in_repo_root_without_shell(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    captured = {}

    def fake(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return ""

    monkeypatch.setattr(subprocess, "check_output", fake)
    bi._run_git_command("log")
    assert captured["cmd"] == ["git", "log"]
    assert captured["kwargs"]["cwd"] == bi.REPO_ROOT
    assert "shell" not in captured["kwargs"]
