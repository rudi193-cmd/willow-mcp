"""CLI smoke tests for egress onboarding commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "willow_mcp", *args],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def test_setup_egress_creates_manifest(tmp_path, monkeypatch):
    cfg = tmp_path / "egress"
    willow_home = tmp_path / "willow"
    willow_home.mkdir()
    monkeypatch.setenv("WILLOW_MCP_EGRESS_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("WILLOW_HOME", str(willow_home))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(willow_home))

    out = _run("setup-egress")
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout.split("\n\n")[0])
    assert payload["action"] == "created"
    assert Path(payload["private_key"]).is_file()
    assert Path(payload["public_key"]).is_file()
    assert (cfg / "manifest.json").is_file()


def test_setup_egress_merges_mcp_json(tmp_path, monkeypatch):
    cfg = tmp_path / "egress"
    willow_home = tmp_path / "willow"
    willow_home.mkdir()
    project = tmp_path / "proj"
    mcp_json = project / ".cursor" / "mcp.json"
    mcp_json.parent.mkdir(parents=True)
    mcp_json.write_text(
        json.dumps({"mcpServers": {"willow-mcp": {"command": "willow-mcp"}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WILLOW_MCP_EGRESS_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("WILLOW_HOME", str(willow_home))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(willow_home))

    out = _run("setup-egress", "--project-root", str(project))
    assert out.returncode == 0, out.stderr
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "WILLOW_MCP_EGRESS_PUBLIC_KEY" in data["mcpServers"]["willow-mcp"]["env"]
