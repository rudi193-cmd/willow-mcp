"""DB perimeter (B2) — the operator-signed per-task envelope for `allow_db`.

Pure-crypto tests for the scope-aware envelope: a `database`-scoped envelope
authorizes a `# allow_db` task, and the network/db scopes are cryptographically
non-interchangeable. The submit-time gate in server.task_submit and the
execution-time recheck (ExecutorDbAuthorizer) are exercised under the Postgres
CI matrix; these need no database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from willow_mcp import egress_authorization as auth


@pytest.fixture(autouse=True)
def _outside_kart(monkeypatch):
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)


@pytest.fixture
def keys(tmp_path):
    private = Ed25519PrivateKey.generate()
    priv, pub = tmp_path / "op-private.pem", tmp_path / "op-public.pem"
    priv.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    priv.chmod(0o600)
    pub.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return priv, pub


DB_TASK = auth.canonical_db_task("psql -c 'select 1'")
NET_TASK = auth.canonical_network_task("curl https://example.com")


def _sign(keys, *, task, scope, task_id="DBTASK01", agent="kart", now=None):
    return auth.sign_envelope(
        private_key_path=keys[0], submitted_by="caller", task_id=task_id,
        agent=agent, task=task, ttl_seconds=300,
        nonce="abcdefghijklmnopqrstuvwxyz012345", scope=scope, now=now)


def _verify(keys, envelope, *, task, scope, task_id="DBTASK01", agent="kart", now=None):
    return auth.verify_envelope(
        public_key_path=keys[1], submitted_by="caller", task_id=task_id,
        agent=agent, task=task, envelope=envelope, expected_scope=scope, now=now)


# ── the happy path: a db-scoped envelope authorizes a db task ───────────────────
def test_db_envelope_verifies_for_db_task(keys):
    env = _sign(keys, task=DB_TASK, scope=auth.DB_SCOPE)
    ok, reason, _ = _verify(keys, env, task=DB_TASK, scope=auth.DB_SCOPE)
    assert ok, reason


# ── the load-bearing property: scopes are not interchangeable ───────────────────
def test_network_envelope_cannot_authorize_a_db_task(keys):
    """A `network` envelope presented for a db task is refused — otherwise any
    app holding a routine egress signature could reach Postgres."""
    net_env = _sign(keys, task=NET_TASK, scope=auth.NETWORK_SCOPE)
    ok, reason, _ = _verify(keys, net_env, task=NET_TASK, scope=auth.DB_SCOPE)
    assert not ok and reason == "scope mismatch"


def test_db_envelope_cannot_authorize_a_network_task(keys):
    db_env = _sign(keys, task=DB_TASK, scope=auth.DB_SCOPE)
    # default expected_scope is NETWORK_SCOPE — the net verify path
    ok, reason, _ = auth.verify_envelope(
        public_key_path=keys[1], submitted_by="caller", task_id="DBTASK01",
        agent="kart", task=DB_TASK, envelope=db_env)
    assert not ok and reason == "scope mismatch"


# ── standard envelope integrity carries over to the db scope ────────────────────
def test_task_mutation_breaks_the_db_envelope(keys):
    env = _sign(keys, task=DB_TASK, scope=auth.DB_SCOPE)
    tampered = auth.canonical_db_task("psql -c 'drop table knowledge'")
    ok, reason, _ = _verify(keys, env, task=tampered, scope=auth.DB_SCOPE)
    assert not ok and reason == "task hash mismatch"


def test_expired_db_envelope_is_refused(keys):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    env = _sign(keys, task=DB_TASK, scope=auth.DB_SCOPE, now=past)
    ok, reason, _ = _verify(keys, env, task=DB_TASK, scope=auth.DB_SCOPE)
    assert not ok and reason == "authorization expired"


def test_sign_rejects_unknown_scope(keys):
    with pytest.raises(ValueError, match="unsupported authorization scope"):
        _sign(keys, task=DB_TASK, scope="filesystem")
