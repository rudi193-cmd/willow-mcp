import json
from datetime import datetime, timezone

from willow_mcp import consent, consent_admin, envelopes, fleet_roster
from willow_mcp.governance_ledger import entry_hash


class _Ledger:
    def __init__(self, used=0, final_outcome=None):
        self.used = used
        self.final_outcome = final_outcome
        self.events = []

    def citation_count(self, envelope_id):
        return self.used

    def append_citation(self, project, content, *, max_count):
        self.events.append((project, "envelope_citation", content))
        return "citation-1", self.final_outcome or content["outcome"]


def _charter(tmp_path, *, maximum=2):
    registry = {
        "active": [{
            "id": "env-dispatch",
            "verb_id": 11,
            "verb": "dispatch",
            "grantee": "willow",
            "bounds": {"to_agents": ["hanuman"], "task_class": ["build"]},
            "issued_by": "root",
            "issued_at": "2026-01-01",
            "expires_at": "2027-01-01",
            "max_count": maximum,
            "use_count_source": "frank",
            "status": "active",
        }]
    }
    table = {
        "verbs": [{
            "id": 11,
            "verb": "dispatch",
            "bounds": {"to_agents": "list", "task_class": "string"},
        }]
    }
    registry_path = tmp_path / "pre-approved.json"
    syscall_path = tmp_path / "syscall-table.json"
    tmp_path.chmod(0o700)
    registry_path.write_text(json.dumps(registry))
    syscall_path.write_text(json.dumps(table))
    # §4.6: governance inputs must be operator-owned, non-writable to trust them.
    registry_path.chmod(0o600)
    syscall_path.chmod(0o600)
    return registry_path, syscall_path


def test_envelope_cites_grant_before_return(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path)
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))
    ledger = _Ledger()

    result = envelopes.EnvelopeAuthority(ledger).authorize_and_cite(
        "env-dispatch",
        actor="willow",
        verb="dispatch",
        call_args={"to_agents": "hanuman", "task_class": "build"},
        project="willow",
        session="s1",
    )

    assert result["ok"] is True
    assert result["cited_before_act"] is True
    assert ledger.events[0][2]["outcome"] == "granted"


def test_envelope_exhaustion_and_bounds_mismatch_are_cited(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path, maximum=1)
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))
    ledger = _Ledger(used=1)
    authority = envelopes.EnvelopeAuthority(ledger)

    exhausted = authority.authorize_and_cite(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args={"to_agents": "hanuman", "task_class": "build"},
        project="willow", session="s1",
    )
    mismatch = authority.authorize_and_cite(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args={"to_agents": "opus", "task_class": "build"},
        project="willow", session="s1",
    )

    assert exhausted["errno"] == "EDQUOT"
    assert mismatch["errno"] == "EAMBIG"
    assert [event[2]["outcome"] for event in ledger.events] == ["EDQUOT", "EAMBIG"]


def test_expiry_boundary_is_fail_closed(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path)
    data = json.loads(registry.read_text())
    data["active"][0]["expires_at"] = "2026-07-16T20:00:00+00:00"
    registry.write_text(json.dumps(data))
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))

    result = envelopes.EnvelopeAuthority(_Ledger()).check(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args={"to_agents": "hanuman", "task_class": "build"},
        now=datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
    )
    assert result["errno"] == "EEXPIRED"


def test_atomic_meter_can_refuse_racing_final_use(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path)
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))
    result = envelopes.EnvelopeAuthority(_Ledger(final_outcome="EDQUOT")).authorize_and_cite(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args={"to_agents": "hanuman", "task_class": "build"},
        project="willow", session="s1",
    )
    assert result["ok"] is False
    assert result["errno"] == "EDQUOT"


