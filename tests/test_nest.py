"""Tests for the Nest content pipeline (willow_mcp.nest) and its MCP tools.

The load-bearing test is test_bridge_emits_no_content_names_or_filenames — the
wall. The Nest DB is the local PII zone; the promotion path to the shared KB
must carry *structure* (counts, curated category names, redacted secret kinds)
and never content, person names, or filenames. Mirrors corpus-lens's test_wall
and this repo's test_egress_authorization: the guarantee is asserted, not
assumed.
"""
import json

import pytest

from willow_mcp import gate, server
from willow_mcp.db import Store
from willow_mcp.nest import bridge, classify, db as nest_db, digest
from willow_mcp.receipts import ReceiptLog

# Content planted in a synthetic Nest DB. None of the PII strings below may
# appear in anything the bridge (or the walled digest) emits.
OWNER = "Operator"
PERSON = "Jane Doe"                       # a person who is NOT the owner/subject
FILENAME = "custody-2019-legal.pdf"       # a filename embedding a date + matter
DOC_CONTENT = "The custody arrangement for the minor child is as follows"
NOTE_CONTENT = "Dear diary, today Jane and I finally spoke about the house"
PII_STRINGS = [PERSON, FILENAME, DOC_CONTENT, NOTE_CONTENT]


def _fn(tool):
    """FastMCP wraps @mcp.tool() functions; unwrap to the raw callable."""
    return getattr(tool, "fn", tool)


def _build_nest_db(path):
    """A small canonical Nest DB with known content spanning every surface the
    bridge and digest touch: topical categories, a non-owner person, a secret,
    a dated fragment, and a filename that embeds a date."""
    conn = nest_db.open_db(path)
    nest_db.init_meta(conn, owner=OWNER, description="test fixture")
    sid = nest_db.add_source(conn, _FakePath(FILENAME), mime_hint=".pdf")
    nest_db.update_source_status(conn, sid, "extracted", ocr_method="pdfplumber",
                                 char_count=len(DOC_CONTENT))
    nest_db.add_fragment(conn, source_id=sid, fragment_type="document",
                         content=DOC_CONTENT, label="legal", confidence="likely")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="note",
                         content=NOTE_CONTENT, label="journal", confidence="likely")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="receipt",
                         content="Grand total $45.00", label="financial", confidence="likely")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="person",
                         content=PERSON, confidence="speculative")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="date",
                         content="2019-06-21", date_ref="2019-06-21", confidence="likely")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="secret",
                         content="[REDACTED:github_pat]", label="github_pat",
                         confidence="confirmed")
    conn.commit()
    conn.close()


class _FakePath:
    """add_source hashes the file bytes; the fixture never has a real file, so
    stand in with a name + deterministic pseudo-bytes."""
    def __init__(self, name):
        self.name = name
        self._data = name.encode()

    def __str__(self):
        return f"/nonexistent/{self.name}"


# add_source calls file_hash(path) which opens the path — patch it to hash the
# name instead so the fixture needs no real files on disk.
@pytest.fixture(autouse=True)
def _stub_file_hash(monkeypatch):
    import hashlib
    monkeypatch.setattr(nest_db, "file_hash",
                        lambda p: hashlib.sha256(str(p).encode()).hexdigest()[:16])


# ── the wall ─────────────────────────────────────────────────────────────────

def test_bridge_emits_no_content_names_or_filenames(tmp_path):
    """THE WALL: bridge atoms carry structure only — never fragment content,
    person names, or filenames."""
    db = tmp_path / "seed.db"
    _build_nest_db(db)

    built = bridge.build_bridge(str(db))
    assert built["status"] == "ok"
    atoms = built["atoms"]
    assert atoms, "expected at least the structure overview atom"

    blob = json.dumps(atoms)
    for pii in PII_STRINGS:
        assert pii not in blob, f"wall breach: {pii!r} reached a bridge atom"

    # And it DID carry structure: counts + curated category names + secret kind.
    assert any("legal" in a["summary"] or "legal" in a.get("tags", []) for a in atoms)
    assert any(a["category"] == "nest" for a in atoms)
    assert any("github_pat" in a["summary"] for a in atoms), "secret KIND is structure"


def test_bridge_drops_filename_labels(tmp_path):
    """Regression: the regex classifier labels document/receipt fragments with
    their FILENAME, not a topical category. Those filenames (which embed dates
    and names) must never cross the wall as 'category names' — they're counted
    as uncategorised instead."""
    db = tmp_path / "seed.db"
    conn = nest_db.open_db(db)
    nest_db.init_meta(conn, owner=OWNER)
    sid = nest_db.add_source(conn, _FakePath("x.pdf"), mime_hint=".pdf")
    # regex-fallback shape: label IS the sensitive filename
    nest_db.add_fragment(conn, source_id=sid, fragment_type="document",
                         content="body", label=FILENAME, confidence="uncertain")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="document",
                         content="brief", label="legal", confidence="likely")
    conn.commit()
    conn.close()

    built = bridge.build_bridge(str(db))
    blob = json.dumps(built["atoms"])
    assert FILENAME not in blob                       # filename walled
    assert "legal" in blob                            # real category survives
    assert "uncategorised" in blob                    # dropped one is counted, not hidden
    walled = digest.build_digest(str(db), wall=True)
    assert FILENAME not in walled


