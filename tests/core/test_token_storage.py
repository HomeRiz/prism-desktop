import os
import stat
import subprocess
import types

import pytest
from cryptography.fernet import Fernet

from core import token_storage as ts

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are posix only")


def fake_sys(platform):
    return types.SimpleNamespace(platform=platform)


def enc_path(config_dir):
    return config_dir / ".ha_token.enc"


def salt_path(config_dir):
    return config_dir / ".ha_token.salt"


@pytest.fixture
def file_storage(config_dir, no_keyring, fixed_seed):
    return config_dir


def test_round_trip_through_encrypted_file(file_storage):
    ts.store_token("abc.def.ghi")
    assert ts.load_token() == "abc.def.ghi"


def test_round_trip_preserves_unicode_and_long_tokens(file_storage):
    token = "tok-" + "ü€" * 500
    ts.store_token(token)
    assert ts.load_token() == token


def test_stored_file_does_not_contain_plaintext(file_storage):
    ts.store_token("super-secret-token")
    assert b"super-secret-token" not in enc_path(file_storage).read_bytes()


def test_empty_token_is_not_stored(file_storage):
    ts.store_token("")
    assert not enc_path(file_storage).exists()
    assert ts.load_token() == ""


def test_load_with_no_files_returns_empty(file_storage):
    assert ts.load_token() == ""


def test_load_with_missing_salt_returns_empty(file_storage):
    ts.store_token("tok")
    salt_path(file_storage).unlink()
    assert ts.load_token() == ""


def test_load_with_missing_enc_file_returns_empty(file_storage):
    ts.store_token("tok")
    enc_path(file_storage).unlink()
    assert ts.load_token() == ""


def test_tampered_ciphertext_is_rejected(file_storage):
    ts.store_token("tok")
    path = enc_path(file_storage)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    assert ts.load_token() == ""


def test_truncated_ciphertext_is_rejected(file_storage):
    ts.store_token("tok")
    path = enc_path(file_storage)
    path.write_bytes(path.read_bytes()[:20])
    assert ts.load_token() == ""


def test_garbage_ciphertext_is_rejected(file_storage):
    ts.store_token("tok")
    enc_path(file_storage).write_bytes(b"not a fernet token")
    assert ts.load_token() == ""


def test_changed_salt_cannot_decrypt(file_storage):
    ts.store_token("tok")
    salt_path(file_storage).write_bytes(os.urandom(16))
    assert ts.load_token() == ""


def test_wrong_machine_seed_cannot_decrypt(file_storage, fixed_seed):
    ts.store_token("tok")
    fixed_seed["value"] = b"another-machine"
    ts._derive_key.cache_clear()
    assert ts.load_token() == ""


def test_same_seed_and_salt_derive_same_key(fixed_seed):
    salt = b"s" * 16
    assert ts._derive_key(salt) == ts._derive_key(salt)


def test_different_salts_derive_different_keys(fixed_seed):
    assert ts._derive_key(b"a" * 16) != ts._derive_key(b"b" * 16)


def test_derived_key_is_valid_fernet_key(fixed_seed):
    Fernet(ts._derive_key(b"z" * 16))


def test_salt_is_reused_across_stores(file_storage):
    ts.store_token("one")
    first = salt_path(file_storage).read_bytes()
    ts.store_token("two")
    assert salt_path(file_storage).read_bytes() == first
    assert ts.load_token() == "two"


def test_new_salt_is_sixteen_random_bytes(file_storage):
    ts.store_token("one")
    assert len(salt_path(file_storage).read_bytes()) == 16


@posix_only
def test_files_are_created_owner_only(file_storage):
    ts.store_token("tok")
    for path in (enc_path(file_storage), salt_path(file_storage)):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@posix_only
