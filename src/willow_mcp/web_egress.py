"""Egress gate for willow_web_search / willow_web_fetch (server-process HTTP)."""

from __future__ import annotations

from typing import Optional


def egress_denial(app_id: str) -> Optional[dict]:
    """Three-key check keyed on web_net — mirror of integrations.egress_denial."""
    from . import consent, gate, lease

    if not gate.permitted(app_id, gate.WEB_NET_PERMISSION):
        return {"error": (
            f"net_denied: open-web tools require the '{gate.WEB_NET_PERMISSION}' "
            f"permission in this app's manifest ($WILLOW_HOME/mcp_apps/"
            f"{app_id or '<app_id>'}/manifest.json). It is not granted by "
            f"'{gate.NET_PERMISSION}', '{gate.INTEGRATION_NET_PERMISSION}', "
            "integration_call, or full_access — egress is granted on its own line.")}

    if not consent.internet_permitted():
        return {"error": (
            "consent_denied: open-web tools also require the operator's standing "
            f"'consent.internet' in {consent.settings_path()}. This app holds "
            f"'{gate.WEB_NET_PERMISSION}', but egress is switched off (or the "
            "consent policy could not be read, which denies).")}

    lease_state = lease.read_lease(app_id)
    if lease_state["status"] != "active":
        return {"error": (
            f"lease_denied: open-web tools require an unexpired egress lease for "
            f"'{app_id}' (status: {lease_state['status']}"
            + (f" — {lease_state['error']}" if lease_state.get("error") else "")
            + "). Leases are issued only by the operator via `willow-mcp grant-net "
            f"{app_id or '<app_id>'} --ttl 30m --reason ...` and they expire. "
            "No MCP tool can mint one.")}

    if lease.strict_trust_root():
        forgeable = lease.self_writable_trust_paths(app_id)
        if forgeable:
            return {"error": (
                "trust_root_denied: WILLOW_MCP_STRICT_TRUST_ROOT is set, but this "
                "process can write the very keys that authorize it: "
                + ", ".join(f"{f['key']} ({f['path']})" for f in forgeable)
                + ". Chown these to a uid the agent does not run as.")}
    return None
