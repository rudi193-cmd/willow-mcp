"""Smoke tests for willow-serve worker-install unit generation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVE = REPO / "scripts" / "willow-serve"
TEMPLATE = REPO / "deploy" / "willow-mcp-worker@.service.template"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [str(SERVE), *args],
        cwd=REPO,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


def test_worker_install_writes_fleet_defaults(tmp_path):
    cfg = tmp_path / "config"
    unit_file = cfg / "systemd" / "user" / "willow-mcp-worker@.service"
    willow_home = tmp_path / "fleet" / ".willow"
    willow_home.mkdir(parents=True)
    (willow_home / "kart-sandbox.json").write_text("{}\n", encoding="utf-8")

    proc = _run(
        "worker-install",
        env={
            "XDG_CONFIG_HOME": str(cfg),
            "WILLOW_SERVE_WILLOW_HOME": str(willow_home),
            "WILLOW_SERVE_PG_DB": "willow_test",
            "WILLOW_SERVE_PG_USER": "tester",
            "WILLOW_HOME": "/should/not/be/used",
        },
    )
    assert unit_file.is_file(), proc.stdout + proc.stderr
    body = unit_file.read_text(encoding="utf-8")
    assert "-m willow_mcp.worker" in body
    assert "--require-postgres" in body
    assert f"WILLOW_HOME={willow_home}" in body
    assert "WILLOW_PG_DB=willow_test" in body
    assert f"KART_SANDBOX_CONFIG={willow_home}/kart-sandbox.json" in body
    assert "/should/not/be/used" not in body


def test_worker_off_rejects_invalid_lane():
    proc = _run("worker-off", "nope")
    assert proc.returncode == 2
    assert "invalid lane" in proc.stderr


def test_worker_template_has_journal_and_postgres():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "postgresql.service" in text
    assert "StandardOutput=journal" in text
    assert "willow_mcp.worker" in text