def test_loose_permissions_are_tightened_on_load(file_storage):
    ts.store_token("tok")
    os.chmod(enc_path(file_storage), 0o644)
    os.chmod(salt_path(file_storage), 0o644)
    assert ts.load_token() == "tok"
    assert stat.S_IMODE(enc_path(file_storage).stat().st_mode) == 0o600
    assert stat.S_IMODE(salt_path(file_storage).stat().st_mode) == 0o600


@posix_only
def test_loose_salt_permissions_are_tightened_on_store(file_storage):
    ts.store_token("tok")
    os.chmod(salt_path(file_storage), 0o644)
    ts.store_token("tok2")
    assert stat.S_IMODE(salt_path(file_storage).stat().st_mode) == 0o600


def test_write_private_leaves_no_temp_file(config_dir):
    target = config_dir / "secret"
    ts._write_private(target, b"data")
    assert target.read_bytes() == b"data"
    assert [p.name for p in config_dir.iterdir()] == ["secret"]


def test_write_private_cleans_temp_on_failure(config_dir, monkeypatch):
    target = config_dir / "secret"

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(ts.os, "replace", boom)
    with pytest.raises(OSError):
        ts._write_private(target, b"data")
    assert list(config_dir.iterdir()) == []


def test_clear_token_removes_files(file_storage):
    ts.store_token("tok")
    ts.clear_token()
    assert not enc_path(file_storage).exists()
    assert not salt_path(file_storage).exists()
    assert ts.load_token() == ""


def test_clear_token_without_files_is_harmless(file_storage):
    ts.clear_token()


def test_keyring_store_deletes_stale_encrypted_file(config_dir, fake_keyring, fixed_seed):
    ts._enc_store("old")
    assert enc_path(config_dir).exists()
    ts.store_token("fresh")
    assert not enc_path(config_dir).exists()
    assert fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] == "fresh"
    assert ts.load_token() == "fresh"


def test_keyring_failure_falls_back_to_file_and_clears_stale_entry(config_dir, fake_keyring, fixed_seed):
    fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] = "stale"
    fake_keyring.fail_set = True
    ts.store_token("fresh")
    assert (ts.SERVICE_NAME, ts.KEY_TOKEN) not in fake_keyring.store
    assert ts.load_token() == "fresh"


def test_encrypted_file_takes_priority_over_keyring(config_dir, fake_keyring, fixed_seed):
    fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] = "keyring-old"
    ts._enc_store("file-new")
    assert ts.load_token() == "file-new"


def test_load_uses_keyring_when_no_file(config_dir, fake_keyring, fixed_seed):
    fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] = "from-keyring"
    assert ts.load_token() == "from-keyring"


def test_keyring_read_error_returns_empty(config_dir, fake_keyring, fixed_seed):
    fake_keyring.fail_get = True
    assert ts.load_token() == ""


def test_corrupt_file_falls_through_to_keyring(config_dir, fake_keyring, fixed_seed):
    ts._enc_store("tok")
    enc_path(config_dir).write_bytes(b"junk")
    fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] = "kr"
    assert ts.load_token() == "kr"


def test_clear_token_removes_keyring_entry_and_files(config_dir, fake_keyring, fixed_seed):
    fake_keyring.store[(ts.SERVICE_NAME, ts.KEY_TOKEN)] = "kr"
    ts._enc_store("f")
    ts.clear_token()
    assert fake_keyring.store == {}
    assert not enc_path(config_dir).exists()


def test_clear_token_tolerates_missing_keyring_entry(config_dir, fake_keyring, fixed_seed):
    ts.clear_token()


def test_probe_succeeds_with_working_keyring(monkeypatch, fake_keyring):
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    assert ts._probe_keyring() is True
    assert fake_keyring.store == {}


def test_probe_result_is_cached(monkeypatch, fake_keyring):
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    assert ts._probe_keyring() is True
    fake_keyring.fail_set = True
    assert ts._probe_keyring() is True


def test_probe_fails_when_keyring_raises(monkeypatch, fake_keyring):
    fake_keyring.fail_set = True
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    assert ts._probe_keyring() is False


