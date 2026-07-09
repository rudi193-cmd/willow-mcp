"""Tests for gates_panel.py — the unified on/off view over every gate.

Focuses on the read model (`collect`) staying honest about what each
underlying module (`consent`, `lease`, `gate`, `heartbeat`, identity
bindings) reports, and on the two renderers not blowing up or mangling
their input.
"""
import json

import pytest

from willow_mcp import gates_panel, lease, manifest_admin


@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    root = tmp_path / "mcp_apps"
    root.mkdir()
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(root))
    monkeypatch.delenv("WILLOW_MCP_STRICT_TRUST_ROOT", raising=False)
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("WILLOW_MCP_FLEET_HOME", raising=False)
    monkeypatch.delenv("WILLOW_MCP_FLEET_PG_DB", raising=False)
    return root


def _row(rows, row_id):
    return next(r for r in rows if r.id == row_id)


def test_list_app_ids_skips_reserved_dirs(apps_root):
    (apps_root / "real_app").mkdir()
    (apps_root / "_net_leases").mkdir()
    (apps_root / "_identity_bindings").mkdir()
    assert gates_panel.list_app_ids() == ["real_app"]


def test_collect_reflects_manifest_permission_state(apps_root):
    manifest_admin.set_permission("testapp", "store_read", True)
    rows = gates_panel.collect("testapp")
    on = _row(rows, "perm.testapp.store_read")
    off = _row(rows, "perm.testapp.store_write")
    assert on.state == "on"
    assert off.state == "off"
    assert off.action_cli == "willow-mcp allow-permission testapp store_write"
    assert on.action_cli == "willow-mcp deny-permission testapp store_read"


def test_collect_reflects_active_lease_with_timer(apps_root):
    lease.grant("testapp", 1800, issuer="operator", reason="testing")
    row = _row(gates_panel.collect("testapp"), "lease.testapp")
    assert row.state == "on"
    assert row.timer_shape == "lease"
    assert row.remaining_seconds is not None and row.remaining_seconds <= 1800
    assert row.action_cli == "willow-mcp revoke-net testapp"


def test_collect_reflects_absent_lease(apps_root):
    row = _row(gates_panel.collect("testapp"), "lease.testapp")
    assert row.state == "off"
    assert "grant-net" in row.action_cli


def test_collect_consent_rows_are_never_actionable_via_cli(apps_root):
    """consent.py is a read-only consumer by design — the panel must never
    offer a CLI command that would write settings.global.json from here."""
    rows = gates_panel.collect()
    for key in ("internet", "cloud_llm", "lan"):
        row = _row(rows, f"consent.{key}")
        assert row.action_cli is None
        assert row.action_note is not None


def test_collect_env_gates_are_process_lifetime_not_actionable(apps_root):
    rows = gates_panel.collect()
    for gate_id in ("strict_trust_root", "severance", "human_orchestrator"):
        row = _row(rows, gate_id)
        assert row.action_cli is None
        assert "restart" in row.action_note


def test_collect_defaults_to_every_app(apps_root):
    manifest_admin.set_permission("app_a", "store_read", True)
    manifest_admin.set_permission("app_b", "store_read", True)
    rows = gates_panel.collect()
    scopes = {r.scope for r in rows}
    assert "app_a" in scopes and "app_b" in scopes


def test_collect_scoped_to_one_app_excludes_others(apps_root):
    manifest_admin.set_permission("app_a", "store_read", True)
    manifest_admin.set_permission("app_b", "store_read", True)
    rows = gates_panel.collect("app_a")
    scopes = {r.scope for r in rows if r.id.startswith("perm.")}
    assert scopes == {"app_a"}


def test_render_tui_includes_every_row_label(apps_root):
    manifest_admin.set_permission("testapp", "store_read", True)
    rows = gates_panel.collect("testapp")
    out = gates_panel.render_tui(rows, color=False)
    for row in rows:
        assert row.label in out


def test_render_html_is_self_contained_and_escapes_script_boundary(apps_root):
    manifest_admin.set_permission("testapp", "store_read", True)
    rows = gates_panel.collect("testapp")
    html = gates_panel.render_html(rows, "2026-01-01T00:00:00+00:00")
    assert "<!doctype html>" in html
    assert html.count("<script>") == html.count("</script>") == 1
    # The embedded JSON payload must be parseable back out.
    start = html.index("const ROWS = ") + len("const ROWS = ")
    end = html.index(";\n", start)
    payload = json.loads(html[start:end])
    assert any(r["id"] == "perm.testapp.store_read" for r in payload)


def test_render_html_escapes_embedded_script_close_tag(apps_root):
    """A detail/reason string containing a literal '</script>' must not be
    able to break out of the inline <script> block."""
    lease.grant("testapp", 60, issuer="op", reason="</script><script>evil()</script>")
    rows = gates_panel.collect("testapp")
    html = gates_panel.render_html(rows, "2026-01-01T00:00:00+00:00")
    # A stray literal "<script>" in embedded text data is inert (the HTML
    # tokenizer inside a script element only looks for the closing tag), but
    # an unescaped "</script>" would end the block early and let the rest of
    # the payload be parsed as HTML/script — that's the one occurrence that
    # must not survive render_html's escaping.
    assert html.count("</script>") == 1  # only the template's own closing tag
    assert "<\\/script>" in html  # the payload's literal close-tag was neutralized
