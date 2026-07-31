"""Unit tests for kb_curate tag encoding and enrichment."""

from willow_mcp import kb_curate as kbc


def test_merge_flag_tags_idempotent_marker():
    tags = kbc.merge_flag_tags([], app_id="ada", reason="synthetic demo", severity="high")
    assert kbc.FLAGGED_MARKER in tags
    assert any(t.startswith(kbc.FLAG_PREFIX) for t in tags)
    again = kbc.merge_flag_tags(tags, app_id="ada", reason="updated", severity="low")
    assert again.count(kbc.FLAGGED_MARKER) == 1
    flag, retracted, _ = kbc.parse_curate_tags(again)
    assert flag and flag["severity"] == "low"
    assert not retracted


def test_merge_retract_tags_sets_retracted():
    tags = kbc.merge_retract_tags(["continuity"], app_id="willow", reason="bad atom")
    assert kbc.RETRACT_TAG in tags
    _, retracted, meta = kbc.parse_curate_tags(tags)
    assert retracted and meta["reason"] == "bad atom"


def test_enrich_atom_surfaces_flag_and_retract():
    tags = kbc.merge_retract_tags(
        kbc.merge_flag_tags([], app_id="x", reason="warn", severity="medium"),
        app_id="x",
        reason="gone",
    )
    rec = kbc.enrich_atom({"id": "A1", "tags": tags})
    assert rec["retracted"] is True
    assert rec["kb_flag"]["severity"] == "medium"
    assert rec["kb_retract"]["reason"] == "gone"
