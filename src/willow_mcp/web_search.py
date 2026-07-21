"""General web search — DuckDuckGo HTML scrape + navigational map handoffs."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import random
import re
import time
from collections import OrderedDict
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

log = logging.getLogger("willow_mcp.web_search")

_USER_AGENT = "Mozilla/5.0 (compatible; Willow-mcp/2.0; +https://github.com/rudi193-cmd/willow-mcp)"
_DDG_URL = "https://html.duckduckgo.com/html/"
_LINK_RE = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIP_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|td|span|div)>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")

# Hostname suffixes for trusted-source filtering.
# Covers all sources registered in core/jeles_sources.py SOURCES dict.
_TRUSTED_SUFFIXES = (
    # Broad TLD catches (.gov, .edu, .museum, .go.jp for NDL, .ac.uk for CORE)
    "gov", "edu", "museum", "go.jp", "ac.uk",
    # Already-present institutions
    "si.edu", "loc.gov", "archive.org", "louvre.fr", "nasa.gov", "nih.gov",
    "unesco.org", "europeana.eu", "metmuseum.org", "vam.ac.uk", "britishmuseum.org",
    "nature.com", "jstor.org", "wikipedia.org", "stanford.edu", "britannica.com",
    # Academic / open-access repositories
    "openalex.org", "crossref.org", "europepmc.org", "semanticscholar.org",
    "arxiv.org", "zenodo.org", "datacite.org", "doaj.org", "openaire.eu",
    "base-search.net", "dblp.org",
    # Reference / encyclopedic
    "wikidata.org", "eol.org",
    # Museums / cultural heritage
    "clevelandart.org", "rijksmuseum.nl",
    # Libraries / archives
    "openlibrary.org", "gutenberg.org", "biodiversitylibrary.org",
    "dp.la", "bnf.fr", "archives-ouvertes.fr", "hal.science",
    # International
    "scielo.org", "europa.eu",
    # Music
    "musicbrainz.org",
    # Species / ecology / geography
    "gbif.org", "inaturalist.org", "openstreetmap.org",
    # Law
    "courtlistener.com",
    # Clinical trade press / science misc
    "psychiatrictimes.com", "improbable.com",
)


def _hostname(url: str) -> str:
    try:
        return urlparse(url).netloc or "web"
    except Exception:
        return "web"


def _strip_tags(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _unwrap_ddg(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            if qs.get("uddg"):
                return unquote(qs["uddg"][0])
        except Exception:
            pass
    return href


def _trusted_host(hostname: str) -> bool:
    host = (hostname or "").lower().lstrip("www.")
    if not host:
        return False
    for suffix in _TRUSTED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix) or host.endswith(suffix):
            return True
    return False


def navigational_handoffs(query: str) -> list[dict[str, Any]]:
    """Synthetic map/search URLs for local/navigational queries."""
    q = query.strip()
    if not q:
        return []
    enc = quote_plus(q)
    return [
        {
            "title": f"OpenStreetMap: {q}",
            "url": f"https://www.openstreetmap.org/search?query={enc}",
            "snippet": "Search OpenStreetMap for places matching your query.",
            "source": "OpenStreetMap",
            "source_id": "maps_osm",
            "date": "",
            "hostname": "openstreetmap.org",
        },
        {
            "title": f"Google Maps: {q}",
            "url": f"https://www.google.com/maps/search/{enc}",
            "snippet": "Open Google Maps with this search.",
            "source": "Google Maps",
            "source_id": "maps_google",
            "date": "",
            "hostname": "google.com",
        },
        {
            "title": f"Web search: {q}",
            "url": f"https://duckduckgo.com/?q={enc}",
            "snippet": "Full DuckDuckGo results in your browser.",
            "source": "DuckDuckGo",
            "source_id": "web_ddg",
            "date": "",
            "hostname": "duckduckgo.com",
        },
    ]


class SearchError(Exception):
    """Base class for provider search failures."""


class TransientSearchError(SearchError):
    """Retryable failure — rate limit, 5xx, connection error, timeout."""


class HardBlockError(SearchError):
    """Non-retryable block (403/407) — retrying the same path won't help."""


