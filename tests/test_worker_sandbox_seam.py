"""A production worker must not serve on the generic sandbox policy.

Regression cover for the slice-2 cutover rollback (FRANK 73ca45d5,
dispatch E0C187D3).

What happened: `willow-mcp-worker-fast/batch` were started 2026-07-20 20:43
with no `KART_SANDBOX_CONFIG` in their unit `Environment=`. kartikeya fell
back to its vendored product-neutral policy, silently, and every task those
workers claimed died with `bwrap: Creating new namespace failed: Resource
temporarily unavailable`. The fast lane looked healthy because the legacy
willow-2.0 worker retried behind it; the batch lane had no such backstop and
dead-lettered every task for 28 hours. Nothing failed loudly — the units
stayed `active (running)` throughout.

The seams were later added to `$WILLOW_HOME/env`, which did not help: an
`EnvironmentFile` cannot reach a process that is already running, and these
units carried no `EnvironmentFile=` line to begin with.

So the contract is: a worker serving a production lane resolves the fleet
policy or refuses to start. A unit that fails to start is visible.
"""
from __future__ import annotations

import json

import pytest

from willow_mcp import worker as worker_mod


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """A $WILLOW_HOME with no kart-sandbox.json and no seam in the env."""
    monkeypatch.delenv("KART_SANDBOX_CONFIG", raising=False)
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setattr(
        "kartikeya.home.willow_home", lambda package_root=None: tmp_path
    )
    return tmp_path


def _write_fleet_policy(path):
    path.write_text(
        json.dumps({"env_prefixes": ["WILLOW_"], "bind_read_only": ["/usr"]}),
        encoding="utf-8",
    )
    return path


def test_production_worker_refuses_generic_policy(isolated_home):
    with pytest.raises(RuntimeError) as exc:
        worker_mod.check_sandbox_config(require_fleet_config=True)

    msg = str(exc.value)
    # the message has to be actionable at 3am: name the variable, and say why
    # editing the env file is not the fix.
    assert "KART_SANDBOX_CONFIG" in msg
    assert "EnvironmentFile" in msg


def test_production_worker_accepts_willow_home_policy(isolated_home):
    policy = _write_fleet_policy(isolated_home / "kart-sandbox.json")

    source = worker_mod.check_sandbox_config(require_fleet_config=True)

    assert source == str(policy)


def test_production_worker_accepts_explicit_seam(isolated_home, tmp_path, monkeypatch):
    policy = _write_fleet_policy(tmp_path / "fleet-policy.json")
    monkeypatch.setenv("KART_SANDBOX_CONFIG", str(policy))

    source = worker_mod.check_sandbox_config(require_fleet_config=True)

    assert source == str(policy)


def test_non_production_worker_tolerates_generic_policy(isolated_home):
    # a --once drain or a dev fast lane may legitimately run on the default
    source = worker_mod.check_sandbox_config(require_fleet_config=False)

    assert source  # reported, not enforced
