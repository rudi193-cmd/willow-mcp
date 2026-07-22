"""Fleet kart-sandbox policy — operator vault must not be reachable via blanket binds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FLEET_POLICY = Path.home() / "github" / ".willow" / "kart-sandbox.json"
_BIND_LIST_KEYS = (
    "bind_read_only",
    "bind_read_write",
    "bind_try",
    "bind_try_read_only",
)
_VAULT_FRAGMENT = "sean-data-vault"
_GITHUB_BLANKET = "{{HOME}}/github"
_KARTIKEYA_BIND = "{{HOME}}/github/kartikeya"


@pytest.fixture
def fleet_policy():
    """Fleet policy at $WILLOW_HOME/kart-sandbox.json (the live successor-lane file)."""
    assert _FLEET_POLICY.is_file(), f"missing fleet policy: {_FLEET_POLICY}"
    return json.loads(_FLEET_POLICY.read_text(encoding="utf-8"))


def _paths_from_config(cfg: dict) -> list[str]:
    paths: list[str] = []
    for key in _BIND_LIST_KEYS:
        paths.extend(str(p) for p in cfg.get(key, []))
    return paths


def test_fleet_policy_has_no_vault_bind_entries(fleet_policy):
    offenders = [p for p in _paths_from_config(fleet_policy) if _VAULT_FRAGMENT in p]
    assert offenders == [], f"vault path in fleet bind lists: {offenders}"


def test_fleet_policy_has_no_github_blanket_bind(fleet_policy):
    offenders = [p for p in _paths_from_config(fleet_policy) if p == _GITHUB_BLANKET]
    assert offenders == [], f"~/github blanket in fleet bind lists: {offenders}"


def test_fleet_policy_enumerates_kartikeya_bind_try(fleet_policy):
    bind_try = [str(p) for p in fleet_policy.get("bind_try", [])]
    assert _KARTIKEYA_BIND in bind_try, (
        f"{_KARTIKEYA_BIND} missing from bind_try — kartikeya editable install "
        "would be unreachable after blanket removal"
    )