def test_probe_fails_on_read_back_mismatch(monkeypatch, fake_keyring):
    fake_keyring.get_password = lambda service, key: "different"
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    assert ts._probe_keyring() is False


def test_probe_tolerates_unsupported_delete(monkeypatch, fake_keyring):
    def no_delete(service, key):
        raise NotImplementedError

    fake_keyring.delete_password = no_delete
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    assert ts._probe_keyring() is True


def test_probe_never_touches_keyring_on_macos(monkeypatch, fake_keyring):
    fake_keyring.fail_set = True
    called = []
    fake_keyring.get_keyring = lambda: called.append(1)
    monkeypatch.setattr(ts, "_keyring_probed", False)
    monkeypatch.setattr(ts, "_keyring_available", True)
    monkeypatch.setattr(ts, "sys", fake_sys("darwin"))
    assert ts._probe_keyring() is False
    assert called == []


def test_machine_seed_linux_reads_machine_id(monkeypatch):
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))
    monkeypatch.setattr(ts.Path, "read_text", lambda self, *a, **k: "abc123\n")
    assert ts._get_machine_seed() == b"abc123"


def test_machine_seed_linux_falls_back_to_dbus_id(monkeypatch):
    monkeypatch.setattr(ts, "sys", fake_sys("linux"))

    def read_text(self, *a, **k):
        if str(self) == "/etc/machine-id":
            raise FileNotFoundError
        return "dbus-id\n"

    monkeypatch.setattr(ts.Path, "read_text", read_text)
    assert ts._get_machine_seed() == b"dbus-id"


def test_machine_seed_darwin_parses_ioreg_output(monkeypatch):
    monkeypatch.setattr(ts, "sys", fake_sys("darwin"))
    output = '    "IOPlatformUUID" = "11111111-2222-3333-4444-555555555555"\n'
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(stdout='  "x" = "y"\n' + output),
    )
    assert ts._get_machine_seed() == b"11111111-2222-3333-4444-555555555555"


def test_machine_seed_darwin_ioreg_failure_uses_host_fallback(monkeypatch):
    monkeypatch.setattr(ts, "sys", fake_sys("darwin"))

    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(ts.platform, "node", lambda: "host")
    monkeypatch.setattr(ts.os, "getlogin", lambda: "alice")
    assert ts._get_machine_seed() == b"host:alice"


def test_machine_seed_fallback_uses_uid_when_getlogin_fails(monkeypatch):
    monkeypatch.setattr(ts, "sys", fake_sys("freebsd"))
    monkeypatch.setattr(ts.platform, "node", lambda: "host")

    def no_tty():
        raise OSError("no controlling terminal")

    monkeypatch.setattr(ts.os, "getlogin", no_tty)
    monkeypatch.setattr(ts.os, "getuid", lambda: 501, raising=False)
    assert ts._get_machine_seed() == b"host:501"


def test_machine_seed_windows_reads_registry(monkeypatch):
    winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=1,
        OpenKey=lambda root, path: "handle",
        QueryValueEx=lambda key, name: ("guid-1234", 1),
        CloseKey=lambda key: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "winreg", winreg)
    monkeypatch.setattr(ts, "sys", fake_sys("win32"))
    assert ts._get_machine_seed() == b"guid-1234"


def test_machine_seed_windows_registry_failure_uses_fallback(monkeypatch):
    def boom(root, path):
        raise OSError

    winreg = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, OpenKey=boom)
    monkeypatch.setitem(__import__("sys").modules, "winreg", winreg)
    monkeypatch.setattr(ts, "sys", fake_sys("win32"))
    monkeypatch.setattr(ts.platform, "node", lambda: "pc")
    monkeypatch.setattr(ts.os, "getlogin", lambda: "bob")
    assert ts._get_machine_seed() == b"pc:bob"
