"""Tests for agent_seed_v1 loader (AS-3)."""

import json

import pytest

from willow_mcp import home_init as hi
from willow_mcp import seed_loader as sl
from willow_mcp import dispatch as ds


def _write_seed(home, agent_id: str, **overrides):
    seeds = home / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": agent_id, "kind": "specialist", "display_name": agent_id.title()},
        "seed": {
            "instruction": "One bite at a time.",
            "ratification": {"status": "pending", "ratifier_agent_id": "sean"},
        },
        "persona": {"character": "Builder voice"},
        "context": {"cognitive_style": "sequential"},
        "gaps": ["example unknown"],
    }
    data.update(overrides)
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


def test_load_missing_seed(home):
    out = sl.load_agent_seed("hanuman")
    assert out["present"] is False
    assert out["reason"] == "no_seed_file"


def test_load_pending_seed(home):
    _write_seed(home, "hanuman")
    out = sl.load_agent_seed("hanuman")
    assert out["present"] is True
    assert out["ratification_status"] == "pending"
    assert out["gaps"] == ["example unknown"]
    assert out["advisory"]
    assert out["excerpt"]["instruction"] == "One bite at a time."


def test_session_enter_includes_agent_seed(home):
    hi.ensure_home_layout()
    _write_seed(home, "hanuman")
    out = ds.session_enter("hanuman", "sess-seed")
    assert out["entry_mode"] == "human"
    seed = out["agent_seed"]
    assert seed["present"] is True
    assert seed["ratification_status"] == "pending"
    assert "persona" in out


def test_pgp_skipped_when_fingerprint_unset(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_seed(
        home,
        "loki",
        seed={
            "instruction": "Audit.",
            "ratification": {"status": "ratified", "ratified_at": "2026-07-09"},
        },
    )
    out = sl.load_agent_seed("loki")
    assert out["present"] is True
    assert out["ratification_status"] == "ratified"
    assert out.get("verify") is None
    assert out.get("trusted") is True


def test_pgp_enforced_when_fingerprint_set(home, monkeypatch):
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", "B" * 40)
    _write_seed(
        home,
        "hanuman",
        seed={
            "instruction": "Build.",
            "ratification": {"status": "ratified", "ratified_at": "2026-07-09"},
        },
    )
    monkeypatch.setattr(sl.pgp, "verify_detached", lambda p: (True, "ok"))
    out = sl.load_agent_seed("hanuman")
    assert out["trusted"] is True
    assert out["verify"]["ok"] is True
