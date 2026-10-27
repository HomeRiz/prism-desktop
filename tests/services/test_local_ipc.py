import os
import shutil
import tempfile
import threading
import socket
from pathlib import Path

import pytest

from services import local_ipc

pytestmark = pytest.mark.skipif(os.name != "posix", reason="local IPC uses unix domain sockets")

@pytest.fixture
def short_tmp(monkeypatch):
    directory = tempfile.mkdtemp(prefix="pi", dir="/tmp")
    monkeypatch.setenv("TMPDIR", directory)
    monkeypatch.setattr(tempfile, "tempdir", None)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)

@pytest.fixture
def config_path(monkeypatch, tmp_path):
    state = {"path": tmp_path / "config.json"}
    monkeypatch.setattr(local_ipc, "get_config_path", lambda *a: state["path"])
    return state

def test_server_name_is_stable_for_same_config_path(config_path):
    assert local_ipc.prism_ipc_server_name() == local_ipc.prism_ipc_server_name()

def test_server_name_has_prefix_and_short_hex_digest(config_path):
    name = local_ipc.prism_ipc_server_name()
    prefix, digest = name.rsplit("-", 1)
    assert prefix == "prism-desktop"
    assert len(digest) == 12
    int(digest, 16)

def test_server_name_differs_per_config_path(config_path, tmp_path):
    first = local_ipc.prism_ipc_server_name()
    config_path["path"] = tmp_path / "other" / "config.json"
    assert local_ipc.prism_ipc_server_name() != first

def test_server_name_does_not_leak_path(config_path):
    assert str(config_path["path"].parent) not in local_ipc.prism_ipc_server_name()

def test_send_command_without_server_returns_false(short_tmp, config_path):
    assert local_ipc.send_local_command("toggle") is False

def test_send_command_to_stale_socket_file_returns_false(short_tmp, config_path):
    Path(short_tmp, local_ipc.prism_ipc_server_name()).write_text("")
    assert local_ipc.send_local_command("toggle") is False

def test_send_command_delivers_stripped_utf8_to_plain_socket(short_tmp, config_path):
    path = os.path.join(short_tmp, local_ipc.prism_ipc_server_name())
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    received = []

    def accept():
        conn, _ = server.accept()
        received.append(conn.recv(1024))
        conn.close()

    thread = threading.Thread(target=accept)
    thread.start()
    try:
        assert local_ipc.send_local_command("  toggle \n") is True
    finally:
        thread.join(timeout=5)
        server.close()
    assert received == [b"toggle"]

def test_command_server_round_trip(qapp, qtbot, short_tmp, config_path):
    server = local_ipc.LocalCommandServer()
    try:
        assert server.start() is True
        with qtbot.waitSignal(server.command_received, timeout=5000) as blocker:
            assert local_ipc.send_local_command("toggle-dashboard") is True
        assert blocker.args == ["toggle-dashboard"]
    finally:
        server.close()

def test_command_server_delivers_multiple_commands_in_order(qapp, qtbot, short_tmp, config_path):
    server = local_ipc.LocalCommandServer()
    received = []
    server.command_received.connect(received.append)
    try:
        assert server.start()
        for command in ("one", "two", "three"):
            assert local_ipc.send_local_command(command)
            qtbot.waitUntil(lambda c=command: c in received, timeout=5000)
    finally:
        server.close()
    assert received == ["one", "two", "three"]

def test_command_server_ignores_blank_commands(qapp, qtbot, short_tmp, config_path):
    server = local_ipc.LocalCommandServer()
    received = []
    server.command_received.connect(received.append)
    try:
        assert server.start()
        assert local_ipc.send_local_command("   ")
        assert local_ipc.send_local_command("ok")
        qtbot.waitUntil(lambda: received == ["ok"], timeout=5000)
    finally:
        server.close()

def test_command_server_start_recovers_from_stale_socket(qapp, short_tmp, config_path):
    stale = Path(short_tmp, local_ipc.prism_ipc_server_name())
    stale.write_text("")
    server = local_ipc.LocalCommandServer()
    try:
        assert server.start() is True
    finally:
        server.close()

def test_command_server_close_removes_socket_file(qapp, short_tmp, config_path):
    server = local_ipc.LocalCommandServer()
    server.start()
    socket_file = Path(short_tmp, local_ipc.prism_ipc_server_name())
    server.close()
    assert not socket_file.exists()
    assert local_ipc.send_local_command("late") is False

def test_server_class_is_built_lazily_and_cached(qapp):
    first = local_ipc.LocalCommandServer()
    second = local_ipc.LocalCommandServer()
    assert type(first) is type(second)
