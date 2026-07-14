"""UtetyAdapter — UTETY speaks through its own mouth, never jeles's.

Founding rule (UTETY build-plan §0.5): UTETY's product identity and egress ride a
`UtetyAdapter` with its own app_id, backend URL, and secret — so a student-facing
call is attributable to `utety` and never borrows the librarian's credentials.
These tests pin that separation and the adapter's registration.
"""
from __future__ import annotations

import importlib

import pytest

from willow_mcp import integrations as ig


def test_utety_is_registered_and_live():
    a = ig.get("utety")
    assert a is not None, "utety adapter must be registered"
    assert isinstance(a, ig.UtetyAdapter)
    assert a.status == "live"          # not a StubAdapter
    assert a.name == "utety"


def test_utety_is_not_the_jeles_adapter():
    """The founding rule, made a test: utety is a DISTINCT adapter with its own
    identity — different object, name, base_url, and credential path than jeles."""
    utety, jeles = ig.get("utety"), ig.get("jeles")
    assert utety is not jeles
    assert utety.name != jeles.name
    assert utety.base_url != jeles.base_url
    assert ig.vault_key("utety") == "integration/utety/token"
    assert ig.vault_key("utety") != ig.vault_key("jeles")


def test_utety_owns_its_credential_source(monkeypatch):
    monkeypatch.delenv("WILLOW_UTETY_SECRET", raising=False)
    a = ig.get("utety")
    # No env secret and (in test) no vault → source is None, never jeles's.
    src = a.credential_source()
    assert src in (None, "vault")
    monkeypatch.setenv("WILLOW_UTETY_SECRET", "s3cret")
    assert a.credential_source() == "env:WILLOW_UTETY_SECRET"


def test_base_url_respects_env_override(monkeypatch):
    """base_url is resolved at import from WILLOW_UTETY_BASE_URL — the seam that
    swaps the backend without touching code (build-plan: adapter is swappable)."""
    monkeypatch.setenv("WILLOW_UTETY_BASE_URL", "https://utety.example.test/api/")
    reloaded = importlib.reload(ig)
    try:
        assert reloaded.get("utety").base_url == "https://utety.example.test/api"  # trailing / stripped
    finally:
        monkeypatch.delenv("WILLOW_UTETY_BASE_URL", raising=False)
        importlib.reload(ig)  # restore module default for other tests


def test_utety_listed_in_integrations():
    names = {row["name"] for row in ig.list_integrations()}
    assert "utety" in names


def test_utety_host_is_fixed_path_cannot_repoint(monkeypatch):
    """A request path cannot re-point scheme/host — the adapter contract. A
    dot-dot or protocol-relative path is refused before any socket."""
    a = ig.get("utety")
    assert a.request("GET", "/../../etc/passwd").get("error", "").startswith("bad_path")
    assert a.request("GET", "//evil.example.com/x").get("error", "").startswith("bad_path")
