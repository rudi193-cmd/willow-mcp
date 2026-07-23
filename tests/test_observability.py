"""Deny-by-default telemetry scrub — the fix for un-gated Sentry egress.

These tests demonstrate the bug and lock the fix: a naive Sentry init on
willow-mcp would ship stack-frame locals, breadcrumbed queries, and vault paths
to an external SaaS. observability._scrub_event rebuilds every event from an
allow-list, so nothing sensitive can cross even if sentry-sdk captures it.
No network and no sentry-sdk install required — the scrub functions are pure.
"""
from __future__ import annotations

import os
from unittest import mock

from willow_mcp import observability as obs


def test_init_is_noop_without_dsn():
    with mock.patch.dict(os.environ, {}, clear=True):
        status = obs.init_observability()
    assert status["enabled"] is False
    assert "fail-closed" in status["reason"]


def test_init_disabled_when_sdk_missing():
    # DSN present but the extra isn't installed -> still disabled, never raises.
    with mock.patch.dict(os.environ, {"WILLOW_SENTRY_DSN": "https://k@o.ingest.sentry.io/1"}, clear=True):
        with mock.patch.dict("sys.modules", {"sentry_sdk": None}):
            status = obs.init_observability()
    assert status["enabled"] is False


def test_scrub_drops_stack_frame_locals():
    event = {
        "level": "error",
        "exception": {
            "values": [{
                "type": "ValueError",
                "value": "boom",
                "stacktrace": {"frames": [{
                    "filename": "server.py",
                    "function": "handle",
                    "lineno": 42,
                    "vars": {"lease_token": "SECRET-LEASE-abc123", "app_id": "willow"},
                }]},
            }]
        },
    }
    scrubbed = obs._scrub_event(event)
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame                      # locals never cross
    assert frame["function"] == "handle"            # structure preserved
    assert frame["lineno"] == 42


def test_scrub_drops_unknown_top_level_keys():
    event = {
        "level": "error",
        "request": {"headers": {"Authorization": "Bearer sk-live-xyz"}},
        "extra": {"consent": {"internet": True}, "vault_path": "/home/x/sean-data-vault/k"},
        "user": {"id": "sean", "email": "rudi193@gmail.com"},
        "server_name": "the-real-hostname",
    }
    scrubbed = obs._scrub_event(event)
    assert "request" not in scrubbed                # dropped wholesale
    assert "extra" not in scrubbed
    assert "user" not in scrubbed
    assert scrubbed["server_name"] == "willow-mcp"  # never the real hostname


def test_scrub_redacts_vault_path_in_message():
    event = {
        "level": "error",
        "exception": {"values": [{
            "type": "FileNotFoundError",
            "value": "no such file: /home/sean/sean-data-vault/secret.md",
        }]},
    }
    scrubbed = obs._scrub_event(event)
    val = scrubbed["exception"]["values"][0]["value"]
    assert "sean-data-vault" not in val
    assert val == obs._REDACTED


def test_scrub_redacts_secret_paths_in_frame_filename():
    event = {
        "level": "error",
        "exception": {"values": [{
            "type": "OSError",
            "stacktrace": {"frames": [{
                "filename": "/home/x/.willow/leases/active.json",
                "function": "load",
                "lineno": 7,
            }]},
        }]},
    }
    frame = obs._scrub_event(event)["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame["filename"] == obs._REDACTED
    assert frame["lineno"] == 7


def test_transaction_scrub_strips_span_data():
    txn = {
        "type": "transaction",
        "transaction": "task_submit",
        "spans": [{
            "op": "db.query",
            "description": "SELECT * FROM kb WHERE secret='...'",  # data-bearing
            "data": {"sql": "SELECT ..."},
            "span_id": "abc",
        }],
    }
    scrubbed = obs._scrub_transaction(txn)
    span = scrubbed["spans"][0]
    assert "description" not in span                # SQL text never crosses
    assert "data" not in span
    assert span["op"] == "db.query"                 # shape/timing preserved
    assert span["span_id"] == "abc"


def test_exposure_registers_sentry_as_telemetry_destination():
    # The membrane's own answer for "what may cross to Sentry?" is: nothing.
    from willow_mcp import exposure
    preset, _ = exposure.resolve_preset("willow", "sentry")
    assert preset == "telemetry"
    assert exposure.PRESET_FIELDS["telemetry"] == ()
    assert exposure.apply_field_paths({"persona": {"register": "x"}},
                                      list(exposure.PRESET_FIELDS["telemetry"])) == {}
