"""Standing operator consent — the outer key of the two-key egress gate.

The property under test: **anything we cannot read as an explicit `true` denies.**
willow-2.0's writer defaults consent to all-True and returns those defaults for a
malformed block; willow-mcp deliberately inverts that. An absent file is not
consent, an unparseable file is not consent, and `"true"` is not `true`.
"""
import json

import pytest

from willow_mcp import consent


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_SETTINGS_GLOBAL", raising=False)
    return tmp_path


def _canonical(home, **con):
    (home / "settings.global.json").write_text(json.dumps({"version": 1, "consent": con}))


def _legacy(home, **con):
    (home / "consent.json").write_text(json.dumps(con))


# ── fail-closed ──────────────────────────────────────────────────────────────

def test_no_policy_at_all_denies(home):
    out = consent.read_consent()
    assert out["consent"] == {"internet": False, "cloud_llm": False, "lan": False}
    assert out["source"] == "none"
    assert out["status"] == "warn"
    assert consent.internet_permitted() is False


def test_unparseable_canonical_denies(home):
    (home / "settings.global.json").write_text("{ not json")
    out = consent.read_consent()
    assert out["status"] == "fail"
    assert out["consent"]["internet"] is False
    assert consent.internet_permitted() is False


def test_unparseable_canonical_does_not_fall_back_to_permissive_legacy(home):
    """A corrupt policy must never be replaced by an older, laxer one."""
    (home / "settings.global.json").write_text("{ not json")
    _legacy(home, internet=True, cloud_llm=True, lan=True)
    assert consent.read_consent()["status"] == "fail"
    assert consent.internet_permitted() is False


def test_truthy_non_bool_is_not_consent(home):
    """`is True` on purpose: 1, "true", "yes" are not an operator saying yes."""
    for value in ("true", "yes", 1, [1], {"a": 1}):
        _canonical(home, internet=value, cloud_llm=True, lan=True)
        assert consent.internet_permitted() is False, f"{value!r} was accepted as consent"


def test_missing_key_denies_that_key(home):
    _canonical(home, cloud_llm=True)
    out = consent.read_consent()
    assert out["consent"] == {"internet": False, "cloud_llm": True, "lan": False}


def test_explicit_true_permits(home):
    _canonical(home, internet=True, cloud_llm=True, lan=False)
    assert consent.internet_permitted() is True
    assert consent.permitted("lan") is False


def test_unknown_key_denies(home):
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    assert consent.permitted("root_access") is False


# ── precedence: canonical wins; legacy only when canonical is absent ──────────

def test_canonical_wins_over_legacy(home):
    """Mirrors load_global_settings(): legacy is imported only on first load."""
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    _legacy(home, internet=False, cloud_llm=False, lan=False)
    out = consent.read_consent()
    assert out["source"] == "canonical"
    assert consent.internet_permitted() is True


def test_legacy_used_only_when_canonical_absent(home):
    _legacy(home, internet=True, cloud_llm=True, lan=True)
    out = consent.read_consent()
    assert out["source"] == "legacy"
    assert consent.internet_permitted() is True


def test_settings_global_env_override_is_honoured(home, tmp_path, monkeypatch):
    elsewhere = tmp_path / "other.json"
    elsewhere.write_text(json.dumps({"consent": {"internet": True}}))
    monkeypatch.setenv("WILLOW_SETTINGS_GLOBAL", str(elsewhere))
    assert consent.settings_path() == elsewhere
    assert consent.internet_permitted() is True


# ── disagreement is surfaced, never resolved ─────────────────────────────────

def test_disagreement_is_reported_not_resolved(home):
    """The live bug: consent.json says off, settings.global.json says on."""
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    _legacy(home, internet=False, cloud_llm=True, lan=False)
    out = consent.read_consent()
    assert out["disagreement"]["keys"] == ["internet", "lan"]
    assert out["disagreement"]["canonical"] == {"internet": True, "lan": True}
    assert out["disagreement"]["legacy"] == {"internet": False, "lan": False}
    # canonical still governs — reporting the conflict does not change the answer
    assert consent.internet_permitted() is True


def test_agreement_reports_no_disagreement(home):
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    _legacy(home, internet=True, cloud_llm=True, lan=True)
    assert consent.read_consent()["disagreement"] is None


def test_a_key_only_one_file_declares_is_not_a_disagreement(home):
    """Caught by the e2e: a file that omits a key is silent on it, not in conflict.

    The omitted key is still *denied* for gating — absence is not consent — but
    reporting it as a conflict sends the operator hunting a disagreement that does
    not exist.
    """
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    _legacy(home, internet=True)  # says nothing about cloud_llm / lan
    out = consent.read_consent()
    assert out["disagreement"] is None


def test_partial_legacy_still_denies_its_undeclared_keys_when_it_governs(home):
    _legacy(home, internet=True)  # no canonical file, so legacy governs
    out = consent.read_consent()
    assert out["source"] == "legacy"
    assert out["consent"] == {"internet": True, "cloud_llm": False, "lan": False}


def test_consent_module_never_writes(home):
    """willow-mcp is a consumer of this policy. A gate that writes the policy it
    is checked against is not a gate."""
    _canonical(home, internet=True, cloud_llm=True, lan=True)
    before = sorted(p.name for p in home.iterdir())
    consent.read_consent()
    consent.internet_permitted()
    assert sorted(p.name for p in home.iterdir()) == before


# ── diagnostic_summary rollup ────────────────────────────────────────────────

def test_disagreement_is_an_error_problem():
    from willow_mcp import server
    con = {"canonical_path": "/c.json", "legacy_path": "/l.json", "status": "ok",
           "disagreement": {"keys": ["internet"],
                            "canonical": {"internet": True},
                            "legacy": {"internet": False}}}
    problems = server._derive_problems({}, {}, {}, "stdio", None, con)
    assert [p["check"] for p in problems] == ["consent"]
    assert problems[0]["severity"] == "error"
    assert server._derive_verdict(problems) == "broken"


def test_unreadable_consent_is_an_error_problem():
    from willow_mcp import server
    con = {"canonical_path": "/c.json", "status": "fail", "error": "unparseable: x"}
    problems = server._derive_problems({}, {}, {}, "stdio", None, con)
    assert problems[0]["check"] == "consent"
    assert problems[0]["severity"] == "error"


def test_consent_off_is_not_a_problem():
    """Egress switched off is the switch working, not an install defect."""
    from willow_mcp import server
    con = {"status": "ok", "source": "canonical", "disagreement": None,
           "consent": {"internet": False, "cloud_llm": True, "lan": False}}
    assert server._derive_problems({}, {}, {}, "stdio", None, con) == []


def test_derive_problems_consent_arg_is_optional():
    from willow_mcp import server
    assert server._derive_problems({}, {}, {}, "stdio") == []
