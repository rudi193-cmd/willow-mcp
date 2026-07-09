"""Tests for core.record_lessons() — a journal distilled into one grove ring.

The fixture journal is deliberately shaped like a 2004-era hand-rolled
schema (an `entries` table, a text body, a created date) because that is
exactly the kind of database this function exists to remember.
"""
import sqlite3

import pytest

from willow_mcp import core, the_grove


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_MCP_GROVE_RINGS", raising=False)
    return tmp_path


@pytest.fixture
def journal(tmp_path):
    db = tmp_path / "journal.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, created TEXT, body TEXT)")
    rows = [
        ("2004-03-17", "feeling alone again. the apartment is too quiet."),
        ("2004-04-02", "sketched a database schema for the journal idea"),
        ("2004-06-11", "what should persist? I keep coming back to: remember the why"),
        ("2004-08-30", "ashamed I dropped the project. again."),
        ("2004-11-29", "a good day. laughed a lot. the system design finally clicked."),
    ]
    conn.executemany("INSERT INTO entries (created, body) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def test_record_lessons_distills_a_journal(home, journal):
    result = core.record_lessons(str(journal))
    assert "error" not in result
    assert result["table"] == "entries"
    assert result["entries"] == 5
    assert result["range"] == ["2004-03-17", "2004-11-29"]
    assert result["themes"]["loneliness"] == 1
    assert result["themes"]["systems"] == 2
    assert result["themes"]["what should persist"] == 1
    assert result["themes"]["shame"] == 1
    assert result["themes"]["joy"] == 1
    assert result["lesson"] == core.SEED_LESSON


def test_record_lessons_grows_exactly_one_ring(home, journal):
    assert the_grove.depth() == 0
    result = core.record_lessons(str(journal))
    assert the_grove.depth() == 1
    assert result["depth"] == 1
    ring = the_grove.rings()[0]
    assert ring["lesson"] == core.SEED_LESSON
    assert ring["source"] == "journal.db"
    assert ring["themes"] == result["themes"]
    # the lesson is now a historical invariant
    assert core.SEED_LESSON in the_grove.deep_roots()


def test_record_lessons_honors_a_caller_lesson_and_lexicon(home, journal):
    result = core.record_lessons(
        str(journal),
        themes={"vespas": ("vespa", "scooter")},
        lesson="Some things are technically accurate and that is sufficient.",
    )
    assert result["themes"] == {"vespas": 0}
    assert the_grove.deep_roots() == [
        "Some things are technically accurate and that is sufficient."]


def test_record_lessons_missing_journal_grows_nothing(home, tmp_path):
    result = core.record_lessons(str(tmp_path / "never_kept.db"))
    assert result["error"] == "not_found"
    assert the_grove.depth() == 0


def test_record_lessons_needs_something_written(home, tmp_path):
    db = tmp_path / "numbers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (id INTEGER, value REAL)")
    conn.commit()
    conn.close()
    result = core.record_lessons(str(db))
    assert result["error"] == "no_text_table"
    assert the_grove.depth() == 0


def test_record_lessons_leaves_the_source_untouched(home, journal):
    before = journal.read_bytes()
    core.record_lessons(str(journal))
    assert journal.read_bytes() == before  # opened mode=ro; remembered, not edited
