"""Tests for SOIL seed mirror (AS-5)."""

import json

import pytest

from willow_mcp import seed_loader as sl
from willow_mcp import seed_mirror as sm
from willow_mcp import server
from willow_mcp.db import Store


def _write_ratified_seed(home, agent_id: str, *, status: str = "ratified"):
    seeds = home / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": agent_id, "kind": "specialist"},
        "seed": {
            "instruction": "One bite.",
            "ratification": {
                "status": status,
                "ratifier_agent_id": "sean",
                "ratified_at": "2026-07-09T00:00:00Z",
                "sig_path": f"seeds/{agent_id}.json.sig",
            },
        },
        "persona": {"register": "formal", "voice_rules": ["short"], "character": "x"},
        "context": {"active_work": "PR stack", "correction_pattern": "ask first"},
        "gaps": [],
    }
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


@pytest.fixture
def mirror_app(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    app_dir = home / "mcp_apps" / "willow"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["orchestrator"], "store_scope": ["willow_*"]})
    )
    return "willow"


def test_apply_slice_voice_only():
    data = {
        "persona": {"register": "calm", "voice_rules": ["a"], "cast": "secret"},
        "context": {"active_work": "hidden"},
    }
    body = sm.apply_slice(data, "voice_only")
    assert body == {"persona": {"register": "calm", "voice_rules": ["a"]}}


def test_mirror_rejects_pending(home):
    _write_ratified_seed(home, "hanuman", status="pending")
    out = sm.build_mirror_record("hanuman")
    assert out["ok"] is False
    assert out["error"] == "seed_not_ratified"


def test_mirror_full_record(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "hanuman")
    out = sm.build_mirror_record("hanuman", slice_name="full")
    assert out["ok"] is True
    assert out["record"]["_mirror_of"] == "seeds/hanuman.json"
    assert out["record"]["body"]["format"] == "agent_seed_v1"


def test_mirror_to_store(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "jeles")
    store = Store()
    out = sm.mirror_seed_to_store(store, "jeles")
    assert out["ok"] is True
    assert out["collection"] == sm.MIRROR_COLLECTION
    item = store.get(sm.MIRROR_COLLECTION, "jeles")
    assert item["_slice"] == "full"


def test_agent_seed_mirror_tool(mirror_app, home):
    _write_ratified_seed(home, "loki")
    out = server.agent_seed_mirror(mirror_app, "loki", slice="work_context")
    assert out["ok"] is True
    assert out["slice"] == "work_context"
    assert out["record_id"] == "loki__work_context"


def test_mirror_denied_when_pgp_verify_fails(home, monkeypatch):
    _write_ratified_seed(home, "ada")
    monkeypatch.setenv("WILLOW_PGP_FINGERPRINT", "A" * 40)
    monkeypatch.setattr(
        sl.pgp,
        "verify_detached",
        lambda p: (False, "bad sig"),
    )
    loaded = sl.load_agent_seed("ada")
    assert loaded["trusted"] is False
    out = sm.build_mirror_record("ada")
    assert out["error"] == "seed_signature_invalid"
