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