def test_consent_admin_atomically_reconciles_and_audits(monkeypatch, tmp_path):
    monkeypatch.setattr(consent_admin, "_require_operator_terminal", lambda: None)
    tmp_path.chmod(0o700)
    canonical = tmp_path / "settings.global.json"
    mirror = tmp_path / "consent.json"
    canonical.write_text(json.dumps({"other": 1, "consent": {
        "internet": False, "cloud_llm": False, "lan": False,
    }}))
    canonical.chmod(0o600)
    mirror.write_text(json.dumps({
        "internet": True, "cloud_llm": False, "lan": False,
    }))
    mirror.chmod(0o600)
    monkeypatch.setattr(consent, "settings_path", lambda: canonical)
    monkeypatch.setattr(consent, "legacy_path", lambda: mirror)

    result = consent_admin.set_key("internet", True)

    assert json.loads(canonical.read_text())["other"] == 1
    assert json.loads(mirror.read_text())["internet"] is True
    assert result["reconciled"] is True
    assert "before_hash" in json.loads(
        (tmp_path / "audit" / "consent.jsonl").read_text().splitlines()[0]
    )


def test_roster_loader_rejects_prose_rows(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    roster = tmp_path / "fleet.json"
    roster.write_text(json.dumps({"agents": {"hanuman": "engineer"}}))
    roster.chmod(0o600)
    monkeypatch.setenv("WILLOW_FLEET_ROSTER", str(roster))
    try:
        fleet_roster.load_roster()
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("malformed roster was accepted")


def test_consent_admin_refuses_malformed_or_untrusted_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(consent_admin, "_require_operator_terminal", lambda: None)
    tmp_path.chmod(0o700)
    canonical = tmp_path / "settings.global.json"
    mirror = tmp_path / "consent.json"
    canonical.write_text("{")
    canonical.chmod(0o600)
    monkeypatch.setattr(consent, "settings_path", lambda: canonical)
    monkeypatch.setattr(consent, "legacy_path", lambda: mirror)
    try:
        consent_admin.set_key("internet", True)
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("malformed policy was overwritten")

    canonical.write_text(json.dumps({"consent": {
        "internet": False, "cloud_llm": False, "lan": False,
    }}))
    canonical.chmod(0o666)
    try:
        consent_admin.set_key("internet", True)
    except PermissionError as exc:
        assert "untrusted" in str(exc)
    else:
        raise AssertionError("world-writable policy was accepted")


def test_hash_matches_existing_frank_algorithm():
    assert entry_hash(None, "decision", {"b": 2, "a": 1}) == entry_hash(
        None, "decision", {"a": 1, "b": 2}
    )


# ── §4.6 input authentication (trust root) ───────────────────────────────────

def test_envelope_registry_refused_when_world_writable(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path)
    registry.chmod(0o666)  # anyone can rewrite the grant table → forged envelopes
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))
    result = envelopes.EnvelopeAuthority(_Ledger()).check(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args={"to_agents": "hanuman", "task_class": "build"},
    )
    assert result["ok"] is False
    assert result["errno"] == "EAMBIG"  # untrusted source → fail-closed


