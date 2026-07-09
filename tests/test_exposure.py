"""Tests for AS-8 exposure membrane (exposure.json + slice resolution)."""

import json

import pytest

from willow_mcp import dispatch as ds
from willow_mcp import exposure as exp
from willow_mcp import home_init as hi
from willow_mcp import paths
from willow_mcp import server


def _write_ratified_seed(home, agent_id: str, **overrides):
    seeds = home / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {"agent_id": agent_id, "kind": "specialist", "display_name": agent_id.title()},
        "seed": {
            "instruction": "One bite.",
            "ratification": {
                "status": "ratified",
                "ratifier_agent_id": "sean",
                "ratified_at": "2026-07-09T00:00:00Z",
            },
        },
        "persona": {
            "register": "formal",
            "voice_rules": ["short"],
            "character": "builder",
            "cast": "secret cast",
        },
        "context": {
            "active_work": "PR stack",
            "session_pattern": "one bite",
            "correction_pattern": "ask first",
            "personal_note": "private",
        },
        "gaps": [],
    }
    data.update(overrides)
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


@pytest.fixture
def reader_app(home):
    app_dir = home / "mcp_apps" / "reader"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["dispatch_read"]})
    )
    return "reader"


def test_default_exposure_config_shape():
    cfg = exp.default_exposure_config()
    assert cfg["format"] == exp.EXPOSURE_FORMAT
    assert cfg["defaults"]["session_enter"] == "work_context"
    assert cfg["agents"]["sean"]["deny_presets"]


def test_home_init_writes_exposure_json(home):
    hi.ensure_home_layout()
    path = paths.exposure_config_path()
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["format"] == exp.EXPOSURE_FORMAT


def test_resolve_preset_global_default(home):
    hi.ensure_home_layout()
    preset, source = exp.resolve_preset("hanuman", "grove")
    assert preset == "voice_only"
    assert source == "defaults.grove"


def test_resolve_preset_per_agent_override(home):
    hi.ensure_home_layout()
    preset, source = exp.resolve_preset("sean", "kb_ingest")
    assert preset == "voice_only"
    assert "sean" in source


def test_apply_slice_voice_only_excludes_cast():
    data = {
        "persona": {"register": "calm", "voice_rules": ["a"], "cast": "secret"},
        "context": {"active_work": "hidden"},
    }
    body = exp.apply_slice(data, "voice_only")
    assert body == {"persona": {"register": "calm", "voice_rules": ["a"]}}


def test_apply_slice_full_alias():
    data = {"format": "agent_seed_v1", "persona": {"register": "x"}}
    body = exp.apply_slice(data, "full")
    assert body["format"] == "agent_seed_v1"


def test_build_exposure_slice_session_enter(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    hi.ensure_home_layout()
    _write_ratified_seed(home, "hanuman")
    out = exp.build_exposure_slice("hanuman", destination="session_enter")
    assert out["ok"] is True
    assert out["preset"] == "work_context"
    assert "active_work" in out["body"].get("context", {})
    assert "cast" not in out["body"].get("persona", {})


def test_build_exposure_slice_custom_fields(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "loki")
    out = exp.build_exposure_slice(
        "loki",
        fields=["persona.register", "context.active_work"],
    )
    assert out["ok"] is True
    assert out["preset"] == "custom"
    assert out["body"]["persona"]["register"] == "formal"
    assert out["body"]["context"]["active_work"] == "PR stack"


def test_preset_denied_operator_full_seed(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    hi.ensure_home_layout()
    _write_ratified_seed(
        home,
        "sean",
        identity={"agent_id": "sean", "kind": "operator"},
    )
    out = exp.build_exposure_slice("sean", preset="full_seed")
    assert out["ok"] is False
    assert out["error"] == "preset_denied"


def test_session_enter_includes_exposure(home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    hi.ensure_home_layout()
    _write_ratified_seed(home, "jeles")
    out = ds.session_enter("jeles", "sess-exp")
    exposure = out.get("agent_seed_exposure")
    assert exposure is not None
    assert exposure["preset"] == "work_context"
    assert "body" in exposure


def test_exposure_config_get_tool(reader_app, home):
    hi.ensure_home_layout()
    out = server.exposure_config_get(reader_app)
    assert out["format"] == exp.EXPOSURE_FORMAT
    assert out["exists"] is True
    assert "defaults" in out["config"]


def test_exposure_slice_tool(reader_app, home, monkeypatch):
    monkeypatch.delenv("WILLOW_PGP_FINGERPRINT", raising=False)
    _write_ratified_seed(home, "ada")
    out = server.exposure_slice(reader_app, "ada", destination="grove")
    assert out["ok"] is True
    assert out["preset"] == "voice_only"
