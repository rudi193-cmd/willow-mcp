"""Tests for web_search — DDG parse + search_web."""

from __future__ import annotations

from unittest.mock import patch

from willow_mcp import web_search


def test_parse_ddg_html_extracts_links():
    html = '''
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">Example</a>
    <td class="result__snippet">A snippet here</td>
    '''
    hits = web_search._parse_ddg_html(html, max_results=5)
    assert len(hits) == 1
    assert hits[0]["url"] == "https://example.com/"
    assert hits[0]["title"] == "Example"


def test_search_web_returns_empty_for_blank_query():
    assert web_search.search_web("   ") == []


@patch("willow_mcp.web_search._search_providers")
def test_search_web_delegates_to_providers(mock_providers):
    mock_providers.return_value = [{"title": "T", "url": "https://x.test", "snippet": "",
                                    "source": "x.test", "source_id": "web", "date": "",
                                    "hostname": "x.test"}]
    hits = web_search.search_web("hello", max_results=3, cache=False)
    assert len(hits) == 1
    assert hits[0]["url"] == "https://x.test"


# ── trusted_only was wrong in both directions ────────────────────────────────
#
# `trusted_only=True` is a parameter on the `willow_web_search` MCP tool, so
# this label is handed to a model as a reason to believe a page. It was:
#
#   * spoofable — `host.endswith(suffix)` had no notion of a label boundary, so
#     any registrable domain ending in a trusted string inherited its trust.
#     `evilnature.com`, `notarxiv.org`, `myjstor.org`, `evildp.la` all passed,
#     and every one of those is an open registration anyone can buy.
#   * broken for two of its own entries — `.lstrip("www.")` strips leading
#     *characters* from {w, .}, not the prefix, so `wikipedia.org` became
#     `ikipedia.org` and `wikidata.org` became `ikidata.org`.
#
# The two bugs partly masked each other: `web.archive.org` was mangled to
# `eb.archive.org` and then rescued by the loose `endswith`.


def _old_trusted_host(hostname: str) -> bool:
    """The previous implementation, kept so these tests show a real delta."""
    host = (hostname or "").lower().lstrip("www.")
    if not host:
        return False
    for suffix in web_search._TRUSTED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix) or host.endswith(suffix):
            return True
    return False


def test_a_lookalike_domain_is_not_trusted():
    """The security half. Each of these is an open registration."""
    for host in ("evilnature.com", "notarxiv.org", "myjstor.org", "evildp.la",
                 "attacker-europa.eu", "fakemusicbrainz.org"):
        assert _old_trusted_host(host) is True, f"{host} used to pass"
        assert web_search._trusted_host(host) is False, host


def test_every_listed_suffix_trusts_itself():
    """The correctness half. `wikipedia.org` and `wikidata.org` are on the list
    and were rejected by it."""
    rejected = [s for s in web_search._TRUSTED_SUFFIXES
                if not web_search._trusted_host(s)]
    assert rejected == [], rejected
    assert not _old_trusted_host("wikipedia.org"), "the bug this pins"
    assert web_search._trusted_host("wikipedia.org")


def test_subdomains_and_www_still_match():
    for host in ("www.nature.com", "api.crossref.org", "web.archive.org",
                 "some.dept.edu", "WWW.LOC.GOV", "arxiv.org."):
        assert web_search._trusted_host(host) is True, host


def test_restricted_registries_stay_broadly_trusted():
    """`.gov`, `.edu`, `.ac.uk` and friends are restricted registries — a
    lookalike under them is not something an attacker can register, so the
    broad TLD entries remain a real claim about who registered the name."""
    for host in ("nih.gov", "phishing-nih.gov", "evilvam.ac.uk"):
        assert web_search._trusted_host(host) is True, host


def test_an_empty_or_junk_host_is_not_trusted():
    for host in ("", None, ".", "www.", "localhost"):
        assert web_search._trusted_host(host) is False, host


