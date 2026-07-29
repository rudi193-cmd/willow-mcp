"""The serve-mode arm of `_gate` — L-AUTH-02, previously reachable by no test.

`_gate` has two arms. The stdio arm takes the caller's `app_id` argument at face
value (single-operator trust model) and is covered by test_server.py. The serve
arm does the opposite: it *discards* the caller's `app_id` and resolves the
identity from the authenticated OAuth session's confirmed binding, because over
HTTP anyone who can sign in can type any `app_id` they like. That arm — and the
`_resolve_serve_identity()` it rests on — had no test at all: `grep -rn
"_SERVE_MODE\\|_resolve_serve_identity" tests/` came back empty before this file.

Serve mode is entered here by patching `server._serve_mode`, the accessor every
call-time read now goes through. The sessions are real: an `AccessToken` in the
MCP SDK's own `auth_context_var`, read back by the SDK's `get_access_token()`,
not a stub of it — so these exercise the same contextvar path a live HTTP
request populates.

Four ways in, one of which works:
  * no authenticated session at all                     -> denied
  * a session carrying no idp, or no subject            -> denied
  * signed in, but no operator-confirmed binding        -> denied
  * signed in WITH a confirmed binding                  -> allowed, AS THE BOUND
                                                           IDENTITY
The last line is the finding. A caller who passes `app_id="X"` is gated as
whatever identity the operator bound, never as X — so a signed-in stranger
cannot self-declare their way into another app's manifest.
"""
import contextlib
import json

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from willow_mcp import human_loop, identity_binding, server
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog

IDP = "google"
SUBJECT = "sub-1234567890"


def _fn(tool):
    """FastMCP wraps @mcp.tool() functions; reach the underlying callable."""
    return getattr(tool, "fn", tool)


