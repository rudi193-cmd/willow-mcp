"""
sap/mai/tools.py — Python implementations of the MarkdownAI MCP tools.

Replaces the Node.js @markdownai/mcp package with a native Python equivalent.
Register all tools on a FastMCP instance by calling register(mcp).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from willow_mcp.mai import parser

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_MAI_HEADER = "@markdownai"


def _strip_yaml_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block including delimiters, or ''), and body."""
    t = text.lstrip()
    if not t.startswith("---"):
        return "", text
    end = t.find("---", 3)
    if end < 0:
        return "", text
    front = t[: end + 3]
    body = t[end + 3 :].lstrip("\n")
    return front, body


def _markdownai_body(text: str) -> str:
    """Body after optional YAML frontmatter — where @markdownai must live."""
    _, body = _strip_yaml_frontmatter(text)
    return body


def _resolve_path(path: str, cwd: str = "") -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p.resolve()


def _read_file(path: str, cwd: str = "") -> str:
    return _resolve_path(path, cwd).read_text(encoding="utf-8", errors="replace")


def _is_markdownai_content(content: str) -> bool:
    return _markdownai_body(content).lstrip().startswith(_MAI_HEADER)


def _is_markdownai_path(path: Path) -> bool:
    if not path.exists() or path.suffix.lower() != ".md":
        return False
    try:
        return _is_markdownai_content(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def register(mcp: "FastMCP") -> None:
    """Register all MarkdownAI tools on the provided FastMCP instance."""

    @mcp.tool()
    def mai_read_file(
        path: str,
        phase: str = "",
        format: str = "ai",
        consumer: str = "ai",
        budget: int = 0,
        skill_args: str = "",
        skill_named_args: dict = None,
        skill_session_id: str = "",
        skill_effort: str = "",
        skill_dir: str = "",
    ) -> str:
        """
        Read and render a MarkdownAI document. Returns ai-format (token-efficient) by default.
        Pass format="standard" to get the full rendered output.
        When reading a skill/command file, pass skill_args to enable @if conditions on $ARGUMENTS.

        Args:
            path: Path to the .md file.
            phase: Optional phase name to extract.
            format: 'ai' (default, condensed) or 'standard' (full).
            consumer: Consumer hint for @if conditions (default: 'ai').
            skill_args: Positional arguments string for skill files ($ARGUMENTS).
            skill_named_args: Named arguments dict for skill files.
            skill_session_id: Session ID passed to skill.
            skill_effort: Effort level passed to skill.
            skill_dir: Working directory override for skill.
        """
        cwd = skill_dir or os.getcwd()
        try:
            raw = _read_file(path, cwd)
        except FileNotFoundError:
            return f"[mai_read_file] file not found: {path}"
        except Exception as e:
            return f"[mai_read_file] error reading {path}: {e}"

        if not _is_markdownai_content(raw):
            return raw

        return parser.render(
            _markdownai_body(raw),
            cwd=cwd,
            phase=phase,
            fmt=format,
            consumer=consumer,
            skill_args=skill_args,
            skill_named_args=skill_named_args or {},
        )

    @mcp.tool()
    def mai_write_file(path: str, content: str, cwd: str = "") -> dict:
        """
        Write raw content to a MarkdownAI file (no rendering).

        Invalidates the render cache for the path. Use for .md files with an
        @markdownai header when IDE Write/Edit is blocked by preToolUse hooks.

        Args:
            path: Absolute or cwd-relative path to the file.
            content: Full file content to write (must include @markdownai header if required).
            cwd: Working directory for relative paths.
        """
        try:
            target = _resolve_path(path, cwd or os.getcwd())
            if target.suffix.lower() != ".md":
                return {"ok": False, "error": f"[mai_write_file] not a .md file: {path}"}
            if not _is_markdownai_content(content) and _is_markdownai_path(target):
                return {
                    "ok": False,
                    "error": (
                        "[mai_write_file] existing @markdownai file — content must keep "
                        "@markdownai header on line 1 of body (after YAML frontmatter if any)"
                    ),
                }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            parser.invalidate(str(target))
            nbytes = len(content.encode("utf-8"))
            return {"ok": True, "path": str(target), "bytes": nbytes}
        except Exception as e:
            return {"ok": False, "error": f"[mai_write_file] {path}: {e}"}

    @mcp.tool()
    def mai_list_phases(file: str) -> list[dict]:
        """List all phases in a MarkdownAI document."""
        try:
            raw = _read_file(file)
        except Exception as e:
            return [{"error": str(e)}]
        phases = parser.extract_phases(_markdownai_body(raw))  # #157: strip frontmatter
        return [{"name": p.name, "line": p.line} for p in phases]

    @mcp.tool()
    def mai_resolve_phase(file: str, phase: str) -> dict:
        """Resolve a named phase in a document — returns its content."""
        try:
            raw = _read_file(file)
        except Exception as e:
            return {"error": str(e)}
        phases = parser.extract_phases(_markdownai_body(raw))  # #157: strip frontmatter
        matched = next((p for p in phases if p.name == phase), None)
        if not matched:
            return {"error": f"phase '{phase}' not found", "available": [p.name for p in phases]}
        return {"name": matched.name, "content": matched.content, "line": matched.line}

    @mcp.tool()
    def mai_next_phase(file: str, current_phase: str) -> dict:
        """Get the next phase after current_phase."""
        try:
            raw = _read_file(file)
        except Exception as e:
            return {"error": str(e)}
        phases = parser.extract_phases(_markdownai_body(raw))  # #157: strip frontmatter
        names = [p.name for p in phases]
        if current_phase not in names:
            return {"error": f"phase '{current_phase}' not found", "available": names}
        idx = names.index(current_phase)
        if idx + 1 >= len(phases):
            return {"current": current_phase, "next": None, "done": True}
        nxt = phases[idx + 1]
        return {"current": current_phase, "next": nxt.name, "line": nxt.line}

    @mcp.tool()
    def mai_call_macro(file: str, macro: str, args: dict = None) -> str:
        """Call a named macro in a document."""
        try:
            raw = _read_file(file)
        except Exception as e:
            return f"[mai_call_macro] error: {e}"
        macros = parser.extract_macros(_markdownai_body(raw))  # #157: strip frontmatter
        return parser.call_macro(macros, macro, args or {})

    @mcp.tool()
    def mai_get_env(key: str, fallback: str = "") -> str:
        """Get an environment variable value."""
        return os.environ.get(key, fallback)

    @mcp.tool()
    def mai_execute_directive(directive: str) -> str:
        """
        Execute a MarkdownAI directive string and return its output.

        Supports: @env KEY, @db using=X raw="SQL", @http url=X
        """
        d = directive.strip()
        if d.startswith("@env"):
            rest = d[4:].strip()
            attrs = parser.parse_attrs(rest)
            key = attrs.get("key", attrs.get("var", rest.split()[0] if rest.split() else ""))
            fallback = attrs.get("fallback", "")
            return os.environ.get(key, fallback)
        if d.startswith("@db"):
            rest = d[3:].strip()
            # Handle pipe: @db ... | @render ...
            if "|" in rest:
                db_part, render_part = rest.split("|", 1)
                db_attrs = parser.parse_attrs(db_part.strip())
                render_attrs = parser.parse_attrs(render_part.strip().lstrip("@render").strip())
                data = parser._handle_db(db_attrs, "")
                return parser._handle_render(data, render_attrs)
            attrs = parser.parse_attrs(rest)
            import json
            return json.dumps(parser._handle_db(attrs, ""), default=str)
        if d.startswith("@http"):
            rest = d[5:].strip()
            attrs = parser.parse_attrs(rest)
            import json
            result = parser._handle_http(attrs, "")
            return json.dumps(result, default=str) if not isinstance(result, str) else result
        return f"[mai_execute_directive] unrecognized directive: {directive}"

    @mcp.tool()
    def mai_invalidate_cache(directive: str = "") -> dict:
        """Invalidate the directive cache. Pass directive to invalidate a specific entry."""
        parser.invalidate(directive if directive else None)
        return {"invalidated": directive or "all"}

    @mcp.tool()
    def mai_get_constraints(file: str) -> list[dict]:
        """Get all @constraint declarations from a MarkdownAI document, sorted by severity."""
        try:
            raw = _read_file(file)
        except Exception as e:
            return [{"error": str(e)}]
        constraints = parser.extract_constraints(raw)
        return [
            {"severity": c.severity, "text": c.text, "line": c.line}
            for c in constraints
        ]
