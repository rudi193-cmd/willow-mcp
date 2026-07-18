"""The lineage seed pack must stay recordable — every atom passes Lineage.record's
discipline (a rationale AND at least one evidence citation), slugs are unique, and
edge targets that name another atom actually resolve. This guards the content
pack from rotting as atoms are added, without touching a live store.
"""
import importlib.util
from pathlib import Path

import pytest

from willow_mcp.db import Store
from willow_mcp.lineage import Lineage

_PACK = Path(__file__).resolve().parents[1] / "seed" / "lineage_willow.py"
_spec = importlib.util.spec_from_file_location("lineage_willow", _PACK)
pack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pack)

_ATOM_IDS = {a["id"] for a in pack.ATOMS}
_EDGE_KEYS = ("supersedes", "derived_from", "motivated_by")


def test_slugs_are_unique():
    ids = [a["id"] for a in pack.ATOMS]
    assert len(ids) == len(set(ids)), "duplicate atom slug in the seed pack"


@pytest.mark.parametrize("atom", pack.ATOMS, ids=lambda a: a["id"])
def test_every_atom_records_cleanly(atom, tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    lin = Lineage(Store())
    out = lin.record(**atom)
    assert not out.get("error"), f"{atom['id']} refused: {out}"
    assert out["recorded"] is True


def test_edge_targets_that_name_an_atom_resolve():
    # Edge targets may be external, but any that LOOKS like one of our slugs must
    # actually be one — catches a typo'd derived_from/supersedes reference.
    for atom in pack.ATOMS:
        for key in _EDGE_KEYS:
            for target in (atom.get(key) or []):
                # external ids are allowed; only flag near-miss internal refs
                if target not in _ATOM_IDS and "-" in target and target.islower():
                    # heuristic: our slugs are lowercase-hyphenated; a hyphenated
                    # lowercase target not in the set is almost certainly a typo
                    assert target in _ATOM_IDS, (
                        f"{atom['id']}.{key} -> {target!r} is not a known atom slug")


def test_full_pack_seeds_and_is_queryable(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    lin = Lineage(Store())
    for atom in pack.ATOMS:
        lin.record(**atom)
    # the supersedes edge produces a real chain + archives the old atom
    why = lin.why("h1-per-call-signed")
    assert "appid-only-binding" in [c["id"] for c in why["supersedes_chain"]]
    assert lin.why("appid-only-binding")["atom"]["is_current"] is False
    # re-seeding does not duplicate (idempotent by slug / composite edge id)
    before = len(lin.list_atoms())
    for atom in pack.ATOMS:
        lin.record(**atom)
    assert len(lin.list_atoms()) == before
