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
    registry_path.write_text(json.dumps(registry))
    syscall_path.write_text(json.dumps(table))
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
    roster = tmp_path / "fleet.json"
    roster.write_text(json.dumps({"agents": {"hanuman": "engineer"}}))
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