# HTTP status classification for retry vs. hard-block decisions.
_RETRYABLE_STATUS = frozenset({429, 503, 504})
_HARD_BLOCK_STATUS = frozenset({403, 407})


def _parse_ddg_html(text: str, max_results: int) -> list[dict[str, Any]]:
    """Parse DuckDuckGo HTML into result dicts."""
    links = _LINK_RE.findall(text)
    snippets = _SNIP_RE.findall(text)
    hits: list[dict[str, Any]] = []
    for idx, (href, title_html) in enumerate(links[: max_results + 4]):
        url = _unwrap_ddg(href)
        if not url or "duckduckgo.com" in url:
            continue
        title = _strip_tags(title_html) or url
        snippet = _strip_tags(snippets[idx]) if idx < len(snippets) else ""
        host = _hostname(url)
        hits.append(
            {
                "title": title[:200],
                "url": url,
                "snippet": snippet[:400],
                "source": host,
                "source_id": "web",
                "date": "",
                "hostname": host,
            }
        )
        if len(hits) >= max_results:
            break
    return hits


# Below this body size a 200-OK page with 0 parsed links is treated as a genuine
# empty/blocked response, not a structure change. A real DDG results page is tens
# of KB; a "no results"/interstitial page is small.
_PARSER_MISS_MIN_BODY = 2000


def _looks_like_results_page(html_text: str) -> bool:
    """Heuristic: did DDG return a substantial results-style page (vs. an empty
    or interstitial one)? Used to flag a parser miss as likely HTML drift rather
    than a legitimately empty result set."""
    body = html_text or ""
    if len(body) < _PARSER_MISS_MIN_BODY:
        return False
    return "result" in body.lower()


def _ddg_fetch(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """Fetch + parse DuckDuckGo HTML, raising typed errors on failure.

    Raises TransientSearchError (retryable) for timeouts, connection errors,
    and 429/503/504; HardBlockError for 403/407; SearchError for other HTTP
    failures. Used by the provider chain so retry/circuit-breaker logic can
    distinguish failure classes. `ddg_html_search()` wraps this and swallows.

    A 200-OK results-style page that parses to 0 links is logged as a
    `parser_miss` (likely DDG HTML structure drift) — detection only; the call
    still returns [] and the chain's retry/fallback handle the empty result.
    """
    q = query.strip()
    if not q:
        return []
    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": q, "b": "", "kl": "us-en"},
            headers={"User-Agent": _USER_AGENT},
            timeout=12,
        )
    except requests.Timeout as exc:
        raise TransientSearchError(f"timeout: {exc}") from exc
    except requests.ConnectionError as exc:
        raise TransientSearchError(f"connection error: {exc}") from exc
    except requests.RequestException as exc:
        raise SearchError(f"request failed: {exc}") from exc

    status = resp.status_code
    if status in _HARD_BLOCK_STATUS:
        raise HardBlockError(f"hard block (HTTP {status})")
    if status in _RETRYABLE_STATUS:
        raise TransientSearchError(f"retryable (HTTP {status})")
    if status >= 400:
        raise SearchError(f"HTTP {status}")

    hits = _parse_ddg_html(resp.text, max_results)
    if not hits and _looks_like_results_page(resp.text):
        _log_search_event(
            query_hash=_query_hash(q), provider="ddg_html", status="parser_miss",
            result_count=0, body_bytes=len(resp.text), cache_hit=False,
        )
        log.warning(
            "ddg parser miss — HTTP 200, %d-byte results-like body, 0 links parsed; "
            "DDG HTML structure may have changed (_LINK_RE)", len(resp.text),
        )
    return hits


