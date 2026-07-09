"""Fleet-wide gap backlog: log/list/resolve, dedup, and stopword handling.

willow_mcp.gaps holds a module-level Store() singleton created at import
time (same pattern as server.py's _store — see conftest.py's docstring),
so WILLOW_STORE_ROOT is fixed for the whole test session, not per-test.
Isolation here comes from giving each test its own unique `topic`, the
same way the rest of the suite uses unique app_ids, rather than swapping
WILLOW_STORE_ROOT per test (which the already-imported singleton would
never see).
"""

from __future__ import annotations

from willow_mcp import gaps


def test_log_requires_topic_and_question():
    assert "error" in gaps.log("", "some question")
    assert "error" in gaps.log("topic", "")


def test_log_creates_open_gap():
    result = gaps.log("t-basic", "What is the accent color in Nord?")
    assert result["status"] == "open"
    assert result["asked_count"] == 1


def test_log_repeated_question_bumps_count_not_duplicates():
    gaps.log("t-dedup", "What is the accent color in Nord?")
    gaps.log("t-dedup", "what is the accent color in nord")
    rows = gaps.list_gaps(topic="t-dedup")
    assert len(rows) == 1
    assert rows[0]["asked_count"] == 2


def test_log_same_question_different_topic_is_separate():
    gaps.log("t-cross-a", "What is the primary color?")
    gaps.log("t-cross-b", "What is the primary color?")
    assert len(gaps.list_gaps(topic="t-cross-a")) == 1
    assert len(gaps.list_gaps(topic="t-cross-b")) == 1


def test_list_gaps_ranks_by_asked_count():
    gaps.log("t-rank", "low priority question")
    for _ in range(3):
        gaps.log("t-rank", "high priority question")
    rows = gaps.list_gaps(topic="t-rank")
    assert rows[0]["question"] == "high priority question"
    assert rows[0]["asked_count"] == 3


def test_list_gaps_filters_by_status():
    a = gaps.log("t-status", "What is the accent color in Nord?")
    gaps.log("t-status", "What is the border radius in Grove?")
    gaps.resolve(a["id"])
    open_rows = gaps.list_gaps(topic="t-status", status="open")
    resolved_rows = gaps.list_gaps(topic="t-status", status="resolved")
    assert len(open_rows) == 1
    assert len(resolved_rows) == 1
    assert resolved_rows[0]["question"] == "What is the accent color in Nord?"


def test_resolve_missing_gap_errors():
    assert gaps.resolve("does-not-exist-xyz") == {"error": "not_found"}


def test_resolve_is_bookkeeping_only():
    logged = gaps.log("t-resolve", "question a")
    result = gaps.resolve(logged["id"], note="drafted an answer")
    assert result["status"] == "resolved"
    row = gaps.get(logged["id"])
    assert row["status"] == "resolved"
    assert row["resolution_note"] == "drafted an answer"
    assert row.get("promoted_to") is None


def test_mark_promoted_sets_status_and_target():
    logged = gaps.log("t-promote", "question a")
    gaps.mark_promoted(logged["id"], "KID1234")
    row = gaps.get(logged["id"])
    assert row["status"] == "promoted"
    assert row["promoted_to"] == "KID1234"


def test_resolve_already_promoted_gap_errors():
    logged = gaps.log("t-promote-resolve", "question a")
    gaps.mark_promoted(logged["id"], "KID1234")
    result = gaps.resolve(logged["id"])
    assert result == {"error": "already_promoted", "promoted_to": "KID1234"}


def test_log_after_promoted_reports_promoted_without_reopening():
    logged = gaps.log("t-promote-relog", "question a")
    gaps.mark_promoted(logged["id"], "KID1234")
    result = gaps.log("t-promote-relog", "question a")
    assert result["status"] == "promoted"
    assert result["promoted_to"] == "KID1234"
    row = gaps.get(logged["id"])
    assert row["status"] == "promoted"
