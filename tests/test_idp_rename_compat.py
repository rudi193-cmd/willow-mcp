"""`idp` is the upstream provider; `iss` belongs to RFC 9207. And the rename
must not sign anybody out.

WHAT WAS WRONG
--------------
`oauth.exchange_authorization_code` stored the upstream provider NAME —
literally `"google"` or `"apple"` — under the key `issuer`, and
`load_access_token` surfaced it as `claims={"iss": ...}`. RFC 9207 gives `iss`
a different and specific meaning: the issuer URL of *this* authorization
server. SEP-2468 in the 2026-07-28 revision makes clients **MUST**-validate a
present `iss` against the recorded issuer.

So the moment anyone implemented RFC 9207 properly and wrote a real issuer URL
into `claims["iss"]`, `_resolve_serve_identity` would look up a binding keyed on
`("https://127.0.0.1:8765/", subject)`, find none, and deny **every** serve-mode
caller. Fail-closed, so not a breach — a total outage, from one shadowed key.

WHAT THIS FILE PINS
-------------------
Both halves. That the two concepts no longer share a key, and — the part with
real blast radius — that renaming them did not orphan the state already on disk.
Two persistence surfaces held the old key: the OAuth token file and the binding
records. An upgrade that silently invalidated either would look to an operator
exactly like "everyone got signed out", with no reason given.
"""
from __future__ import annotations

import json

import pytest

from willow_mcp import identity_binding


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Pin BOTH env vars. `_bindings_root` prefers WILLOW_MCP_APPS_ROOT over
    WILLOW_HOME, so leaving it set from another test sends these writes
    somewhere else and the assertions read an empty directory."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)
    return tmp_path


# ── the rename itself ────────────────────────────────────────────────────────


def test_iss_is_no_longer_used_for_the_provider_name():
    """The regression fence. `iss` must not carry "google"/"apple" again."""
    from willow_mcp import oauth

    src = (oauth.__file__ and open(oauth.__file__, encoding="utf-8").read()) or ""
    assert 'claims={"iss"' not in src, (
        "claims['iss'] is RFC 9207's issuer URL, not the upstream provider name"
    )


def test_the_gate_reads_idp_not_iss():
    from willow_mcp import server

    src = open(server.__file__, encoding="utf-8").read()
    assert '.get("idp")' in src
    assert '(token.claims or {}).get("iss")' not in src


def test_apples_own_iss_check_is_untouched():
    """`iss` IS used correctly elsewhere — validating Apple's ID token issuer.
    The rename must not have swept that away with a global search-and-replace."""
    from willow_mcp import oauth

    src = open(oauth.__file__, encoding="utf-8").read()
    assert 'payload.get("iss") != "https://appleid.apple.com"' in src


# ── the migration: nothing on disk is orphaned ───────────────────────────────


def _legacy_record(home, idp, subject, app_id):
    """A binding record exactly as it was written BEFORE the rename."""
    root = home / "mcp_apps" / "_identity_bindings"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{idp}__{subject}.json"
    path.write_text(json.dumps({
        "issuer": idp,               # the pre-rename key
        "subject_id": subject,
        "email": "operator@example.com",
        "email_basis": "verified",
        "verified_at": "2026-07-01T00:00:00+00:00",
        "app_id": app_id,
        "confirmed": True,
        "created_at": "2026-07-01T00:00:00+00:00",
    }))
    return path


def test_a_pre_rename_binding_still_resolves(home):
    """The one that would have hurt. A confirmed binding written before the
    rename must keep authorizing its app — an upgrade that quietly stopped
    resolving them is indistinguishable from every agent being deauthorized."""
    _legacy_record(home, "google", "sub-123", "hanuman")
    assert identity_binding.resolve_app_id("google", "sub-123") == "hanuman"


def test_a_pre_rename_binding_is_normalised_on_read(home):
    """Read once, one shape downstream — nothing else has to know two existed."""
    _legacy_record(home, "apple", "sub-9", "willow")
    rec = identity_binding.load_binding("apple", "sub-9")
    assert rec["idp"] == "apple"
    assert "issuer" not in rec


def test_the_filename_format_did_not_change(home):
    """Compatibility rests on this: the path always contained the IdP NAME, so
    an old record sits exactly where the new code looks. If the filename shape
    ever changes, every one of these bindings is orphaned at once."""
    identity_binding.propose_binding("google", "sub-new", "operator@example.com")
    assert (home / "mcp_apps" / "_identity_bindings" / "google__sub-new.json").exists()


def test_an_unconfirmed_pre_rename_binding_still_fails_closed(home):
    root = home / "mcp_apps" / "_identity_bindings"
    root.mkdir(parents=True, exist_ok=True)
    (root / "google__sub-x.json").write_text(json.dumps({
        "issuer": "google", "subject_id": "sub-x", "app_id": "hanuman",
        "confirmed": False,
    }))
    assert identity_binding.resolve_app_id("google", "sub-x") is None


def test_a_pre_rename_access_token_still_carries_its_identity():
    """The other persistence surface. A token in mcp_token.json written before
    the rename keys the provider as `issuer`; reading it must still produce an
    identity, or every live session silently loses its binding."""
    from willow_mcp.oauth import _idp_of

    assert _idp_of({"issuer": "google", "subject": "s"}) == "google"
    assert _idp_of({"idp": "apple", "subject": "s"}) == "apple"
    assert _idp_of({"subject": "s"}) is None


def test_new_writes_use_the_new_key(home):
    identity_binding.propose_binding("google", "sub-fresh", "operator@example.com")
    raw = json.loads((home / "mcp_apps" / "_identity_bindings" / "google__sub-fresh.json").read_text())
    assert raw["idp"] == "google"
    assert "issuer" not in raw
