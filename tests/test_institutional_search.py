"""`willow_institutional_search` — trust from what was queried, not from a hostname.

This is the tool half of the trusted-source split. `willow_web_search` searches
the open web and makes no claim about what it finds; this searches ~60 *named*
collections and every hit carries `confidence: "institutional"` because a
collection was actually queried.

The distinction is the whole point. `trusted_only` inferred trust from a
hostname suffix, and that inference was wrong in both directions — spoofable by
any lookalike domain, and it rejected two entries on its own list. No suffix
list could have been right: 46 of jeles' 61 sources build their citation URL out
of the API response, so where a result *points* is not knowable in advance.
"""
from __future__ import annotations

import inspect

import pytest

from willow_mcp import gate, server, tier_policy, web_egress

jeles_institutional = pytest.importorskip(
    "jeles.institutional", reason="jeles is a declared runtime dependency")


def _tool():
    """The undecorated function. `@_guarded` runs the gate first — correctly, and
    a test of the body would otherwise only ever see a permission denial."""
    obj = server.willow_institutional_search
    return inspect.unwrap(getattr(obj, "fn", obj))


def _fake(n: int = 25, ok: bool = True, **over):
    out = {
        "hits": [{"title": f"h{i}", "url": f"https://arxiv.org/abs/{i}",
                  "confidence": "institutional", "source_id": "institutional"}
                 for i in range(n)],
        "ok": ok, "lane": "local", "sources_queried": ["arxiv", "pubmed"],
        "failed": [], "skipped": [], "timed_out": [], "unknown": [],
        "total": n, "error": "",
    }
    out.update(over)
    return out


def test_the_tool_is_registered_on_every_gate_it_needs():
    """A tool present in the listing but missing from a registry is either
    unreachable or ungated, and both fail quietly."""
    assert "willow_institutional_search" in gate.PERMISSION_GROUPS["web_read"], \
        "not on the web_net permission line — would be callable without it"
    assert tier_policy.TOOL_CLASS["willow_institutional_search"] == tier_policy.EXECUTE
    assert "willow_institutional_search" in tier_policy.EGRESS_TOOLS, \
        "egress tools are excluded from full_access on purpose; this must be one"


def test_it_sits_on_the_same_permission_line_as_the_other_egress_tools():
    """Deliberately not a softer line. One call fans out across ~60 hosts, so
    this is the *largest* egress surface of the three even though every
    destination is a library or an academic index."""
    web_read = gate.PERMISSION_GROUPS["web_read"]
    assert {"willow_web_search", "willow_web_fetch",
            "willow_institutional_search"} <= set(web_read)


def test_nothing_reaches_the_network_when_the_lease_is_denied(monkeypatch):
    """The check that matters most: a denial must short-circuit *before* the
    fan-out, not filter its results afterwards."""
    called = []
    monkeypatch.setattr(web_egress, "egress_denial",
                        lambda app_id: {"error": "lease_denied: no lease"})
    monkeypatch.setattr(jeles_institutional, "search_institutional",
                        lambda *a, **k: called.append(1) or _fake())

    out = _tool()(app_id="app", query="crispr")
    assert out == {"error": "lease_denied: no lease"}
    assert called == [], "queried the collections despite a denied lease"


def test_max_results_truncates_and_total_still_reports_what_there_was(monkeypatch):
    """jeles' own limit is *per source*, so with ~60 sources the default of 3
    can produce far more hits than `max_results` keeps. Truncating without
    surfacing that would make 'nothing more was found' and 'we stopped looking'
    indistinguishable."""
    monkeypatch.setattr(web_egress, "egress_denial", lambda app_id: None)
    monkeypatch.setattr(jeles_institutional, "search_institutional",
                        lambda *a, **k: _fake(25))

    out = _tool()(app_id="app", query="crispr", max_results=10)
    assert len(out["hits"]) == 10
    assert out["count"] == 10
    assert out["total"] == 25, "the pre-cap count must survive truncation"


def test_the_arguments_reach_jeles_under_the_names_it_actually_uses(monkeypatch):
    """`search_institutional` takes keyword-only `sources_filter` and
    `limit_per_source` — there is no `limit`. Calling it with the wrong names
    raises TypeError on first use, which is a runtime failure no type checker
    here would catch."""
    seen = {}
    monkeypatch.setattr(web_egress, "egress_denial", lambda app_id: None)

    def spy(query, *, sources_filter=None, limit_per_source=3):
        seen.update(query=query, sources_filter=sources_filter,
                    limit_per_source=limit_per_source)
        return _fake(2)

    monkeypatch.setattr(jeles_institutional, "search_institutional", spy)
    _tool()(app_id="app", query="q", sources=["arxiv"], limit_per_source=5)
    assert seen == {"query": "q", "sources_filter": ["arxiv"], "limit_per_source": 5}


def test_a_failed_fan_out_stays_legible(monkeypatch):
    """`ok=False` with no hits means no source completed a look; `ok=True` with
    no hits means the collections had nothing. Collapsing those two into an
    empty list is the failure jeles' own `_verdict` exists to prevent, and this
    tool must not undo it."""
    monkeypatch.setattr(web_egress, "egress_denial", lambda app_id: None)
    monkeypatch.setattr(jeles_institutional, "search_institutional",
                        lambda *a, **k: _fake(0, ok=False, failed=["arxiv"],
                                              error="every source failed"))

    out = _tool()(app_id="app", query="q")
    assert out["ok"] is False
    assert out["hits"] == [] and out["count"] == 0
    assert out["failed"] == ["arxiv"]
    assert out["error"], "an unexplained failure is indistinguishable from an empty shelf"


def test_hits_carry_institutional_confidence(monkeypatch):
    """The reason this tool exists. The label comes from having queried a named
    collection — not from the hostname the result happens to point at."""
    monkeypatch.setattr(web_egress, "egress_denial", lambda app_id: None)
    monkeypatch.setattr(jeles_institutional, "search_institutional",
                        lambda *a, **k: _fake(3))

    out = _tool()(app_id="app", query="q")
    assert all(h["confidence"] == "institutional" for h in out["hits"])
