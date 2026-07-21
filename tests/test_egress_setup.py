"""Tests for egress key bootstrap and default path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from willow_mcp import egress_setup
from willow_mcp.egress_authorization import public_key_path


@pytest.fixture
def egress_home(tmp_path, monkeypatch):
    cfg = tmp_path / "egress-config"
    willow_home = tmp_path / "willow-home"
    willow_home.mkdir()
    monkeypatch.setenv("WILLOW_MCP_EGRESS_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("WILLOW_HOME", str(willow_home))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(willow_home))
    monkeypatch.delenv("WILLOW_MCP_EGRESS_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("WILLOW_MCP_EGRESS_SIGNING_KEY", raising=False)
    return cfg


def test_ensure_keypair_creates_outside_willow_home(egress_home):
    result = egress_setup.ensure_keypair()
    assert result["action"] == "created"
    private = Path(result["private_key"])
    public = Path(result["public_key"])
    assert private.is_file()
    assert public.is_file()
    assert egress_setup.manifest_path().is_file()
    assert egress_setup.resolve_private_key_path() == private
    assert egress_setup.resolve_public_key_path() == public
    assert public_key_path() == public


def test_ensure_keypair_registers_existing(egress_home, tmp_path):
    private = tmp_path / "priv.pem"
    public = tmp_path / "pub.pem"
    egress_setup._generate_keypair(private, public)
    result = egress_setup.ensure_keypair(private_key=private, public_key=public)
    assert result["action"] == "registered"
    manifest = json.loads(egress_setup.manifest_path().read_text(encoding="utf-8"))
    assert manifest["private_key"] == str(private.resolve())
    assert manifest["public_key"] == str(public.resolve())


def test_public_key_env_overrides_manifest(egress_home, tmp_path):
    egress_setup.ensure_keypair()
    override = tmp_path / "override.pub"
    override.write_text("dummy", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("WILLOW_MCP_EGRESS_PUBLIC_KEY", str(override))
    try:
        assert egress_setup.resolve_public_key_path() == override
    finally:
        monkeypatch.undo()
