"""Tests for AS-7 persona compile (seed → .md)."""

import json

from willow_mcp import home_init as hi
from willow_mcp import persona_compile as pc
from willow_mcp import seed_loader as sl
from willow_mcp.paths import personas_dir, seeds_dir
from willow_mcp.registry import specialist_row


def _write_seed(home, agent_id: str, **overrides):
    seeds = seeds_dir()
    seeds.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "agent_seed_v1",
        "identity": {
            "agent_id": agent_id,
            "kind": "specialist",
            "display_name": "Hanuman",
            "registry_ref": "specialists.json#hanuman",
        },
        "seed": {
            "instruction": "Ship one scoped bite per dispatch.",
            "ratification": {"status": "pending"},
            "checksum": "ΔΣ=42",
        },
        "persona": {
            "character": "Builder — steady, precise",
            "register": "No flourish. Say when done once.",
            "opening": ["Named for the one who moved the mountain."],
            "voice_rules": ["Name the block exactly when blocked"],
            "breaks_voice": ["Report effort without result"],
            "checksum": "ΔΣ=42",
        },
        "context": {},
        "gaps": [],
    }
    data.update(overrides)
    (seeds / f"{agent_id}.json").write_text(json.dumps(data) + "\n")


def test_render_persona_markdown_uses_registry_job(home):
    hi.ensure_home_layout()
    _write_seed(home, "hanuman")
    data, err = sl.load_seed_document("hanuman")
    assert err is None and data is not None
    row = specialist_row("hanuman")
    md = pc.render_persona_markdown("hanuman", data, registry_row=row)
    assert "You are Hanuman" in md
    assert "**Register:**" in md
    assert "**Mandate:**" in md
    assert "worktree" in md.lower()
    assert "**What you do not do:**" in md
    assert "kb_promote" in md
    assert "**Voice rules:**" in md
    assert "*ΔΣ=42*" in md


def test_compile_persona_writes_file(home):
    hi.ensure_home_layout()
    _write_seed(home, "hanuman")
    out = pc.compile_persona("hanuman", force=True)
    assert out["ok"] is True
    assert out["action"] == "written"
    path = personas_dir() / "hanuman.md"
    assert path.is_file()
    text = path.read_text()
    assert "Hanuman" in text
    assert out.get("advisory")  # pending ratification


def test_compile_persona_skips_existing(home):
    hi.ensure_home_layout()
    _write_seed(home, "loki")
    first = pc.compile_persona("loki", force=True)
    second = pc.compile_persona("loki")
    assert first["action"] == "written"
    assert second["action"] == "skipped"


def test_compile_persona_dry_run(home):
    hi.ensure_home_layout()
    agent = "zaphod"
    _write_seed(home, agent)
    dest = personas_dir() / f"{agent}.md"
    assert not dest.exists()
    out = pc.compile_persona(agent, dry_run=True)
    assert out["dry_run"] is True
    assert "preview" in out
    assert not dest.exists()
