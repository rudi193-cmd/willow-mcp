"""A real `requests` stack with a fake adapter underneath.

Nothing here opens a socket. The adapter builds `requests.Response` objects
directly, so `requests.Session.send` — the code that decides whether and when a
body is pulled off the connection — is the real one. The private addresses the
tests hand it are only ever parsed.

**Why not MagicMock.** The destination tests in `test_web_fetch.py` used to mock
the whole of `requests`, and a mock cannot answer the questions that matter for
a size or lifetime bug: it never runs `Session.send`, so it cannot show that
`max_bytes` bounded nothing (the body was resident before the slice), that a 3xx
body is read in full while filling in `Response._next`, or that the final
response was never closed. Every one of those passed under the mock. So the
transport is faked one layer lower, where the library's own behaviour is still
in the picture.

`CountingRaw` counts the bytes actually handed out and the closes actually
performed, which is what those three assertions are about.
"""
from __future__ import annotations

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict


class CountingRaw:
    """urllib3-HTTPResponse-shaped body that counts the bytes handed out."""

    def __init__(self, body: bytes = b"", nbytes: int | None = None):
        #: Generated lazily so a "50MB response" costs nothing to script.
        self.total = len(body) if nbytes is None else nbytes
        self._body = body or b"A" * 65536
        self.read_bytes = 0
        self.releases = 0
        self.closes = 0
        self._original_response = None
        self.decode_content = True

    @property
    def closed(self) -> bool:
        return bool(self.releases or self.closes)

    def _gen(self, amt):
        left = self.total
        while left > 0:
            n = min(amt or 65536, left, len(self._body))
            left -= n
            self.read_bytes += n
            yield self._body[:n]

    def stream(self, amt=65536, decode_content=True):
        yield from self._gen(amt)

    def read(self, amt=None, decode_content=True):
        return b"".join(self._gen(amt or self.total))

    def release_conn(self):
        self.releases += 1

    def close(self):
        self.closes += 1


class ScriptedAdapter(BaseAdapter):
    """Serves a scripted list of `(status, headers, body)` responses in order.

    `body` may be bytes, or an int meaning "this many bytes, generated lazily".
    """

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.dialled: list[tuple[str, str]] = []   # (method, url)
        self.sent: list = []                       # PreparedRequests
        self.raws: list[CountingRaw] = []

    def send(self, request, stream=False, timeout=None, verify=True,
             cert=None, proxies=None):
        self.dialled.append((request.method, request.url))
        self.sent.append(request)
        status, headers, body = (self.script.pop(0) if self.script
                                 else (200, {}, b""))
        r = requests.Response()
        r.status_code = status
        r.headers = CaseInsensitiveDict(headers)
        r.url = request.url
        r.request = request
        r.encoding = "utf-8"
        raw = (CountingRaw(nbytes=body) if isinstance(body, int)
               else CountingRaw(body))
        self.raws.append(raw)
        r.raw = raw
        return r

    def close(self):
        pass


class RequestsShim:
    """Stands in for the `requests` module, routed through a ScriptedAdapter.

    `Session` is a real `requests.Session` subclass with the adapter already
    mounted, so `web_fetch`'s own no-redirect subclass of it still runs the
    library's `send`.
    """

    def __init__(self, adapter: ScriptedAdapter):
        self.adapter = adapter

        class Session(requests.Session):
            def __init__(inner):   # noqa: N805 — inner session, not this shim
                super().__init__()
                inner.mount("https://", adapter)
                inner.mount("http://", adapter)

        self.Session = Session
        #: Module-shaped too, so the same script can be pointed at code that
        #: calls `requests.get(...)` directly — which is what the paths this
        #: harness was written for used to do.
        self.get = lambda url, **kw: Session().request("GET", url, **kw)
        self.post = lambda url, **kw: Session().request("POST", url, **kw)
        self.request = lambda m, url, **kw: Session().request(m, url, **kw)
        self.RequestException = requests.RequestException
        self.Timeout = requests.Timeout
        self.ConnectionError = requests.ConnectionError


def transport(script):
    """`(shim, adapter)` for a scripted chain — patch `_require_requests` to it."""
    adapter = ScriptedAdapter(script)
    return RequestsShim(adapter), adapter