def test_roster_refused_when_world_writable(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    roster = tmp_path / "fleet.json"
    roster.write_text(json.dumps({"agents": {"hanuman": {"role": "b", "trust": "t"}}}))
    roster.chmod(0o666)
    monkeypatch.setenv("WILLOW_FLEET_ROSTER", str(roster))
    try:
        fleet_roster.load_roster()
    except PermissionError as exc:
        assert "untrusted" in str(exc)
    else:
        raise AssertionError("world-writable roster was trusted")


# ── §4.3 non-forgeable operator boundary ─────────────────────────────────────

def test_operator_terminal_refused_inside_kart(monkeypatch):
    from willow_mcp import human_session
    monkeypatch.setenv("WILLOW_IN_KART", "1")
    try:
        human_session.require_operator_terminal()
    except PermissionError as exc:
        assert "Kart" in str(exc)
    else:
        raise AssertionError("mutation allowed inside the sandbox")


def test_operator_terminal_refused_without_tty(monkeypatch):
    from willow_mcp import human_session
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    monkeypatch.setattr(human_session.os, "getuid", lambda: 1000)
    import sys as _sys
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    try:
        human_session.require_operator_terminal()
    except PermissionError as exc:
        assert "terminal" in str(exc)
    else:
        raise AssertionError("mutation allowed without an operator terminal")


# ── §4.2 frank_append / envelope_apply behind the human-orchestrator boundary ─

def test_governance_tools_require_human_orchestrator_for_willow(monkeypatch):
    from willow_mcp import human_session
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    for tool in ("frank_append", "envelope_apply"):
        # willow seat, unattested → denied
        denial = human_session.orchestrator_write_denial("willow", tool, serve_mode=False)
        assert denial and "human" in denial.lower()
        # a specialist app is not blocked by the willow boundary (its own
        # capability still gates it) — caller cannot bypass by NOT being willow.
        assert human_session.orchestrator_write_denial("hanuman", tool, serve_mode=False) is None
    # attested host clears it
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    assert human_session.orchestrator_write_denial("willow", "frank_append", serve_mode=False) is None


# ── §4.7 roster sync aborts on a source that changed mid-sync ─────────────────

def test_roster_sync_aborts_if_source_changes(monkeypatch, tmp_path):
    from willow_mcp import human_session
    tmp_path.chmod(0o700)
    roster = tmp_path / "fleet.json"
    roster.write_text(json.dumps({"agents": {"hanuman": {"role": "b", "trust": "t"}}}))
    roster.chmod(0o600)
    monkeypatch.setenv("WILLOW_FLEET_ROSTER", str(roster))
    monkeypatch.setattr(human_session, "require_operator_terminal", lambda: None)

    class _Cur:
        def execute(self, *a, **k): pass
        def fetchall(self): return []
        def close(self): pass
    class _Pg:
        def cursor(self): return _Cur()
        def commit(self): pass

    digests = iter(["digest-A", "digest-B"])  # changes between pin and recheck
    monkeypatch.setattr(fleet_roster, "_roster_digest", lambda: next(digests))
    try:
        fleet_roster.sync(_Pg())
    except RuntimeError as exc:
        assert "changed during sync" in str(exc)
    else:
        raise AssertionError("sync wrote despite the source changing underfoot")


# ── §4.1 chain append retries a lost prev_hash race instead of forking ───────

def test_chain_insert_retries_on_prev_hash_conflict():
    import psycopg2
    from willow_mcp.governance_ledger import GovernanceLedger

    class _Cur:
        def __init__(self, pg): self.pg = pg
        def execute(self, sql, params=None):
            if sql.strip().upper().startswith("INSERT"):
                self.pg.inserts += 1
                if self.pg.inserts == 1:
                    raise psycopg2.IntegrityError("frank_ledger_no_fork")
        def fetchone(self): return ("head-hash",)
        def close(self): pass
    class _Pg:
        def __init__(self): self.inserts = 0; self.commits = 0; self.rollbacks = 0
        def cursor(self): return _Cur(self)
        def commit(self): self.commits += 1
        def rollback(self): self.rollbacks += 1

    pg = _Pg()
    digest = GovernanceLedger(pg)._chain_insert(
        _Cur(pg), "rec-1", "willow", "decision", {"a": 1}
    )
    assert pg.inserts == 2          # first lost the race, second won
    assert pg.rollbacks == 1
    assert pg.commits == 1
    assert digest == entry_hash("head-hash", "decision", {"a": 1})


# ── §4.5 one citation authorizes exactly one bounded act ─────────────────────

def test_one_citation_per_act_and_second_act_needs_second_citation(monkeypatch, tmp_path):
    registry, syscalls = _charter(tmp_path, maximum=1)
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(registry))
    monkeypatch.setenv("WILLOW_SYSCALL_TABLE", str(syscalls))
    args = {"to_agents": "hanuman", "task_class": "build"}

    ledger = _Ledger(used=0)
    authority = envelopes.EnvelopeAuthority(ledger)
    first = authority.authorize_and_cite(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args=args, project="willow", session="s1",
    )
    assert first["ok"] is True
    assert len(ledger.events) == 1                    # exactly one citation for one act

    # the grant is now exhausted (max_count=1); a second act cites and is refused
    ledger.used = 1
    ledger.final_outcome = "EDQUOT"
    second = authority.authorize_and_cite(
        "env-dispatch", actor="willow", verb="dispatch",
        call_args=args, project="willow", session="s1",
    )
    assert second["ok"] is False and second["errno"] == "EDQUOT"
    assert len(ledger.events) == 2                    # a distinct citation, not a replay
