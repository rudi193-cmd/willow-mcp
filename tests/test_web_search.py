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
