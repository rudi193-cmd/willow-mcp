"""Guarded HTTP fetch for agents — destination guard + external-guard scan.

The destination half of this file was rewritten after an audit of the sibling
guard in `jeles._egress` turned up the same defects here, larger. Three, and
each one alone was enough to reach the cloud metadata endpoint:

* **The literal host was the only thing inspected.** No name was ever resolved,
  so `https://totally-legit.example/` with an A record of `127.0.0.1` walked
  straight through — measured, `validate_fetch_url` returned None.
* **`allow_redirects=True` was passed to `requests`,** which follows the chain
  inside `get()`. So even the literal check only ever applied to the *first*
  URL, and a 302 to `169.254.169.254` was followed unchecked. This is the one
  that matters, because the first URL is chosen by the operator's agent and the
  redirect target is chosen by whatever answered.
* **Two parsers disagreed about the hostname.** `urlparse` and
  `urllib3.util.parse_url` both read `https://169.254.169%2e254/` as the opaque
  name `169.254.169%2e254`; urllib3's connection layer decodes it before
  dialling. Measured: `connect(('169.254.169.254', 443))`.

`willow_web_fetch` shares the `web_read` permission line with
`willow_institutional_search` (gate.py), so these were one grant with the
weaker path setting the ceiling.

Kept deliberately separate from jeles' copy rather than shared: that one guards
`urllib`, this one guards `requests`/`urllib3`, and the whole class of bug here
is transport-specific parsing. A shared abstraction would have to be right
about both connectors at once, which is how the disagreement got missed the
first time.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
import urllib.request
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

log = logging.getLogger("willow_mcp.web_fetch")

_USER_AGENT = "Mozilla/5.0 (compatible; Willow-mcp/2.0; +https://github.com/rudi193-cmd/willow-mcp)"
_DEFAULT_MAX_BYTES = 512_000
_DEFAULT_MAX_CHARS = 80_000
#: requests defaults to 30. A fetch tool does not need a chain that long, and
#: every hop is another destination check and another resolver round trip.
_MAX_REDIRECTS = 5
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_TAG_RE = re.compile(r"<[^>]+>")


def _require_requests():
    try:
        import requests  # noqa: WPS433 — optional at import, required at call
    except ImportError as exc:
        raise RuntimeError(
            "willow_web_fetch requires the 'requests' package — "
            "pip install 'willow-mcp[web]' or pip install requests"
        ) from exc
    return requests


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or ""))


def _as_address(host: str) -> str | None:
    """The host read as a literal address, or None if it is a name.

    `inet_aton` is here because `ip_address` is stricter than every resolver:
    it rejects `2130706433`, `0177.0.0.1`, `0x7f.0.0.1` and `127.1`. urllib3
    hands all four to the socket untouched and `getaddrinfo` reads every one of
    them as `127.0.0.1` — measured. Doing that arithmetic locally is what keeps
    them refused on the two paths with no DNS lookup: behind a proxy, and
    offline.
    """
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        return None


def _dialled_hosts(hostname: str) -> list[str]:
    """Every host string this URL could end up dialling.

    Both parsers in front of the socket keep percent-escapes; the connection
    layer decodes them. Checking only what `urlparse` reports is what let
    `https://169.254.169%2e254/` through, so the decoded view is checked too
    and either one being private refuses.
    """
    seen: list[str] = []
    for raw in (hostname, unquote(hostname or "")):
        h = (raw or "").strip().strip("[]").lower().rstrip(".")
        if h and h not in seen:
            seen.append(h)
    return seen


def _proxy_dials_for(url: str) -> bool:
    """Whether a proxy, not this process, will resolve and dial the destination.

    `requests` reads the same environment (`trust_env` -> `getproxies`), so this
    agrees with what the transport will do. It matters because a proxied request
    never resolves the destination here — the TCP peer is the proxy and the
    hostname travels to it in a CONNECT line. Resolving anyway is wrong in both
    directions, and the direction that bites is the false refusal: under
    split-horizon DNS a legitimate public host answers with an RFC1918 address
    and the fetch is refused for a reason that is not true.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if not urllib.request.getproxies().get((parsed.scheme or "").lower()):
        return False
    try:
        return not urllib.request.proxy_bypass(parsed.hostname or "")
    except (OSError, ValueError):
        return True


def _is_blocked_host(hostname: str, *, resolve: bool = True) -> bool:
    hosts = _dialled_hosts(hostname)
    if not hosts:
        return True
    for host in hosts:
        if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
            return True
        if host.endswith(".local") or host.endswith(".internal"):
            return True

        literal = _as_address(host)
        if literal is not None:
            candidates = [literal]
        elif resolve:
            try:
                candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
            except OSError:
                # About to fail on its own. Refusing here would report a
                # security decision for what is really a DNS failure.
                continue
        else:
            continue

        for raw in candidates:
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            # `not is_global` is appended, not substituted. On its own it would
            # allow IPv4 and IPv6 multicast and the NAT64 well-known prefix —
            # and `64:ff9b::a9fe:a9fe` reaches 169.254.169.254 on a NAT64
            # network. The explicit list on its own allowed all of
            # 100.64.0.0/10, which is what cloud and ISP internals are numbered
            # from. Each half covers what the other misses.
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
                or addr.is_unspecified
                or not addr.is_global
            ):
                return True
    return False


