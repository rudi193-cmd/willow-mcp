"""
sap/mai/parser.py — MarkdownAI document parser.

Handles the @directive syntax used in .md files that open with `@markdownai v1.0`.
Directives implemented: @env, @db, @http, @render, @prompt/@end, @if/@endif,
@connect, @phase, @macro/@endmacro, @constraint, @define-concept.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

# ── Simple cache (directive results) ─────────────────────────────────

_cache: dict[str, Any] = {}


def invalidate(key: str | None = None) -> None:
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


# ── Attribute parsing ───────────────────────────────────────────────

_ATTR_RE = re.compile(r'(\w[\w-]*)=(?:"([^"]*?)"|\'([^\']*?)\'|(\S+))')


def parse_attrs(text: str) -> dict[str, str]:
    """Parse key="value" or key=value attributes from a directive string."""
    return {
        m.group(1): (m.group(2) or m.group(3) or m.group(4) or "")
        for m in _ATTR_RE.finditer(text)
    }


# ── Connection registry ──────────────────────────────────────────────

@dataclass
class Connection:
    name: str
    conn_type: str
    uri: str = ""


_connections: dict[str, Connection] = {}


def _resolve_value(raw: str) -> str:
    """Resolve env.VAR_NAME references."""
    if raw.startswith("env."):
        return os.environ.get(raw[4:], "")
    return raw


def _register_connection(attrs: dict[str, str]) -> None:
    name = attrs.get("name", attrs.get("using", "default"))
    conn_type = attrs.get("type", "postgres")
    uri_raw = attrs.get("uri", attrs.get("url", ""))
    uri = _resolve_value(uri_raw) if uri_raw else ""
    _connections[name] = Connection(name=name, conn_type=conn_type, uri=uri)


# ── Fallback sentinel ────────────────────────────────────────────────

@dataclass
class _FallbackResult:
    """Returned by _handle_db when the query fails and on-error is set."""
    value: str


# ── Directive handlers ───────────────────────────────────────────────

# ── Directive safety (issue #161) ─────────────────────────────────────
_SECRET_ENV_RE = re.compile(
    r"PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIAL|SESSION_?KEY|_KEY$",
    re.I,
)


def _env_is_secret(key: str) -> bool:
    """Credential-shaped env vars are never exposed through mai (#161)."""
    return bool(key) and bool(_SECRET_ENV_RE.search(key))


_DIRECTIVE_DENIED = (
    "[mai directive denied: caller lacks the 'markdownai_directives' grant (#161)]"
)


def directives_permitted(app_id: str) -> bool:
    """#161: side-effect directives (@db/@http/@env) resolve only for a caller
    whose manifest grants markdownai_directives. An ungated internal
    render() call (empty app_id) is fail-closed — the directives render as
    refusals instead of executing."""
    if not app_id:
        return False
    from willow_mcp import gate
    return gate.permitted(app_id, "__mai_directives__")


def _env_key_allowed(key: str) -> bool:
    """#161: @env is default-deny. Only keys the operator names in
    WILLOW_MAI_ENV_ALLOW (comma-separated) resolve — and never
    credential-shaped ones, even when listed."""
    if not key or _env_is_secret(key):
        return False
    allow = {
        k.strip() for k in os.environ.get("WILLOW_MAI_ENV_ALLOW", "").split(",")
        if k.strip()
    }
    return key in allow


def _db_connection_allowed(app_id: str, name: str) -> bool:
    """#161: a @db connection must be allowlisted in the calling app's
    manifest under "mai_connections" (a list of @connect names). Missing
    list, missing manifest, or unlisted name all deny."""
    if not app_id or not name:
        return False
    from willow_mcp import gate
    manifest = gate._load_manifest(app_id)
    if not isinstance(manifest, dict):
        return False
    allowed = manifest.get("mai_connections")
    return isinstance(allowed, list) and name in allowed


_BLOCKED_HTTP_HOST_RE = re.compile(
    r"^(localhost|0\.0\.0\.0|127\.|10\.|169\.254\.|192\.168\.|"
    r"172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?|metadata\b)",
    re.I,
)


def _http_host_blocked(url: str) -> bool:
    """Block SSRF to loopback / link-local / private / metadata hosts (#161)."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return True
    return bool(_BLOCKED_HTTP_HOST_RE.match(p.hostname or ""))


def _handle_env(attrs: dict[str, str], _content: str, app_id: str = "") -> str:
    key = attrs.get("key", attrs.get("var", ""))
    fallback = attrs.get("fallback", attrs.get("default", ""))
    if not key:
        # @env KEY or inline usage — try positional
        return fallback
    # #161: gate + default-deny allowlist; env degrades quietly to fallback.
    if not directives_permitted(app_id) or not _env_key_allowed(key):
        return fallback
    return os.environ.get(key, fallback)


def _handle_db(attrs: dict[str, str], _content: str, app_id: str = "") -> Any:
    """Execute a SQL query and return rows.

    on-error attr: value to return silently when the query fails.
    E.g.  @db using="willow" raw="SELECT ..." on-error=""

    #161: gate denials are LOUD — on-error softens query failures, never a
    refused authorization.
    """
    using = attrs.get("using", "default")
    raw_sql = attrs.get("raw", "")
    # None means no fallback — render the error dict (legacy behaviour)
    fallback: str | None = attrs.get("on-error", None)
    if not raw_sql:
        return []

    if not directives_permitted(app_id):
        return [{"error": _DIRECTIVE_DENIED}]
    if not _db_connection_allowed(app_id, using):
        return [{"error": f"@db refused: connection {using!r} is not allowlisted in "
                          "the app manifest's \"mai_connections\" (#161)"}]

    conn_info = _connections.get(using)
    uri = ""
    if conn_info:
        uri = conn_info.uri
    if not uri:
        # #161: never silently connect to the willow database. A @db must name an
        # explicit @connect (declared by the doc author); otherwise refuse.
        if fallback is not None:
            return _FallbackResult(fallback)
        return [{"error": "@db refused: no @connect declared (won't default to the "
                          "willow database — #161)"}]

    cache_key = f"db:{using}:{raw_sql}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(uri)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(raw_sql)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        _cache[cache_key] = rows
        return rows
    except Exception as e:
        if fallback is not None:
            return _FallbackResult(fallback)
        return [{"error": str(e)}]


def _handle_render(data: Any, attrs: dict[str, str]) -> str:
    """Render data as a table or JSON."""
    render_type = attrs.get("type", "json")
    if render_type == "table" and isinstance(data, list) and data:
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
            sep = " | "
            rows = [sep.join(str(v) for v in headers)]
            rows.append(sep.join("---" for _ in headers))
            for row in data:
                rows.append(sep.join(str(row.get(h, "")) for h in headers))
            return "\n".join(rows)
    return json.dumps(data, default=str, indent=2)


def _handle_http(attrs: dict[str, str], _content: str, app_id: str = "") -> Any:
    url = _resolve_value(attrs.get("url", attrs.get("src", "")))
    if not url:
        return {"error": "no url"}
    if not directives_permitted(app_id):
        return {"error": _DIRECTIVE_DENIED}
    # #161: honor the operator's standing egress consent — the same switch
    # that gates Kart allow_net (B-29). Read fail-closed by consent.py.
    from willow_mcp import consent
    if not consent.internet_permitted():
        return {"error": "@http refused: operator consent.internet is not granted "
                         "(#161 / B-29)"}
    if _http_host_blocked(url):
        return {"error": "@http refused: host not allowed "
                         "(loopback/link-local/private/metadata blocked — #161)"}
    cache_key = f"http:{url}"
    if cache_key in _cache:
        return _cache[cache_key]
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body)
        except Exception:
            result = body
        _cache[cache_key] = result
        return result
    except Exception as e:
        return {"error": str(e)}


# ── Phase / Macro ───────────────────────────────────────────────────

@dataclass
class Phase:
    name: str
    content: str
    line: int


@dataclass
class Macro:
    name: str
    content: str


def extract_phases(text: str) -> list[Phase]:
    phases = []
    phase_re = re.compile(r"^@phase\s+(\S+)", re.MULTILINE)
    boundaries = [(m.start(), m.group(1), m.end()) for m in phase_re.finditer(text)]
    for i, (start, name, content_start) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        line = text[:start].count("\n") + 1
        content = text[content_start:end].strip()
        phases.append(Phase(name=name, content=content, line=line))
    return phases


def extract_macros(text: str) -> dict[str, Macro]:
    macros = {}
    macro_re = re.compile(
        r"@macro\s+(\S+)(.*?)@endmacro", re.DOTALL
    )
    for m in macro_re.finditer(text):
        name = m.group(1)
        content = m.group(2).strip()
        macros[name] = Macro(name=name, content=content)
    return macros


def call_macro(macros: dict[str, Macro], name: str, args: dict[str, str]) -> str:
    macro = macros.get(name)
    if not macro:
        return f"[macro '{name}' not found]"
    result = macro.content
    for k, v in args.items():
        result = result.replace(f"{{{k}}}", v).replace(f"${k}", v)
    return result


# ── Constraint / Concept extraction ───────────────────────────────────────

@dataclass
class Constraint:
    text: str
    severity: str = "info"
    line: int = 0


def extract_constraints(text: str) -> list[Constraint]:
    constraints = []
    pattern = re.compile(
        # #156: accept BOTH `@constraint <rule>` and the colon form
        # `@constraint: <rule>` — the colon form previously matched nothing and
        # the rule was silently dropped. Separator is a colon or whitespace.
        r"@constraint(?:\s*:\s*|\s+)(?:severity=[\"']?(\w+)[\"']?\s+)?(.*?)(?=@constraint|$)",
        re.DOTALL
    )
    for m in pattern.finditer(text):
        severity = m.group(1) or "info"
        body = m.group(2).strip()
        line = text[:m.start()].count("\n") + 1
        constraints.append(Constraint(text=body, severity=severity, line=line))
    _sev_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    constraints.sort(key=lambda c: _sev_order.get(c.severity, 99))
    return constraints


# ── Conditional blocks ────────────────────────────────────────────────

def apply_conditionals(text: str, consumer: str = "ai") -> str:
    """Strip or keep @if/@endif blocks based on consumer.

    #162: resolves NESTED @if/@endif correctly by rewriting innermost-first. A
    flat, non-recursive regex let an inner @endif close an outer @if, leaking the
    wrong audience's content and stranding a dangling @endif. We repeatedly
    substitute the innermost block — one whose body contains no @if/@endif —
    until none remain, so nesting resolves from the inside out.
    """
    def _replace(m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        req_consumer = attrs.get("consumer", "")
        return m.group(2) if (not req_consumer or req_consumer == consumer) else ""

    innermost = re.compile(
        r"@if\s+([^\n]+)\n((?:(?!@if\b)(?!@endif\b).)*?)@endif",
        re.DOTALL,
    )
    prev = None
    while prev != text:
        prev = text
        text = innermost.sub(_replace, text)
    return text


# ── Main renderer ────────────────────────────────────────────────────

def render(
    text: str,
    cwd: str = "",
    phase: str = "",
    fmt: str = "ai",
    consumer: str = "ai",
    skill_args: str = "",
    skill_named_args: dict[str, str] | None = None,
    app_id: str = "",
) -> str:
    """
    Render a MarkdownAI document.

    - Strips the @markdownai header line
    - Resolves @connect, @env, @db, @http directives
    - Removes @prompt/@end blocks (they're instructions for the AI, not rendered content)
    - Applies @if/@endif conditionals
    - Handles @phase filtering
    - In 'ai' format: strips comment lines, condenses whitespace

    #161: side-effect directives (@db/@http/@env) resolve only when app_id
    carries the markdownai_directives grant. A render with no app_id — every
    internal/legacy call — is fail-closed: the document still renders, but
    the dangerous directives yield refusal text instead of executing.
    """
    allowed = directives_permitted(app_id)

    # Strip header
    text = re.sub(r"^@markdownai\s+v[\d.]+\s*\n?", "", text, count=1)

    # Register connections — only for a directive-granted caller; an ungated
    # render must not poison the process-global registry either (#161).
    if allowed:
        for m in re.finditer(r"^@connect\s+(\S+)\s+(.*)", text, re.MULTILINE):
            attrs_str = f"name={m.group(1)} {m.group(2)}"
            _register_connection(parse_attrs(attrs_str))

    # Remove @connect lines
    text = re.sub(r"^@connect.*\n?", "", text, flags=re.MULTILINE)

    # Apply conditionals
    text = apply_conditionals(text, consumer=consumer)

    # Skill argument substitution
    if skill_args:
        text = text.replace("$ARGUMENTS", skill_args)
    if skill_named_args:
        for k, v in skill_named_args.items():
            text = text.replace(f"${k.upper()}", v).replace(f"${{{k}}}", v)

    # Phase filtering
    if phase:
        phases = extract_phases(text)
        matched = next((p for p in phases if p.name == phase), None)
        if matched:
            text = matched.content
        # else render full doc

    # Remove macro definitions (they're templates, not rendered content)
    text = re.sub(r"@macro\s+\S+.*?@endmacro\s*", "", text, flags=re.DOTALL)

    # Remove @prompt/@end blocks — these are instructions embedded for the AI reader,
    # not output content
    text = re.sub(r"@prompt[^\n]*\n.*?@end\s*\n?", "", text, flags=re.DOTALL)

    # Resolve @env directives — gate + default-deny allowlist (#161); env
    # degrades quietly to its declared fallback. The old regex captured only
    # the first token, so `key=`/`fallback=` attrs never reached parse_attrs
    # and every keyed @env silently rendered "" — parse the whole rest of the
    # line instead, with a bare `@env KEY` positional form kept working.
    def _env_sub(m: re.Match) -> str:
        rest = m.group(1)
        attrs = parse_attrs(rest)
        key = attrs.get("key", attrs.get("var", ""))
        if not key:
            words = rest.split()
            key = words[0] if words and "=" not in words[0] else ""
        fallback = attrs.get("fallback", attrs.get("default", ""))
        if not allowed or not key or not _env_key_allowed(key):
            return fallback
        return os.environ.get(key, fallback)

    text = re.sub(r"@env\s+([^\n]+)", _env_sub, text)

    # Resolve @db ... | @render chains
    def _db_render_sub(m: re.Match) -> str:
        db_attrs_str = m.group(1)
        render_attrs_str = m.group(2) or ""
        db_attrs = parse_attrs(db_attrs_str)
        render_attrs = parse_attrs(render_attrs_str)
        data = _handle_db(db_attrs, "", app_id=app_id)
        if isinstance(data, _FallbackResult):
            return data.value
        return _handle_render(data, render_attrs)

    text = re.sub(
        r"@db\s+([^\n|]+)\s*\|\s*@render\s*([^\n]*)",
        _db_render_sub,
        text,
    )

    # Standalone @db (no pipe)
    def _db_sub(m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        data = _handle_db(attrs, "", app_id=app_id)
        if isinstance(data, _FallbackResult):
            return data.value
        return json.dumps(data, default=str)

    text = re.sub(r"@db\s+([^\n]+)(?!\s*\|)", _db_sub, text)

    # @http
    def _http_sub(m: re.Match) -> str:
        attrs = parse_attrs(m.group(1))
        result = _handle_http(attrs, "", app_id=app_id)
        return json.dumps(result, default=str) if not isinstance(result, str) else result

    text = re.sub(r"@http\s+([^\n]+)", _http_sub, text)

    # Strip remaining unknown @directives (not content)
    text = re.sub(r"^@(?!markdownai)\w[\w-]*[^\n]*\n?", "", text, flags=re.MULTILINE)

    if fmt == "ai":
        # Condense: remove trailing spaces, collapse >2 blank lines
        lines = [ln.rstrip() for ln in text.splitlines()]
        condensed: list[str] = []
        blank_run = 0
        for ln in lines:
            if ln == "":
                blank_run += 1
                if blank_run <= 1:
                    condensed.append(ln)
            else:
                blank_run = 0
                condensed.append(ln)
        text = "\n".join(condensed).strip()

    return text
