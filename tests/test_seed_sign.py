"""Tests for willow-mcp-sign-seed CLI (AS-4)."""

import json
from unittest.mock import MagicMock

import pytest

from willow_mcp import pgp
from willow_mcp import seed_sign as ss


def _write_seed(home, agent_id: str, **overrides):
    seeds = home / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": agent_id, "kind": "specialist"},
        "seed": {
            "instruction": "Build.",
            "ratification": {"status": "pending", "ratifier_agent_id": "sean"},
        },
        "persona": {"character": "Builder"},
        "gaps": [],
    }
    data.update(overrides)
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


def test_sign_seed_dry_run(home):
    _write_seed(home, "hanuman")
    out = ss.sign_seed("hanuman", dry_run=True)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["ratification"]["status"] == "ratified"
    assert (home / "seeds" / "hanuman.json").read_text().count("pending") == 1


def test_sign_seed_writes_and_signs(home, monkeypatch):
    _write_seed(home, "loki")
    monkeypatch.setattr(pgp, "sign_detached", lambda p: (True, str(p) + ".sig"))
    monkeypatch.setattr(pgp, "pgp_enabled", lambda: False)
    out = ss.sign_seed("loki")
    assert out["ok"] is True
    assert out["signed"] is True
    data = json.loads((home / "seeds" / "loki.json").read_text())
    assert data["seed"]["ratification"]["status"] == "ratified"
    assert data["seed"]["ratification"]["sig_path"] == "seeds/loki.json.sig"


def test_sign_seed_blocked_in_kart(home, monkeypatch):
    _write_seed(home, "ada")
    monkeypatch.setenv("WILLOW_IN_KART", "1")
    out = ss.sign_seed("ada")
    assert out["ok"] is False
    assert out["signed"] is False
    assert "sandbox" in out["sign_detail"].lower()


def test_sign_detached_calls_gpg(home, monkeypatch):
    monkeypatch.delenv("WILLOW_IN_KART", raising=False)
    path = home / "seeds" / "x.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n")
    mock = MagicMock(returncode=0)
    monkeypatch.setattr(pgp, "subprocess", MagicMock(run=lambda *a, **k: mock))
    ok, detail = pgp.sign_detached(path)
    assert ok is True
    assert str(path) + ".sig" in detail