# ── HALF_OPEN admitted everyone ──────────────────────────────────────────────
#
# `allow()` ended with:
#
#     return True  # HALF_OPEN — allow the single probe
#
# and the comment was the only thing enforcing "single". Every caller arriving
# in HALF_OPEN was let through, so the instant a dead provider's cooldown
# elapsed the whole waiting backlog hit it at once — a thundering herd pointed
# at the one service already known to be failing.


class _Clock:
    """Manual monotonic clock. Time only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tripped(clock, **kw):
    """A breaker sitting in OPEN, one cooldown ago — the next `allow()` moves
    it to HALF_OPEN."""
    cb = web_search.CircuitBreaker(fail_threshold=2, base_cooldown=30.0,
                                   max_cooldown=300.0, clock=clock, **kw)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "OPEN"
    clock.advance(30.0)
    return cb


def test_half_open_admits_one_probe_not_the_whole_backlog():
    clock = _Clock()
    cb = _tripped(clock)

    admitted = sum(cb.allow() for _ in range(50))

    assert cb.state == "HALF_OPEN"
    assert admitted == 1, f"{admitted} of 50 callers got through (was 50 of 50)"


def test_the_probe_reports_back_and_the_breaker_moves():
    """A probe is only useful if its verdict lands. Success closes the breaker;
    failure reopens it with the doubled cooldown."""
    clock = _Clock()
    cb = _tripped(clock)
    assert cb.allow() is True
    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.allow() is True

    clock = _Clock()
    cb = _tripped(clock)
    assert cb.allow() is True
    cb.record_failure()
    assert cb.state == "OPEN"
    # Doubled: 30 -> 60. Still shut at 30s, open for a probe at 60s.
    clock.advance(30.0)
    assert cb.allow() is False
    clock.advance(30.0)
    assert cb.allow() is True


def test_a_second_probe_follows_the_first_once_it_reports():
    """Refusal is per outstanding probe, not per state. A failed probe reopens
    and a later one is admitted; the flag does not accumulate."""
    clock = _Clock()
    cb = _tripped(clock)
    for round_ in range(3):
        assert cb.allow() is True, f"round {round_}: no probe admitted"
        assert cb.allow() is False, f"round {round_}: a second probe got out"
        cb.record_failure()
        clock.advance(cb._cooldown)


def test_a_lost_probe_does_not_wedge_the_breaker_forever():
    """The failure mode this fix could have introduced, and the reason there is
    a deadline. `_search_providers` reports every probe back from
    `except Exception` — which a BaseException walks straight past, returning
    no verdict. A probe with no expiry would then hold this provider at
    "refused" for the life of the process, silently.

    So an unreported probe is treated as lost after one cooldown."""
    clock = _Clock()
    cb = _tripped(clock)
    assert cb.allow() is True          # handed out, and never reported back

    clock.advance(29.0)
    assert cb.allow() is False, "a live probe should still hold the door"

    clock.advance(1.0)
    assert cb.allow() is True, "a lost probe wedged the breaker permanently"
    assert cb.state == "HALF_OPEN"


def test_the_transition_out_of_open_spends_the_probe():
    """The caller that trips OPEN -> HALF_OPEN *is* the probe. If that
    transition did not claim it, the first arrival would take one and the
    second would take another."""
    clock = _Clock()
    cb = _tripped(clock)
    assert cb.state == "OPEN"
    assert cb.allow() is True
    assert cb.state == "HALF_OPEN"
    assert cb.allow() is False


def test_a_closed_breaker_is_never_gated():
    """The probe bookkeeping must not leak into the healthy path."""
    clock = _Clock()
    cb = web_search.CircuitBreaker(fail_threshold=2, base_cooldown=30.0, clock=clock)
    assert all(cb.allow() for _ in range(50))
    cb.record_failure()
    assert cb.state == "CLOSED"
    assert all(cb.allow() for _ in range(50))
