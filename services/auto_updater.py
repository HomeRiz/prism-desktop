"""
Auto-update: pull latest changes from the git remote and restart.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.build_info import REPO_ROOT, APP_VERSION


class AutoUpdateThread(QThread):
    """Pulls latest changes from origin and refreshes Python dependencies."""

    progress = pyqtSignal(str)
    success = pyqtSignal(str)   # "updated" | "already_up_to_date"
    error = pyqtSignal(str)

    _GIT_TIMEOUT = 60
    _PIP_TIMEOUT = 120

    def _run(self, cmd: list, timeout: int) -> subprocess.CompletedProcess:
        kwargs = {
            "cwd": str(REPO_ROOT),
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.run(cmd, **kwargs)

    def run(self):
        if getattr(sys, "frozen", False):
            self.error.emit("Auto-update is not available for packaged builds.")
            return

        try:
            self.progress.emit("Fetching latest changes…")
            result = self._run(["git", "pull", "--ff-only"], self._GIT_TIMEOUT)

            if result.returncode != 0:
                stderr = (result.stderr or result.stdout).strip()
                self.error.emit(stderr or "git pull failed.")
                return

            if "Already up to date." in result.stdout:
                self.success.emit("already_up_to_date")
                return

            req = REPO_ROOT / "requirements.txt"
            if req.exists():
                self.progress.emit("Updating dependencies…")
                self._run(
                    [sys.executable, "-m", "pip", "install", "-r", str(req), "--quiet"],
                    self._PIP_TIMEOUT,
                )

            self.success.emit("updated")

        except subprocess.TimeoutExpired:
            self.error.emit("Update timed out — check your network connection.")
        except FileNotFoundError:
            self.error.emit("git is not available on this system.")
        except Exception as exc:
            self.error.emit(str(exc))


# ── Post-update flag ──────────────────────────────────────────────────────────

def _flag_path() -> Path:
    return Path(tempfile.gettempdir()) / "prism_desktop_just_updated"


def write_update_flag() -> None:
    """Record the pre-update version so the next startup can run a sanity check."""
    try:
        _flag_path().write_text(APP_VERSION, encoding="utf-8")
    except OSError:
        pass


def consume_update_flag() -> str | None:
    """
    Read and delete the update flag written before the restart.
    Returns the version string that was running before the update, or None.
    """
    path = _flag_path()
    if not path.exists():
        return None
    try:
        prev = path.read_text(encoding="utf-8").strip()
        path.unlink(missing_ok=True)
        return prev or "unknown"
    except OSError:
        return None


# ── App restart ───────────────────────────────────────────────────────────────

def restart_app() -> None:
    """Write the update flag, spawn a fresh instance, then quit the current one."""
    write_update_flag()
    subprocess.Popen([sys.executable] + sys.argv)
    QApplication.quit()