def ddg_html_search(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """Fetch DuckDuckGo HTML results (no API key).

    Back-compat surface: never raises — returns [] on any error. The provider
    chain calls `_ddg_fetch()` directly so it can see typed failures; direct
    callers of this function keep the original swallow-and-return-[] contract.
    """
    try:
        return _ddg_fetch(query, max_results=max_results)
    except SearchError as exc:
        log.warning("ddg search failed: %s", exc)
        return []
    except Exception as exc:  # pragma: no cover - defensive catch-all
        log.warning("ddg search failed: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# Provider seam
#
# `search_web()` historically conflated "search" with "DuckDuckGo HTML scrape."
# The seam below separates the two without changing default behavior: the
# default provider chain is `[DDGHtmlProvider]`, so an unconfigured call returns
# exactly what `ddg_html_search()` returned before. Additional providers
# (Brave/Bing/SerpAPI) slot in via `WILLOW_SEARCH_PROVIDER_ORDER` once their
# implementations land — DDG stays the default and last-resort fallback.
# --------------------------------------------------------------------------- #


@runtime_checkable
class SearchProvider(Protocol):
    """A pluggable search backend returning Willow's standard result dicts."""

    name: str

    def available(self) -> bool:
        """Cheap readiness/credential check — False means skip without calling."""
        ...

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Return result dicts (title/url/snippet/source/source_id/date/hostname)."""
        ...


class DDGHtmlProvider:
    """Current implementation — DuckDuckGo HTML scrape, no API key required.

    Default primary provider and the last-resort fallback for the chain.
    """

    name = "ddg_html"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        # Calls the raising fetch (not ddg_html_search) so the chain's retry +
        # circuit-breaker layer can distinguish transient from hard failures.
        return _ddg_fetch(query, max_results=max_results)


class BraveSearchProvider:
    """Brave Search JSON API provider — key-gated seam stub.

    Phase 1 ships the seam only: the class is present and discoverable but is
    not in the default chain, and `available()` stays False until both an API
    key is configured and the real call is implemented in a follow-up. Wiring
    it early (setting BRAVE_API_KEY) cannot change behavior because `available()`
    gates on `_IMPLEMENTED` as well.
    """

    name = "brave"
    _IMPLEMENTED = False

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("BRAVE_API_KEY", "")

    def available(self) -> bool:
        return self._IMPLEMENTED and bool(self._api_key)

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        # Real Brave call lands in the provider-implementation follow-up.
        log.debug("brave provider not yet implemented — returning []")
        return []


# Registry of constructable providers by name. Factories are nullary so the
# chain can be (re)built per call without shared mutable state.
_PROVIDER_FACTORY: dict[str, Any] = {
    "ddg_html": DDGHtmlProvider,
    "brave": BraveSearchProvider,
}

_DEFAULT_PROVIDER_ORDER = "ddg_html"


def _provider_order() -> list[str]:
    """Provider chain from env (`WILLOW_SEARCH_PROVIDER_ORDER`), DDG by default."""
    raw = os.getenv("WILLOW_SEARCH_PROVIDER_ORDER", _DEFAULT_PROVIDER_ORDER)
    return [name.strip() for name in raw.split(",") if name.strip()]


def build_providers(order: list[str] | None = None) -> list[SearchProvider]:
    """Construct the provider chain in priority order, skipping unknown names."""
    providers: list[SearchProvider] = []
    for name in order or _provider_order():
        factory = _PROVIDER_FACTORY.get(name)
        if factory is None:
            log.warning("unknown search provider %r — skipping", name)
            continue
        providers.append(factory())
    return providers


# --------------------------------------------------------------------------- #
# Retry + circuit breaker
#
# The old code made one attempt and silently returned [] on any error. The
# retry layer recovers from transient failures (rate limits, 5xx, timeouts)
# within a bounded budget; the per-provider circuit breaker fast-fails a
# provider that is consistently down so the chain advances without waiting.
# --------------------------------------------------------------------------- #


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _retry_config() -> dict[str, float]:
    return {
        "max_attempts": _env_int("WILLOW_SEARCH_MAX_ATTEMPTS", 3),
        "budget": _env_float("WILLOW_SEARCH_RETRY_BUDGET", 15.0),
        "base_backoff": _env_float("WILLOW_SEARCH_BACKOFF_BASE", 1.0),
    }


def _with_retry(
    fn,
    *,
    max_attempts: int | None = None,
    budget: float | None = None,
    base_backoff: float | None = None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Call `fn`, retrying on TransientSearchError with exponential backoff.

    Backoff is jittered (delay in [d, 2d] where d = base * 2**(attempt-1)) and
    the whole sequence is capped by a total time budget. HardBlockError and any
    other exception propagate immediately — only transient errors are retried.
    """
    cfg = _retry_config()
    max_attempts = int(cfg["max_attempts"] if max_attempts is None else max_attempts)
    budget = cfg["budget"] if budget is None else budget
    base = cfg["base_backoff"] if base_backoff is None else base_backoff
    start = clock()
    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return fn()
        except TransientSearchError as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            d = base * (2 ** (attempt - 1))
            delay = random.uniform(d, 2 * d)
            if (clock() - start) + delay > budget:
                log.info("retry budget exhausted after attempt %d: %s", attempt, exc)
                break
            log.info("search retry %d/%d in %.1fs: %s", attempt, max_attempts, delay, exc)
            sleep(delay)
    raise last_exc if last_exc is not None else SearchError("retry exhausted")


class CircuitBreaker:
    """Per-provider circuit breaker: CLOSED → OPEN → HALF_OPEN.

    Trips OPEN after `fail_threshold` consecutive failures and fast-fails for a
    cooldown that doubles each time a half-open probe fails (capped at
    `max_cooldown`). A success resets it fully.
    """

    def __init__(
        self,
        fail_threshold: int = 5,
        base_cooldown: float = 30.0,
        max_cooldown: float = 300.0,
        clock=time.monotonic,
    ) -> None:
        self._threshold = fail_threshold
        self._base_cooldown = base_cooldown
        self._max_cooldown = max_cooldown
        self._clock = clock
        self.state = "CLOSED"
        self._failures = 0
        self._opened_at: float | None = None
        self._cooldown = base_cooldown

    def allow(self) -> bool:
        """Whether a request may proceed now."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self._opened_at is not None and (self._clock() - self._opened_at) >= self._cooldown:
                self.state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN — allow the single probe

    def record_success(self) -> None:
        self.state = "CLOSED"
        self._failures = 0
        self._opened_at = None
        self._cooldown = self._base_cooldown

    def record_failure(self) -> None:
        if self.state == "HALF_OPEN":
            # Probe failed — reopen with a longer cooldown.
            self._cooldown = min(self._cooldown * 2, self._max_cooldown)
            self.state = "OPEN"
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self.state = "OPEN"
            self._opened_at = self._clock()


_BREAKERS: dict[str, CircuitBreaker] = {}


def _get_breaker(name: str) -> CircuitBreaker:
    cb = _BREAKERS.get(name)
    if cb is None:
        cb = CircuitBreaker(
            fail_threshold=_env_int("WILLOW_SEARCH_CB_THRESHOLD", 5),
            base_cooldown=_env_float("WILLOW_SEARCH_CB_COOLDOWN", 30.0),
            max_cooldown=_env_float("WILLOW_SEARCH_CB_MAX_COOLDOWN", 300.0),
        )
        _BREAKERS[name] = cb
    return cb


def reset_circuit_breakers() -> None:
    """Clear all circuit-breaker state (test helper / operator reset)."""
    _BREAKERS.clear()


# --------------------------------------------------------------------------- #
# Structured logging
#
# One structured record per search outcome on the existing `willow_mcp.web_search` logger.
# Privacy: the raw query never appears — only a `query_hash` (so cache hits and
# provider attempts for the same query correlate without leaking the text).
# Right-sized for single-host local-first: a single JSON line on the logger we
# already run, NOT a Prometheus/metrics sink (the spec's metrics surface and
# proxy_id/proxy_tier fields don't fit — there is no proxy fleet).
# --------------------------------------------------------------------------- #


def _query_hash(query: str) -> str:
    """Stable short hash of the normalized query — for logs, never the raw text."""
    norm = " ".join((query or "").lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def _log_search_event(**fields: Any) -> None:
    """Emit one structured, privacy-safe `web_search` record on willow_mcp.web_search."""
    record = {"event": "web_search", **fields}
    log.info("web_search %s", json.dumps(record, sort_keys=True))


class _AttemptCounter:
    """Wrap a nullary call and count invocations (retry attempts).

    Module-level (not a per-iteration closure) so the provider chain can read
    `.attempts` after `_with_retry` returns without a loop-binding lint trap.
    """

    def __init__(self, fn) -> None:
        self._fn = fn
        self.attempts = 0

    def __call__(self):
        self.attempts += 1
        return self._fn()


def _search_providers(
    query: str,
    max_results: int,
    providers: list[SearchProvider] | None = None,
) -> list[dict[str, Any]]:
    """Run the provider chain, advancing on unavailable/open/empty/error.

    Each provider call is retried on transient failure within the retry budget
    and gated by its circuit breaker. The chain resets per query; each advance
    is logged with a reason. Returns the first non-empty result set, or [] if
    every provider is exhausted.
    """
    chain = build_providers() if providers is None else providers
    qhash = _query_hash(query)
    for provider in chain:
        breaker = _get_breaker(provider.name)
        counter = _AttemptCounter(lambda p=provider: p.search(query, max_results))
        start = time.monotonic()
        try:
            if not provider.available():
                log.debug("provider %s unavailable — advancing", provider.name)
                continue
            if not breaker.allow():
                log.info("provider %s circuit open — advancing", provider.name)
                continue
            results = _with_retry(counter)
        except SearchError as exc:
            breaker.record_failure()
            _log_search_event(query_hash=qhash, provider=provider.name, status="error",
                              result_count=0, latency_ms=_elapsed_ms(start),
                              cache_hit=False, attempt=counter.attempts)
            log.warning("provider %s failed: %s — advancing", provider.name, exc)
            continue
        except Exception as exc:
            breaker.record_failure()
            _log_search_event(query_hash=qhash, provider=provider.name, status="error",
                              result_count=0, latency_ms=_elapsed_ms(start),
                              cache_hit=False, attempt=counter.attempts)
            log.warning("provider %s error: %s — advancing", provider.name, exc)
            continue
        breaker.record_success()
        _log_search_event(query_hash=qhash, provider=provider.name,
                          status="ok" if results else "empty", result_count=len(results),
                          latency_ms=_elapsed_ms(start), cache_hit=False,
                          attempt=counter.attempts)
        if results:
            return results
        log.info("provider %s returned 0 results — advancing", provider.name)
    return []


# --------------------------------------------------------------------------- #
# Query cache
#
# In-process LRU + per-entry TTL over assembled result sets. A repeated query
# inside the TTL window returns immediately without touching the provider chain.
# Right-sized for Willow's single-host reality: in-process only, no Redis (the
# spec's multi-process backend doesn't fit). Current-events queries ("latest",
# "breaking", a date, ...) get a short TTL so fast-moving topics stay fresh.
# Opt-out per call via search_web(cache=False); disable globally with
# WILLOW_SEARCH_CACHE=0. Only non-empty results are cached — caching a [] would
# pin a transient all-providers-down failure for the full TTL.
# --------------------------------------------------------------------------- #


_CURRENT_EVENTS_MARKERS = (
    "latest", "breaking", "just now", "just announced", "right now",
    "live", "today", "this morning", "this week", "current",
)


def _cache_config() -> dict[str, Any]:
    return {
        "enabled": _env_bool("WILLOW_SEARCH_CACHE", True),
        "ttl": _env_float("WILLOW_SEARCH_CACHE_TTL", 300.0),
        "ttl_news": _env_float("WILLOW_SEARCH_CACHE_TTL_NEWS", 60.0),
    }


def _is_current_events(query: str) -> bool:
    """Heuristic: does this query chase fast-moving / time-sensitive results?"""
    q = (query or "").lower()
    return any(marker in q for marker in _CURRENT_EVENTS_MARKERS)


def _cache_key(
    query: str,
    max_results: int,
    trusted_only: bool,
    include_handoffs: bool,
    order: list[str],
) -> str:
    """sha256 over normalized query + the params that change the result set."""
    norm = " ".join((query or "").lower().split())
    raw = f"{norm}|{max_results}|{int(trusted_only)}|{int(include_handoffs)}|{','.join(order)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _TTLCache:
    """Bounded LRU cache with per-entry TTL.

    Not thread-safe by design — Willow's MCP server services search calls
    serially per session, so a lock would only add contention. Eviction is
    least-recently-used once `maxsize` is exceeded; expired entries are dropped
    lazily on access.
    """

    def __init__(self, maxsize: int = 256, clock=time.monotonic) -> None:
        self._maxsize = max(1, maxsize)
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


_SEARCH_CACHE = _TTLCache(maxsize=_env_int("WILLOW_SEARCH_CACHE_SIZE", 256))


def reset_search_cache() -> None:
    """Clear the query cache and re-read its size from env (test/operator reset)."""
    global _SEARCH_CACHE
    _SEARCH_CACHE = _TTLCache(maxsize=_env_int("WILLOW_SEARCH_CACHE_SIZE", 256))


def search_web(
    query: str,
    *,
    max_results: int = 8,
    trusted_only: bool = False,
    include_handoffs: bool = False,
    cache: bool = True,
    providers: list[SearchProvider] | None = None,
) -> list[dict[str, Any]]:
    """
    General open web search for Willow.

    trusted_only: filter to verified institutional domain suffixes.
    include_handoffs: prepend map/search URLs for navigational queries.
    cache: serve/store via the in-process LRU+TTL cache (opt-out per call;
        WILLOW_SEARCH_CACHE=0 disables globally). Current-events queries get a
        short TTL automatically.
    providers: explicit provider chain (default: built from
        WILLOW_SEARCH_PROVIDER_ORDER, falling back to DDG HTML).
    """
    cfg = _cache_config()
    order = [p.name for p in providers] if providers is not None else _provider_order()
    use_cache = cache and cfg["enabled"]
    key = (
        _cache_key(query, max_results, trusted_only, include_handoffs, order)
        if use_cache
        else None
    )
    if key is not None:
        cached = _SEARCH_CACHE.get(key)
        if cached is not None:
            _log_search_event(query_hash=_query_hash(query), provider="cache",
                              status="ok", result_count=len(cached), latency_ms=0.0,
                              cache_hit=True, attempt=0)
            return list(cached)

    hits: list[dict[str, Any]] = []
    if include_handoffs:
        hits.extend(navigational_handoffs(query))

    raw = _search_providers(query, max_results, providers)
    if trusted_only:
        raw = [h for h in raw if _trusted_host(h.get("hostname", ""))]

    seen = {h["url"] for h in hits if h.get("url")}
    for hit in raw:
        url = hit.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            hits.append(hit)
    result = hits[: max_results + (3 if include_handoffs else 0)]

    # Cache only non-empty provider hits — an empty `raw` means every provider
    # failed or was filtered out, and pinning that for the TTL would mask recovery.
    if key is not None and raw:
        ttl = cfg["ttl_news"] if _is_current_events(query) else cfg["ttl"]
        _SEARCH_CACHE.set(key, list(result), ttl)
    return result