def test_walled_digest_omits_names_and_filenames(tmp_path):
    db = tmp_path / "seed.db"
    _build_nest_db(db)
    walled = digest.build_digest(str(db), wall=True)
    for pii in (PERSON, FILENAME):
        assert pii not in walled, f"walled digest leaked {pii!r}"
    assert "legal" in walled  # structure survives


def test_unwalled_digest_includes_name(tmp_path):
    """Guards against a vacuous wall test: the unwalled digest DOES surface the
    name, so the walled test above is really suppressing something."""
    db = tmp_path / "seed.db"
    _build_nest_db(db)
    full = digest.build_digest(str(db), wall=False)
    assert PERSON in full


# ── classifier ───────────────────────────────────────────────────────────────

def test_classifier_deterministic_regex_only():
    text = "Invoice\nGrand total $19.99\nDue on 2020-01-05"
    a = classify.classify(text, filename="receipt.txt", use_llm=False, use_embed=False)
    b = classify.classify(text, filename="receipt.txt", use_llm=False, use_embed=False)
    assert [(f.fragment_type, f.content) for f in a] == \
           [(f.fragment_type, f.content) for f in b]


# ── gate ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    root.mkdir()
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    return root


def _manifest(apps_root, app_id, perms):
    d = apps_root / app_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
    return app_id


def test_nest_read_grants_reads_denies_writes(apps_root):
    _manifest(apps_root, "reader", ["nest_read"])
    assert gate.permitted("reader", "nest_status") is True
    assert gate.permitted("reader", "nest_digest") is True
    assert gate.permitted("reader", "nest_scan") is False
    assert gate.permitted("reader", "nest_promote") is False


def test_nest_write_grants_writes(apps_root):
    _manifest(apps_root, "writer", ["nest_write"])
    assert gate.permitted("writer", "nest_scan") is True
    assert gate.permitted("writer", "nest_promote") is True
    assert gate.permitted("writer", "nest_status") is False  # read not implied


def test_full_access_grants_all_nest_tools(apps_root):
    _manifest(apps_root, "admin", ["full_access"])
    for tool in ("nest_status", "nest_digest", "nest_scan", "nest_promote"):
        assert gate.permitted("admin", tool) is True


# ── tools end-to-end through the _guarded pipeline ───────────────────────────

@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


def test_nest_digest_tool_is_walled_and_gated(tmp_path, mk_app):
    db = tmp_path / "seed.db"
    _build_nest_db(db)
    mk_app("nestapp", ["nest_read"])
    out = _fn(server.nest_digest)("nestapp", db_path=str(db))
    assert out["status"] == "ok" and out["walled"] is True
    assert PERSON not in out["digest"] and FILENAME not in out["digest"]


def test_nest_digest_denied_without_permission(tmp_path, mk_app):
    db = tmp_path / "seed.db"
    _build_nest_db(db)
    mk_app("noperm", ["store_read"])   # has a manifest, but not nest_read
    out = _fn(server.nest_digest)("noperm", db_path=str(db))
    assert "error" in out            # gate denial, not a digest


def test_nest_scan_dry_run_returns_counts_and_writes_nothing(tmp_path, mk_app):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "note.txt").write_text("a short plaintext note about groceries")
    mk_app("scanner", ["nest_write"])
    out = _fn(server.nest_scan)("scanner", folder=str(drop), dry_run=True, use_embed=False)
    assert out["status"] == "ok" and out["dry_run"] is True
    assert out["db_path"] is None
    assert out["counts"]["files"] == 1
    # dry run wrote no DB anywhere under the default home
    assert not list((tmp_path).rglob("seed.db"))


def test_nest_status_walls_filename_labels(tmp_path, mk_app):
    db = tmp_path / "seed.db"
    conn = nest_db.open_db(db)
    nest_db.init_meta(conn, owner=OWNER)
    sid = nest_db.add_source(conn, _FakePath("x.pdf"), mime_hint=".pdf")
    nest_db.add_fragment(conn, source_id=sid, fragment_type="document",
                         content="b", label=FILENAME, confidence="uncertain")
    conn.commit()
    conn.close()
    mk_app("statter", ["nest_read"])
    out = _fn(server.nest_status)("statter", db_path=str(db))
    assert FILENAME not in out["categories"]
    assert out["uncategorised"] == 1


def test_nest_promote_dry_run_returns_structure_only(tmp_path, mk_app):
    db = tmp_path / "seed.db"
    _build_nest_db(db)
    mk_app("promoter", ["nest_write"])
    out = _fn(server.nest_promote)("promoter", db_path=str(db), dry_run=True)
    assert out["status"] == "ok" and out["dry_run"] is True
    assert out["would_promote"] >= 1
    blob = json.dumps(out["atoms"])
    for pii in PII_STRINGS:
        assert pii not in blob, f"wall breach in promote dry-run: {pii!r}"