def validate_fetch_url(url: str) -> str | None:
    """Why this URL must not be fetched, or None.

    Hostnames are resolved, not just pattern-matched. A name-only check is the
    obvious thing to write and is defeated by pointing a public name at
    `127.0.0.1`; this one used to be exactly that.

    **Residual, stated rather than papered over.** Resolving here and connecting
    afterwards are two separate lookups, so a name that answers public now and
    private a moment later still gets through. Closing that needs the connection
    pinned to the address that was checked, which requests does not expose. It
    raises the cost from "set a DNS record" to "win a race". Behind a proxy the
    name is not resolved here at all, so a name only the proxy can resolve to a
    private address is the proxy's ACL to enforce — literal addresses are still
    refused either way, because the proxy will CONNECT to whatever it is named.
    """
    raw = (url or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return "unparseable URL"
    if parsed.scheme not in ("http", "https"):
        return f"unsupported scheme: {parsed.scheme!r} (http/https only)"
    if not parsed.netloc:
        return "missing hostname"
    try:
        hostname = parsed.hostname
    except ValueError:
        # A bracketed netloc that is not an IP literal. Neither view can say
        # where this goes, and "nobody could tell" is not permission.
        return "blocked host: cannot be parsed"
    if _is_blocked_host(hostname or "", resolve=not _proxy_dials_for(raw)):
        return f"blocked host: {parsed.hostname}"
    return None


class _RefusedRedirect(Exception):
    """A hop in the chain failed the destination check."""


def _get_checking_every_hop(requests, url: str, *, timeout: float):
    """Follow the redirect chain by hand, validating each hop before taking it.

    `allow_redirects=True` follows the chain inside `requests.get`, where no
    check of ours runs — so the destination guard applied only to the first URL,
    the one hop nobody else chooses. An upstream returning
    `Location: https://169.254.169.254/latest/meta-data/` was followed, and the
    body came back through the tool.

    Returns `(final_response, [urls followed])`. Intermediate responses are
    closed rather than left to the collector, since only their headers are read.
    """
    headers = {"User-Agent": _USER_AGENT}
    current = url
    followed: list[str] = []
    for _ in range(_MAX_REDIRECTS + 1):
        resp = requests.get(current, headers=headers, timeout=timeout,
                            allow_redirects=False)
        location = (resp.headers.get("Location") if resp.status_code
                    in _REDIRECT_CODES else None)
        if not location:
            return resp, followed
        resp.close()
        # Relative Locations are the common case and are resolved against the
        # URL that issued them, exactly as requests would.
        nxt = urljoin(current, location)
        err = validate_fetch_url(nxt)
        if err:
            raise _RefusedRedirect(
                f"refusing redirect from {current} — {err}")
        followed.append(nxt)
        current = nxt
    raise _RefusedRedirect(
        f"more than {_MAX_REDIRECTS} redirects starting at {url}")


def fetch_url(
    url: str,
    *,
    wrap: bool = True,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    max_chars: int = _DEFAULT_MAX_CHARS,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Fetch URL body with size limits, guard scan, optional sandwich wrap."""
    from . import external_guard

    err = validate_fetch_url(url)
    if err:
        return {"ok": False, "url": url, "error": err}

    requests = _require_requests()
    try:
        resp, redirects = _get_checking_every_hop(requests, url, timeout=timeout)
    except _RefusedRedirect as exc:
        log.warning("fetch refused %s: %s", url, exc)
        return {"ok": False, "url": url, "error": str(exc)}
    except requests.RequestException as exc:
        log.warning("fetch failed %s: %s", url, exc)
        return {"ok": False, "url": url, "error": str(exc)}

    raw = resp.content[:max_bytes]
    charset = resp.encoding or "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "html" in content_type or text.lstrip().startswith("<"):
        text = _strip_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"

    hits = external_guard.scan(text)
    guard = external_guard.verdict(hits)
    if guard == "BLOCKED":
        label = hits[0]["label"] if hits else "injection pattern"
        return {
            "ok": False,
            "url": url,
            "status_code": resp.status_code,
            "guard": guard,
            "guard_hits": hits,
            "error": f"external-guard BLOCKED: {label}",
        }

    body = external_guard.SANDWICH_TEMPLATE.format(content=text) if wrap else text
    return {
        "ok": True,
        "url": url,
        "final_url": str(resp.url),
        # The chain, so a caller can see where the content actually came from.
        # Previously requests followed it silently and only `final_url` hinted.
        "redirects": redirects,
        "status_code": resp.status_code,
        "content_type": content_type,
        "guard": guard,
        "guard_hits": hits,
        "chars": len(text),
        "content": body,
        "wrapped": wrap,
    }