@contextlib.contextmanager
def signed_in(idp=IDP, subject=SUBJECT):
    """Populate the SDK contextvar the way AuthContextMiddleware does per request.

    `idp=None` models a token whose claims carry no `idp`; `subject=None`
    models one with no `sub`. Both are the shapes `_resolve_serve_identity`
    must refuse rather than resolve.
    """
    token = AccessToken(
        token="opaque-access-token",
        client_id="some-registered-client",
        scopes=["willow"],
        subject=subject,
        claims={"idp": idp} if idp is not None else {},
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Enter serve mode, with an isolated $WILLOW_HOME for manifests + bindings.

    Returns a `mk_app(app_id, perms)` helper. WILLOW_HUMAN_ORCHESTRATOR is
    deleted deliberately: every by_human assertion below must come from the
    OAuth binding, never from an ambient env var that would make the test pass
    for the wrong reason.
    """
    apps = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})
    monkeypatch.setattr(server, "_serve_mode", lambda: True)

    def _mk(app_id, perms=("full_access",)):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": list(perms)}))
        return app_id

    return _mk


def _bind(app_id, idp=IDP, subject=SUBJECT):
    """What `willow-mcp confirm-binding` does: the operator's half of the handshake."""
    identity_binding.propose_binding(idp, subject, email="operator@example.com")
    return identity_binding.confirm_binding(idp, subject, app_id)


# ── the seam itself ──────────────────────────────────────────────────────────

def test_serve_mode_defaults_to_stdio_without_the_flag():
    """Production default is unchanged: argv here has no --serve."""
    assert server._serve_mode() is False
    assert server._SERVE_MODE is False


def test_gate_reads_serve_mode_through_the_accessor_not_the_global(serve):
    """Pins the seam, not just the behaviour.

    The `serve` fixture patches `_serve_mode` and leaves `_SERVE_MODE` False. If
    `_gate` ever goes back to reading the global — or snapshots it into a local,
    a default argument, or a `from .server import _SERVE_MODE` elsewhere — this
    call silently takes the stdio arm and returns the caller's own app_id, which
    is exactly the regression that would strand the serve branch as untestable
    again while every test stayed green.
    """
    serve("caller")
    assert server._SERVE_MODE is False
    effective, err = server._gate("caller", "store_put")
    assert effective is None
    assert "no authenticated session" in err["error"]


# ── _resolve_serve_identity: the three fail-closed arms ──────────────────────

def test_no_authenticated_session_is_denied(serve):
    """No `signed_in()` block: the contextvar is unset, as on an unauthenticated
    request. get_access_token() returns None and the resolver must stop there."""
    serve("caller")
    assert auth_context_var.get() is None
    bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "no authenticated session" in err["error"]


def test_session_without_issuer_is_denied(serve):
    serve("caller")
    _bind("caller")
    with signed_in(idp=None):
        bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "no bound identity" in err["error"]


def test_session_without_subject_is_denied(serve):
    serve("caller")
    _bind("caller")
    with signed_in(subject=None):
        bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "no bound identity" in err["error"]


def test_signed_in_without_a_binding_is_denied(serve):
    """A verified Google/Apple sign-in on its own grants no standing."""
    serve("caller")
    with signed_in():
        bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "signed in but not yet bound" in err["error"]
    assert "confirm-binding" in err["error"]


def test_proposed_but_unconfirmed_binding_is_denied(serve):
    """First sign-in writes an *unconfirmed* binding. Only a human confirms it."""
    serve("caller")
    identity_binding.propose_binding(IDP, SUBJECT, email="operator@example.com")
    with signed_in():
        bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "signed in but not yet bound" in err["error"]


def test_unconfirmed_binding_is_denied_even_when_it_names_an_app_id(serve):
    """`confirmed` must be load-bearing on its own.

    A freshly proposed binding has app_id None, so a resolver that checked only
    `app_id` would still deny it — the two conditions are indistinguishable on
    the sign-in path, and dropping the `confirmed` check breaks nothing visible.
    Write the state that separates them: a record naming an app_id that no human
    has confirmed. Only the `confirmed` flag can refuse this one.
    """
    serve("hanuman")
    record = identity_binding.propose_binding(IDP, SUBJECT, email="operator@example.com")
    record["app_id"] = "hanuman"
    assert record["confirmed"] is False
    identity_binding._write_json_atomic(
        identity_binding.binding_path(IDP, SUBJECT), record)

    with signed_in():
        bound, err = server._resolve_serve_identity()
    assert bound is None
    assert "signed in but not yet bound" in err["error"]


def test_confirmed_binding_resolves(serve):
    serve("hanuman")
    _bind("hanuman")
    with signed_in():
        bound, err = server._resolve_serve_identity()
    assert err is None
    assert bound == "hanuman"


# ── _gate's serve arm: the caller's app_id is not an input to authorization ──

def test_gate_ignores_the_callers_app_id_and_uses_the_binding(serve):
    """The finding, stated as an assertion.

    Both apps have real manifests, so neither answer would look like an error;
    the only thing distinguishing them is which one the gate trusted.
    """
    serve("attacker")
    serve("hanuman")
    _bind("hanuman")
    with signed_in():
        effective, err = server._gate("attacker", "store_put")
    assert err is None
    assert effective == "hanuman"


def test_gate_denies_when_the_bound_identity_lacks_the_permission(serve):
    """Self-declaring a privileged app_id buys nothing: the permission check runs
    against the *bound* identity's manifest, so a caller naming a full_access app
    is still refused on the strength of their own, narrower one."""
    serve("privileged", ["full_access"])
    serve("readonly", ["store_read"])
    _bind("readonly")
    with signed_in():
        effective, err = server._gate("privileged", "store_put")
    assert effective is None
    assert "'readonly' not permitted for 'store_put'" in err["error"]


def test_gate_denies_every_tool_call_when_not_signed_in(serve):
    """No session, no standing — even for an app_id with a perfectly good manifest."""
    serve("hanuman")
    _bind("hanuman")
    effective, err = server._gate("hanuman", "store_put")
    assert effective is None
    assert "serve mode requires OAuth sign-in" in err["error"]


def test_gate_binding_is_per_identity_not_global(serve):
    """A confirmed binding for one (idp, subject) grants nothing to another."""
    serve("hanuman")
    _bind("hanuman")
    with signed_in(subject="sub-someone-else"):
        effective, err = server._gate("hanuman", "store_put")
    assert effective is None
    assert "signed in but not yet bound" in err["error"]


# ── end to end through the real _guarded pipeline ────────────────────────────

def test_tool_body_sees_the_bound_identity_not_the_argument(serve):
    """_guarded substitutes the gate's answer for the caller's app_id before the
    body runs, so the attestation is attributed to the bound identity."""
    serve("attacker")
    serve("hanuman")
    _bind("hanuman")
    with signed_in():
        rec = _fn(server.human_attestation_create)(app_id="attacker", subject_id="ATOM_1")
    assert rec["attested_by"] == "hanuman"
    assert rec["by_human"] is False


def test_unbound_caller_cannot_write_an_attestation_at_all(serve):
    serve("attacker")
    with signed_in():
        out = _fn(server.human_attestation_create)(app_id="attacker", subject_id="ATOM_2")
    assert "signed in but not yet bound" in out.get("error", "")
    listed = human_loop.list_attestations(server._store, subject_id="ATOM_2")
    assert listed == []


# ── by_human's serve arm, end to end — the test PR #197 could not write ──────

def test_serve_by_human_requires_a_confirmed_binding_to_willow(serve):
    """`by_human_attested(app_id, serve_mode=True)` returns True unconditionally.
    That is sound only because reaching the body as "willow" in serve mode is
    itself the proof: the caller cannot name themselves willow, they can only be
    *bound* to willow, by an operator running `willow-mcp confirm-binding` on
    the host. This drives the whole path — sign-in, binding, gate, substitution
    — and asserts the operator's signature comes out the far end.

    No WILLOW_HUMAN_ORCHESTRATOR anywhere: the `serve` fixture deletes it. If
    this passed via the env var it would be asserting the stdio invariant twice
    and the serve one never.
    """
    serve("willow")
    serve("attacker")
    _bind("willow")
    with signed_in():
        rec = _fn(server.human_attestation_create)(app_id="attacker", subject_id="ATOM_H")
    assert rec["attested_by"] == "willow"
    assert rec["by_human"] is True


def test_serve_by_human_satisfies_the_require_human_gate(serve):
    """The consequence that makes by_human worth forging: it is what
    has_attestation(require_human=True) counts."""
    serve("willow")
    _bind("willow")
    with signed_in():
        _fn(server.human_attestation_create)(app_id="willow", subject_id="ATOM_G")
    assert human_loop.has_attestation(
        server._store, subject_id="ATOM_G", require_human=True) is True


def test_serve_claiming_willow_without_the_binding_yields_no_human_signature(serve):
    """The forgery attempt, in the mode where app_id is not caller-supplied: the
    caller types willow, but is bound to hanuman, so the record is hanuman's and
    carries no operator signature."""
    serve("willow")
    serve("hanuman")
    _bind("hanuman")
    with signed_in():
        rec = _fn(server.human_attestation_create)(app_id="willow", subject_id="ATOM_F")
    assert rec["attested_by"] == "hanuman"
    assert rec["by_human"] is False
    assert human_loop.has_attestation(
        server._store, subject_id="ATOM_F", require_human=True) is False


def test_serve_by_human_does_not_depend_on_the_stdio_env_var(serve, monkeypatch):
    """Mutation guard, mirroring the stdio one in test_human_loop.py: pin that
    the serve arm's answer is the *same* with and without WILLOW_HUMAN_ORCHESTRATOR.
    If serve mode ever starts consulting the env var, the two calls diverge and
    this fails — the serve arm silently becoming the stdio arm is otherwise
    invisible, because the stdio-attested case looks identical."""
    serve("willow")
    _bind("willow")
    with signed_in():
        without = _fn(server.human_attestation_create)(app_id="willow", subject_id="ATOM_E1")
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    with signed_in():
        with_env = _fn(server.human_attestation_create)(app_id="willow", subject_id="ATOM_E2")
    assert without["by_human"] is True
    assert with_env["by_human"] is True


# ── whoami: the same resolution, on the tool that reports identity ───────────

def test_whoami_reports_the_bound_identity_not_the_requested_one(serve):
    """whoami's docstring promises 'in serve mode the app_id comes from your
    OAuth binding' — so it cannot be used to enumerate another app's manifest."""
    serve("privileged", ["full_access"])
    serve("readonly", ["store_read"])
    _bind("readonly")
    with signed_in():
        out = _fn(server.whoami)(app_id="privileged")
    assert out["app_id"] == "readonly"
    assert out["permissions"] == ["store_read"]


def test_whoami_denied_without_a_confirmed_binding(serve):
    serve("privileged", ["full_access"])
    with signed_in():
        out = _fn(server.whoami)(app_id="privileged")
    assert "signed in but not yet bound" in out.get("error", "")
