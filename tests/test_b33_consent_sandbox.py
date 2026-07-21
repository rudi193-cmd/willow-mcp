"""B-33 — consent policy files must be read-only inside the Kart sandbox.

The standing egress kill switch (`consent.internet`) lives in on-disk policy
files under $WILLOW_HOME. Kartikeya overlays them via
``collect_mcp_trust_ro_overlays`` (kartikeya#6, 0.0.4+). This test pins the
contract from willow-mcp's side so a kartikeya regression cannot reopen the
sandbox lane silently.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("kartikeya")

from kartikeya import sandbox


def _layout(home):
    (home / "mcp_apps").mkdir(parents=True)
    (home / "config").mkdir(parents=True)
    (home / "config" / "settings.global.json").write_text(
        json.dumps({"version": 1, "consent": {"internet": False, "cloud_llm": False, "lan": False}})
        + "\n",
        encoding="utf-8",
    )
    (home / "config" / "consent.json").write_text(
        json.dumps({"internet": False, "cloud_llm": False, "lan": False}) + "\n",
        encoding="utf-8",
    )
    (home / "consent.json").write_text(
        json.dumps({"internet": False, "cloud_llm": False, "lan": False}) + "\n",
        encoding="utf-8",
    )


def test_trust_ro_overlays_include_consent_policy_files(home, monkeypatch):
    _layout(home)
    monkeypatch.setenv("WILLOW_HOME", str(home))
    monkeypatch.setattr("kartikeya.home.willow_home", lambda package_root=None: home)

    overlays = {p.resolve() for p in sandbox.collect_mcp_trust_ro_overlays()}
    expected = {
        (home / "mcp_apps").resolve(),
        (home / "config" / "settings.global.json").resolve(),
        (home / "config" / "consent.json").resolve(),
        (home / "consent.json").resolve(),
    }
    assert expected <= overlays


def test_sandbox_manifest_lists_consent_files_bound_ro(home, monkeypatch):
    _layout(home)
    monkeypatch.setenv("WILLOW_HOME", str(home))
    monkeypatch.setattr("kartikeya.home.willow_home", lambda package_root=None: home)

    manifest = sandbox.sandbox_manifest()
    bound_ro = {p for p in manifest.get("bound_ro", [])}
    for path in (
        home / "config" / "settings.global.json",
        home / "config" / "consent.json",
        home / "consent.json",
    ):
        assert str(path.resolve()) in bound_ro
