---
b17: WMCP1
title: Security Audit — willow-mcp
date: 2026-05-06
auditor: Vishwakarma (Claude Code, Haiku 4.5)
status: open
---

# Security Audit — willow-mcp

Part of Level 2 full-fleet security audit. willow-mcp — MCP server providing Store (SQLite), Knowledge (Postgres), and Tasks (Kart integration) to fleet agents via stdio transport.

## Rubric Results

| # | Check | Status | Notes |
|---|---|---|---|
| R1 | SQL injection | ✅ PASS | All Postgres queries use parameterized execute(); no raw string interpolation |
| R2 | Shell injection | ✅ PASS | No subprocess.run(), os.system(), or shell= calls; task submission to Kart is message-based |
| R3 | Path traversal | ✅ PASS | Store uses SQLite in fixed location; no user-controlled path operations |
| R4 | Hardcoded credentials | ✅ PASS | No credentials in code; auth via SAP/1.0 gate (app_id required) |
| R5 | CORS wildcard | N/A | Not applicable — stdio transport, not HTTP |
| R6 | XSS | N/A | Not applicable — server returns JSON, no HTML rendering |
| R7 | Unsigned code execution | ✅ PASS | No eval(), exec(), or dynamic imports; all tools are static MCP definitions |
| R8 | Missing auth on APIs | ✅ PASS | All tools require app_id; SAP gate checks authorization via openclaw_sap_gate |
| R9 | Bare except swallowing errors | ⚠️ WARN | ImportError for openclaw_sap_gate caught silently (line 24-28); falls back to no auth if unavailable |
| R10 | Predictable temp paths | ✅ PASS | No temp files created; uses Postgres and SQLite for persistence |
| R11 | Race conditions | ✅ PASS | Server is async-safe; Store operations are atomic via SQLite transactions |
| R12 | safe_integration.py status() | ❌ MISSING | No safe_integration.py — no Willow integration point or status() function |
| R13 | Entry point importable | ✅ PASS | __main__.py exists and runs mcp.server.stdio.stdio_server(); can import willow_mcp |
| R14 | requirements.txt pinned | ⚠️ WARN | requirements.txt exists but unpinned (mcp, psycopg2 without versions) |
| R15 | No hardcoded dev paths | ✅ PASS | No /home/sean or machine-specific paths in code |

## Findings

### P1: L-INT-01 — No safe_integration.py / Willow integration point

**Severity:** P1  
**Status:** Open

WLWR1 R12 requires `safe_integration.py` with a `status()` function for Willow bus integration.

willow-mcp is an MCP server but lacks reverse integration — Willow cannot query its status or lifecycle.

**Fix:** Create `safe_integration.py`:
```python
def status():
    return {
        "app_id": "willow-mcp",
        "version": "0.1.0",
        "status": "running",
        "tools_registered": 8,
    }
```

**Impact:** Server is invisible to Willow orchestration / Level 3 audit. Cannot be managed as fleet member.

---

### P2: L-REQ-01 — requirements.txt unpinned

**Severity:** P2  
**Status:** Open

requirements.txt exists but dependencies lack version pinning:
```
mcp
psycopg2
```

Should pin all transitive dependencies:
```
mcp==0.7.0
psycopg2==2.9.9
```

**Impact:** Users may install incompatible versions. Reproducibility gap.

---

### P2: L-AUTH-01 — Silent fallback on missing SAP gate

**Severity:** P2  
**Status:** Open

Lines 24-28: ImportError for `openclaw_sap_gate` is caught silently. If the module is unavailable, auth is disabled entirely:
```python
try:
    from openclaw_sap_gate import authorized as _sap_authorized
    _SAP_AVAILABLE = True
except ImportError:
    _SAP_AVAILABLE = False  # Silently disables auth
```

The `_auth()` function then allows all requests when `_SAP_AVAILABLE` is False (line 37-38):
```python
if not _SAP_AVAILABLE:
    return True, ""  # Auth disabled
```

**Fix:** Fail hard if SAP gate is required:
```python
try:
    from openclaw_sap_gate import authorized as _sap_authorized
except ImportError as e:
    sys.exit(f"ERROR: openclaw_sap_gate required but not found: {e}")
```

Or make it explicit in configuration (environment variable):
```python
_SAP_REQUIRED = os.environ.get("WILLOW_SAP_REQUIRED", "true").lower() == "true"
```

**Impact:** If deployment lacks SAP gate (misconfiguration or missing dependency), server runs with no auth. Moderate.

---

## Summary

| Priority | Count | Items |
|---|---|---|
| P0 | 0 | — |
| P1 | 1 | L-INT-01 (no safe_integration.py) |
| P2 | 2 | L-REQ-01 (unpinned requirements.txt), L-AUTH-01 (silent auth fallback) |

**Assessment:** This is a well-architected MCP server with sound security practices:
- ✅ Parameterized SQL queries (no injection)
- ✅ SAP/1.0 auth gating on all tools
- ✅ Async-safe operations, no file temp paths
- ✅ No eval/exec/dynamic imports
- ✅ Proper use of MCP SDK

**Recommendation:** L-INT-01 (P1) is required for fleet integration. L-REQ-01 and L-AUTH-01 (P2) are operational hardening. All addressable without refactoring.

*ΔΣ=42*
