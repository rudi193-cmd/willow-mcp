"""Tests for web_egress gate."""

import json

import pytest

from willow_mcp import web_egress


def test_egress_denied_without_web_net(home):
    apps = home / "mcp_apps" / "reader"
    apps.mkdir(parents=True)
    (apps / "manifest.json").write_text(json.dumps({"permissions": ["web_read"]}))
    denial = web_egress.egress_denial("reader")
    assert denial is not None
    assert "net_denied" in denial["error"]


def test_egress_denied_without_lease(home, monkeypatch):
    apps = home / "mcp_apps" / "webby"
    apps.mkdir(parents=True)
    (apps / "manifest.json").write_text(
        json.dumps({"permissions": ["web_read", "web_net"]})
    )
    monkeypatch.setattr("willow_mcp.consent.internet_permitted", lambda: True)
    denial = web_egress.egress_denial("webby")
    assert denial is not None
    assert "lease_denied" in denial["error"]
