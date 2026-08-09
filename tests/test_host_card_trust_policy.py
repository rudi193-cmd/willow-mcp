"""The trust policy against jeles' host cards (issue #288).

`_TRUSTED_SUFFIXES`/`_NOT_TRUST_EVIDENCE` used to be the whole story: a flat,
hand-curated list, checked for drift against `jeles.sources.registered_hosts()`
(every host jeles *contacts*, 84 of them) in `test_trusted_sources.py`. That
conflated two different questions — see `web_search.py`'s module comment and
jeles' `docs/design/host-cards.md` — because only 36 of those 84 hosts can ever
be a search-result URL at all; the rest are query-only endpoints or, in
`www.loc.gov`'s case, an XML namespace URI wearing a hostname.

`_card_axis_verdict()` is the narrower check this file exercises: it consults
jeles' card catalog (`jeles.cards`) and decides on the *system-of-record*
axis — measured, not `custody` directly, because "citable iff custody ==
institutional" flips 11 of the 12 `community`-custody hosts this repo has
trusted for years (host-cards.md §4.1). These tests pin that measurement
against whatever jeles is actually installed, so a future jeles release that
changes a card's `roles` or `custody` fails here rather than silently.
"""
from __future__ import annotations

import pytest

from willow_mcp import web_search

cards = pytest.importorskip(
    "jeles.cards", reason="host cards ship in jeles 0.7.0+; older jeles has no "
    "cards module at all, and _card_axis_verdict() degrades to None for every "
    "host in that case — the suffix list alone keeps deciding, unchanged.")


def test_a_card_without_the_citation_role_grants_no_opinion():
    """`www.loc.gov`'s card is `roles: ["namespace", "query"]` — jeles' own
    worked example of the bug this schema exists to name (host-cards.md §1.1).
    The card must not be read as `False`: absence of a detected citation is a
    documented *lower bound* on the static scan, not proof the host is
    uncitable, and this function must never take trust away from a host the
    suffix list grants for its own, independent reason (here: the `.gov` TLD,
    on the Library of Congress's own standing)."""
    card = cards.card("www.loc.gov")
    assert card is not None
    assert "citation" not in card["roles"]
    assert web_search._card_axis_verdict("www.loc.gov") is None
    # And the host stays trusted anyway, via the suffix list, unaffected.
    assert web_search._trusted_host("www.loc.gov")


def test_an_unregistered_host_grants_no_opinion():
    """A host jeles has never heard of (most of the open web) must fall
    straight through to the suffix heuristic rather than being treated as
    "no card means untrusted"."""
    assert cards.card("example.com") is None
    assert web_search._card_axis_verdict("example.com") is None


def test_institutional_custody_citation_hosts_are_trusted():
    """The one direction of the custody axis that IS predictive: a named
    institution holding editorial responsibility for a record is
    definitionally a system of record. Walks every citation-capable card
    jeles actually ships, so it is a live check against installed jeles, not
    a fixed list copied out of a doc."""
    institutional_citation_hosts = [
        h for h in cards.hosts_with_role("citation")
        if cards.card(h)["custody"] == "institutional"
    ]
    assert institutional_citation_hosts, "sanity: jeles should ship at least one"
    for host in institutional_citation_hosts:
        assert web_search._card_axis_verdict(host) is True, host
        assert web_search._trusted_host(host), host


def test_system_of_record_overrides_are_all_citation_capable_non_institutional_hosts():
    """Every name in `_SYSTEM_OF_RECORD_OVERRIDES` should correspond to a real
    jeles card that actually needs a hand decision — a citation-role host
    whose custody is not `institutional` (the one case `_card_axis_verdict`
    cannot decide on its own). An override for a host that no longer needs
    one (jeles reclassified its custody, or dropped the citation role) is a
    stale opinion, the same failure mode `test_trusted_sources.py` guards
    against for the suffix list."""
    for host in web_search._SYSTEM_OF_RECORD_OVERRIDES:
        card = cards.card(host)
        assert card is not None, f"{host}: no longer a jeles card"
        assert "citation" in card["roles"], f"{host}: no longer citation-capable"
        assert card["custody"] != "institutional", (
            f"{host}: now institutional-custody — the override is redundant, "
            "drop it")


def test_system_of_record_overrides_match_the_recorded_verdicts():
    """Locks the actual True/False calls against jeles as installed, so a
    jeles release that adds a new citation-capable host under one of these
    exact hostnames (unlikely, but the whole point of a named list is that it
    is reviewed, not inferred) cannot silently change what this repo believes."""
    for host, expected in web_search._SYSTEM_OF_RECORD_OVERRIDES.items():
        assert web_search._card_axis_verdict(host) is expected, host
        assert web_search._trusted_host(host) is expected, host


def test_thesportsdb_stays_untrusted_despite_a_citation_role():
    """The concrete "genuinely contested call" host-cards.md names: community
    custody, citation-capable, and still not an authority — the card's own
    notes agree ("Explicitly not an authority."). Demonstrates the override
    table overriding what a naive "community => trust it, others get trusted
    too" reading might otherwise assume from the sibling entries."""
    card = cards.card("www.thesportsdb.com")
    assert card is not None
    assert "citation" in card["roles"]
    assert card["custody"] == "community"
    assert web_search._card_axis_verdict("www.thesportsdb.com") is False
    assert not web_search._trusted_host("www.thesportsdb.com")


def test_no_verdict_here_ever_widens_what_the_suffix_list_already_refuses():
    """`_card_axis_verdict` may withhold an opinion (None) or grant one
    (True/False); it must never grant True for a host this repo has
    deliberately excluded with a reason. Cross-checks every
    `_NOT_TRUST_EVIDENCE` entry that also happens to be a jeles card."""
    for domain in web_search._NOT_TRUST_EVIDENCE:
        card = cards.card(domain)
        if card is None:
            continue
        verdict = web_search._card_axis_verdict(domain)
        assert verdict is not True, (
            f"{domain}: card axis says trusted, but it is explicitly excluded "
            "in _NOT_TRUST_EVIDENCE — these must agree")
