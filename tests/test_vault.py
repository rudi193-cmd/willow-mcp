"""Tests for vault.py — Fernet-encrypted secret store. Previously untested (L-TEST-01)."""

import stat

import pytest
from willow_mcp.vault import Vault, default_vault


@pytest.fixture
def vault(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    return v


def test_write_and_read_roundtrip(vault):
    vault.write("google.client_id", "abc123")
    assert vault.read("google.client_id") == "abc123"


def test_read_missing_key_returns_none(vault):
    assert vault.read("nope") is None


def test_has(vault):
    assert vault.has("google.client_id") is False
    vault.write("google.client_id", "abc123")
    assert vault.has("google.client_id") is True


def test_write_overwrites_existing(vault):
    vault.write("k", "first")
    vault.write("k", "second")
    assert vault.read("k") == "second"


def test_list_keys(vault):
    vault.write("a", "1")
    vault.write("b", "2")
    assert vault.list_keys() == ["a", "b"]


def test_key_and_db_files_are_0600(vault):
    key_mode = stat.S_IMODE(vault._key_path.stat().st_mode)
    db_mode = stat.S_IMODE(vault._vault.stat().st_mode)
    assert key_mode == 0o600
    assert db_mode == 0o600


def test_default_vault_raises_if_key_missing_but_db_present(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    (tmp_path / "vault.db").write_text("not a real db, presence is what matters")
    with pytest.raises(FileNotFoundError):
        default_vault()
