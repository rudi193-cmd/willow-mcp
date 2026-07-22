"""S1 authority_check — deterministic policy-decision point (PDP).

Answers whether a principal may perform an act on a resource, with a citation
on allow or the missing authority named on deny. Never a model call; reads only
app manifests and the envelope registry. No mutable state.

Feature flag ``WILLOW_MCP_AUTHORITY_CHECK`` (default off) wires this into
``server._gate()`` instead of ``gate.permitted()``. When enabled:

* Denials use the ``authority denied:`` prefix (legacy path: ``gate denied:``).
* Malformed manifests fail closed with explicit reasons (e.g. ``permissions``
  must be a list); legacy ``permitted()`` treats some malformed shapes as a
  generic deny without naming the defect.
* ``deny_tools`` and empty/missing manifests are denied with named
  ``missing_authority`` — behavior aligned with fail-closed PDP semantics.

Flipping the flag is an operator act; landing this module does not change live
gate behavior until the flag is set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import gate
from .envelopes import EnvelopeAuthority

# Action verb for MCP tool calls through the gate seam.
ACTION_MCP_TOOL = "mcp_tool"


@dataclass(frozen=True)
class Decision:
    """Policy outcome. ``citation`` grounds an allow; ``missing_authority`` names
    what a deny lacked."""

    allowed: bool
    reason: str
    citation: Optional[str] = None
    missing_authority: Optional[str] = None


class _ReadOnlyMeter:
    """Envelope quota checks without mutating or requiring Postgres."""

    def citation_count(self, envelope_id: str) -> int:
        return 0


def authority_check(
    principal: str,
    action: str,
    resource: str,
    context: Optional[dict[str, Any]] = None,
) -> Decision:
    """Decide whether ``principal`` may perform ``action`` on ``resource``.

    * ``action == ACTION_MCP_TOOL`` — ``resource`` is the MCP tool name;
      manifest permission groups / literal grants are consulted.
    * Otherwise — envelope-governed verb: ``resource`` is the envelope id,
      ``action`` is the syscall verb, and ``context['call_args']`` supplies
      bounds to validate field-by-field.
    """
    if action == ACTION_MCP_TOOL:
        return _check_mcp_tool(principal, resource)
    return _check_envelope(principal, action, resource, context or {})


def _check_mcp_tool(principal: str, tool_name: str) -> Decision:
    if not gate.valid_app_id(principal):
        return Decision(
            allowed=False,
            reason=f"invalid principal: {principal!r}",
            missing_authority="valid_app_id",
        )

    manifest = gate._load_manifest(principal)
    if manifest is None:
        return Decision(
            allowed=False,
            reason=f"no manifest for principal {principal!r}",
            missing_authority="manifest",
        )

    perms = manifest.get("permissions")
    if not isinstance(perms, list):
        return Decision(
            allowed=False,
            reason="malformed manifest: permissions must be a list",
            missing_authority="permissions",
        )
    if not perms:
        return Decision(
            allowed=False,
            reason=f"empty permissions for {principal!r}",
            missing_authority="permissions",
        )

    deny = manifest.get("deny_tools")
    if deny is not None and not isinstance(deny, list):
        return Decision(
            allowed=False,
            reason="malformed manifest: deny_tools must be a list",
            missing_authority="deny_tools",
        )
    if isinstance(deny, list) and tool_name in deny:
        return Decision(
            allowed=False,
            reason=f"tool {tool_name!r} blocked by deny_tools",
            missing_authority=f"deny_tools:{tool_name}",
        )

    for perm in perms:
        group = gate.PERMISSION_GROUPS.get(perm)
        if group is not None and tool_name in group:
            return Decision(
                allowed=True,
                reason=f"manifest grants {tool_name!r} via group {perm!r}",
                citation=perm,
            )
        if group is None and perm == tool_name:
            return Decision(
                allowed=True,
                reason=f"manifest grants {tool_name!r} via literal permission",
                citation=perm,
            )

    return Decision(
        allowed=False,
        reason=f"principal {principal!r} not granted tool {tool_name!r}",
        missing_authority=tool_name,
    )


def _check_envelope(
    principal: str,
    verb: str,
    envelope_id: str,
    context: dict[str, Any],
) -> Decision:
    call_args = context.get("call_args")
    if not isinstance(call_args, dict):
        return Decision(
            allowed=False,
            reason="malformed context: call_args must be a dict",
            missing_authority="call_args",
        )

    result = EnvelopeAuthority(_ReadOnlyMeter()).check(
        envelope_id,
        actor=principal,
        verb=verb,
        call_args=call_args,
    )
    if result.get("ok"):
        return Decision(
            allowed=True,
            reason="envelope grants act",
            citation=envelope_id,
        )

    errno = result.get("errno", "EAMBIG")
    reason = result.get("reason") or errno
    missing = _missing_envelope_authority(errno, envelope_id, verb, result)
    return Decision(
        allowed=False,
        reason=reason,
        missing_authority=missing,
    )


def _missing_envelope_authority(
    errno: str,
    envelope_id: str,
    verb: str,
    result: dict,
) -> str:
    if errno == "ENOENT":
        return f"envelope:{envelope_id}"
    if errno == "EACCES":
        return f"grantee:{envelope_id}"
    if errno == "EAMBIG":
        fields = result.get("fields")
        if fields:
            return f"bounds:{','.join(fields)}"
        return f"verb:{verb}"
    if errno == "EEXPIRED":
        return f"expiry:{envelope_id}"
    if errno == "EDQUOT":
        return f"quota:{envelope_id}"
    return f"envelope:{envelope_id}"
