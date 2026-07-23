---
kind: doc
name: willow-mcp-security-hardening-review-2026-07-08
description: "External review of willow-mcp covering security hardening, performance, architecture, testing/reliability, developer experience, and observability, with a prioritized action list and a 7.5/10 overall score."
---

@markdownai v1.0

<!--
PROVENANCE: converted 2026-07-13 (session e2b2a0da, willow seat) from
~/Desktop/Nest/"Security Hardening Deep.txt" (nest intake, mtime 2026-07-08
12:32, claude.ai-era export). Byte-faithful copy; only this header added.
SIBLING of docs/design/mcp-review-2026-07-08.md (0a3946d, same day) — that one
is Kart-specific; this one sweeps security / performance / architecture /
testing / observability / DX, scoring 7.5/10 overall.

ABSORPTION LEDGER vs willow-mcp @ dcb87d2 (2026-07-13 check):
  ALREADY ADDRESSED since 07-08 (fully or in part):
    sandbox-honesty documentation → B-37/B-38 filed (#58), B-39 (#67),
    B-19 task_net manifest gating · time-boxed egress leases (B-32)
    fleet heartbeat/stale-agent rec → B-26 worker heartbeat (#66) +
    willow-2.0 watchmen loop_heartbeat (#786) · severance now asserted
    not narrated (#57)
  STILL OPEN (this file is the local spec; overlaps packet §10 checklist):
    SECURITY.md / threat model · rate limiting · parameterized-SQL audit ·
    willow-mcp check config validation · /health endpoint · structured JSON
    logs · Prometheus /metrics · connection pooling · graceful shutdown ·
    integration + security-regression tests · YAML config · feature flags ·
    caching · performance benchmarks
  CHARTER TIE-IN: the priority list is willow-gate PR #1 (hardening plan
  H1–H7) adjacent — reconcile before ratifying either.
UNRATIFIED external review — adoption decisions are the operator's.
-->

## 🔐 Security Hardening Deep Dive

### What You're Doing Well (Keep This)

| Feature | Why It's Good |
| :--- | :--- |
| **Manifest-based ACL** | Fail-closed by default. No manifest = no access. Clean separation of auth (who) from perms (what). |
| **Schema confirmation workflow** | Prevents accidental writes to misidentified tables. The `preview=True` sample row is excellent UX. |
| **diagnostic_summary ungated** | Correctly scoped. It discloses only the caller's own config, not fleet rows/secrets. This is the right trade-off. |
| **OAuth 2.0 + PKCE** | Gold standard for delegated auth. Using Google/Apple as IdPs offloads credential management. |
| **Identity binding confirmation** | Operator-controlled (`willow-mcp confirm-binding`), never tool-accessible. This prevents privilege escalation. |
| **Soft delete in SOIL** | `store_delete` is soft-delete. You're not losing data accidentally. |

### Potential Hardening Opportunities

@phase 1-shell-command-injection-in-task-queue
#### 1. **Shell Command Injection in Task Queue**
```python
# Risk: If task_submit takes free-form shell commands without sanitization
# Current: "sandboxed task executor" - but what does "sandboxed" actually mean?

# Recommended: Explicitly document the sandbox boundaries
# - Is it chrooted? 
# - Are resource limits (CPU, memory, runtime) enforced?
# - Can it access network? 
# - Does it run as a dedicated low-privilege user?
```

**Action items:**
- Add a `SECURITY.md` section detailing task sandbox implementation
- Consider adding `task_submit` parameter validation: `command` should be a whitelist of allowed binaries, not a free string
- Document that `task_submit` is **disabled by default** (require explicit manifest permission)

@phase 2-environment-variable-exposure-in-serve-mode
#### 2. **Environment Variable Exposure in Serve Mode**
Your README already warns about this, which is good. But you could go further:

```python
# In serve mode startup, explicitly log which env vars are being used
# This helps debug the "systemd doesn't see my shell export" problem

# src/willow_mcp/serve.py
def log_effective_config():
    logger.info(f"WILLOW_PG_DB={os.getenv('WILLOW_PG_DB', 'default')}")
    logger.info(f"WILLOW_STORE_ROOT={os.getenv('WILLOW_STORE_ROOT', 'default')}")
    # ... log all config values at startup
```

**Action:**
- Add a `--debug-config` flag to `willow-mcp --serve` that prints all resolved config values
- In systemd unit, explicitly set `EnvironmentFile=-/etc/willow-mcp.conf` so users have a clear place to put config

@phase 3-api-rate-limiting
#### 3. **API Rate Limiting**
No indication of rate limiting in the current design. This matters because:
- `store_search` and `knowledge_search` could be expensive
- `task_submit` could overwhelm the system
- No token bucket or request throttling in HTTP serve mode

**Recommendation:**
```python
# Add a simple per-app_id rate limiter
# Use a sliding window counter in SOIL or a separate Redis cache

RATE_LIMITS = {
    "store_search": 100,  # per minute
    "task_submit": 10,    # per minute
    "knowledge_search": 50,
}
```

@phase 4-input-validation-depth
#### 4. **Input Validation Depth**
I can't see your internal validation, but ensure:
- All `app_id` values are sanitized (no `../` path traversal in the filesystem lookup)
- `record_id` in `store_get` is validated as an integer or UUID (no injection into SQLite queries)
- `collection` names in `store_list` only allow `[a-zA-Z0-9_-]`
- Postgres query parameters use parameterized queries (not string interpolation)

**Check:** Scan your codebase for `f"SELECT ... WHERE {user_input}"` patterns.

@phase 5-manifest-file-permissions
#### 5. **Manifest File Permissions**
```bash
# Who can create/modify manifests?
$WILLOW_HOME/mcp_apps/<app_id>/manifest.json

# Consider:
# - The operator must have explicit control
# - There's no route for a caller to self-provision (good)
# - But ensure filesystem permissions on ~/.willow/ are 0700
```

**Action:** Document the expected filesystem permissions in the README.

@phase 6-logging-audit-trail
#### 6. **Logging & Audit Trail**
Your `receipts_tail` tool is excellent. Enhance with:
```python
# Structured logging (JSON) for all tool calls
# Include: timestamp, app_id, tool_name, args (redacted), duration, status

# This enables:
# - SIEM integration
# - Security incident investigation
# - Performance monitoring
```

**Action:** Add structured JSON logging; provide an optional `WILLOW_JSON_LOGS=1` env var.

---

## ⚡ Performance Optimization Deep Dive

### Current Design Assessment
| Component | Performance Profile | Bottleneck Risk |
| :--- | :--- | :--- |
| **SOIL (SQLite)** | Fast for <100K records. Full-text search uses SQLite FTS5. | `store_search_all` across collections could be heavy. |
| **Postgres KB** | Depends on indexes. `knowledge_search` likely uses `ILIKE` or `tsvector`. | Missing indexes = slow search. |
| **Kart Task Queue** | Async by nature. Good for offloading. | Queue depth management, resource limits. |
| **Context store** | SOIL-backed with TTL. Good. | Expired keys cleanup could cause overhead. |

### Optimization Recommendations

@phase 1-soil-sqlite-performance
#### 1. **SOIL (SQLite) Performance**
```sql
-- Ensure these indexes exist
CREATE INDEX IF NOT EXISTS idx_store_collection ON store(collection, app_id);
CREATE INDEX IF NOT EXISTS idx_store_soft_delete ON store(soft_deleted_at);
-- FTS5 table already handles full-text, but verify coverage
```

**Action:**
- Add `WILLOW_STORE_PAGE_SIZE` env var to tune SQLite page size (default 4096)
- Document that `store_list` with no filters should be paginated (or add a `limit` param)
- Consider adding `ANALYZE;` after bulk operations to keep query planner fresh

@phase 2-postgres-knowledge-base-performance
#### 2. **Postgres Knowledge Base Performance**
```sql
-- Recommended indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kb_owner ON knowledge_base(owner_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kb_domain ON knowledge_base(domain);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kb_tags ON knowledge_base USING GIN(tags);
-- For full-text search
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kb_fts ON knowledge_base USING GIN(to_tsvector('english', content));
```

**Action:**
- Add a `knowledge_index_status` tool that reports which indexes exist
- Mention required Postgres extensions (`pg_trgm` for fuzzy search, if you use it)
- Document that `knowledge_search` performance is **index-dependent**

@phase 3-task-queue-kart
#### 3. **Task Queue (Kart)**
```python
# Consider these queue management parameters
TASK_QUEUE_MAX_SIZE = 1000        # Reject new tasks if queue too large
TASK_MAX_RUNTIME = 300            # 5 minutes per task
TASK_MAX_OUTPUT_SIZE = 10 * 1024  # 10KB max output capture
TASK_CLEANUP_AGE = 3600 * 24 * 7  # Keep completed tasks for 7 days
```

**Action:**
- Expose these as env vars with sensible defaults
- Document in the README under "Task Queue Configuration"

@phase 4-http-serve-mode-performance
#### 4. **HTTP Serve Mode Performance**
```python
# Use an async HTTP server (you appear to be using something like uvicorn)
# Ensure:
# - Worker count = (2 * CPU cores) + 1
# - Keep-Alive timeout reasonable (e.g., 60s)
# - Max request size = 10MB (prevent DoS)

# In your serve startup code:
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        workers=min(os.cpu_count() * 2 + 1, 8),
        loop="uvloop",  # faster
        timeout_keep_alive=60,
        max_body_size=10 * 1024 * 1024,
    )
```

**Action:** Document recommended `uvicorn` settings in the serve mode section.

@phase 5-caching-strategy
#### 5. **Caching Strategy**
Consider adding optional caching for:
- `schema_confirm_mapping` results (mapping is usually static)
- `knowledge_search` results that are frequently queried
- `store_get` for hot records

```python
# Simple cache layer (TTL-based) using an in-memory dict or Redis
CACHE_TTL = {
    "schema_mapping": 3600,   # 1 hour
    "knowledge_search": 300,  # 5 minutes
    "store_get": 60,          # 1 minute
}
```

**Action:** Add a `WILLOW_CACHE_TTL` env var and document the caching behavior.

---

## 🏗️ Architecture Deep Dive

### What's Already Strong

| Aspect | Assessment |
| :--- | :--- |
| **Separation of Concerns** | Store, KB, Queue, Context, Auth are cleanly separated. |
| **Fail-Closed Security** | Every tool requires `app_id`; no manifest = no access. |
| **Schema Adaptation** | Dynamic schema detection + confirmation is elegant. |
| **Diagnostic Tools** | `diagnostic_summary` and `receipts_tail` are production-ready. |

### Architectural Refinements

@phase 1-database-connection-pooling
#### 1. **Database Connection Pooling**
```python
# Currently: likely creates a new connection per request
# Better: Use a connection pool

# For Postgres:
from psycopg_pool import AsyncConnectionPool

pool = AsyncConnectionPool(
    min_size=1,
    max_size=10,
    conninfo=f"dbname={DB_NAME} user={DB_USER}",
)
```

**Action:** Ensure both SOIL and Postgres use connection pooling in serve mode. Add `WILLOW_PG_POOL_SIZE` env var.

@phase 2-health-check-endpoint
#### 2. **Health Check Endpoint**
Your `diagnostic_summary` is good, but for HTTP serve mode, add a dedicated health endpoint:
```python
# /health endpoint (no auth required)
{
    "status": "ok",
    "version": "2.0.0",
    "backend": {
        "postgres": "connected",
        "store": "writable",
        "queue": "operational"
    }
}
```

**Action:** Add `GET /health` that checks all backends. Useful for Kubernetes liveness/readiness probes.

@phase 3-graceful-shutdown
#### 3. **Graceful Shutdown**
```python
# In serve mode, handle SIGTERM/SIGINT
# - Drain existing requests
# - Close database connections
# - Flush logs
# - Exit with 0

import signal
signal.signal(signal.SIGTERM, graceful_shutdown)
```

**Action:** Add graceful shutdown handling to prevent connection leaks.

@phase 4-configuration-validation-on-startup
#### 4. **Configuration Validation on Startup**
```python
# Validate all required config at startup, not lazily
# This prevents "half-working" serve mode

def validate_config():
    # Check Postgres connection
    # Check store directory is writable
    # Check manifest directory exists
    # Check OAuth credentials are present (if serve mode)
    # Exit with clear error message on failure
```

**Action:** Add a `willow-mcp check` command that validates config without starting the server. Useful for operators.

@phase 5-feature-flags
#### 5. **Feature Flags**
```python
# Allow enabling/disabling tools at build time or runtime
FEATURES = {
    "postgres_kb": True,      # If False, knowledge_* tools return 501
    "task_queue": True,       # If False, task_* tools return 501
    "serve_mode": True,       # If False, only stdio works
    "audit_trail": True,      # If False, receipts_tail returns 501
}

# Use env var: WILLOW_FEATURES=postgres_kb,task_queue
```

**Action:** Add feature flags to let users disable parts they don't need, reducing attack surface and resource usage.

---

## 🧪 Testing & Reliability Deep Dive

### Current Testing Gaps (Based on repo structure)

| Area | What Exists | Gap |
| :--- | :--- | :--- |
| **Unit Tests** | `tests/` directory exists | Coverage unknown |
| **Integration Tests** | Likely minimal | Need tests against real Postgres |
| **Security Tests** | `SECURITY_AUDIT.md` | No automated security regression tests |
| **Performance Tests** | None | Need benchmarking suite |

### Testing Recommendations

@phase 1-unit-test-coverage-target
#### 1. **Unit Test Coverage Target**
```bash
# Aim for 80%+ coverage on critical paths:
# - Authorization (gate.py)
# - All tool handlers
# - Schema confirmation
# - Error handling

# Use pytest-cov
pytest --cov=willow_mcp --cov-report=html
```

**Action:** Add a GitHub Action that enforces coverage thresholds on PRs.

@phase 2-integration-test-suite
#### 2. **Integration Test Suite**
```python
# test_integration.py
# Spin up a test Postgres container, SOIL directory, and test all tools
# Use pytest-docker or testcontainers

def test_store_put_get():
    # Real SQLite file, not in-memory (to test file locking)
    pass

def test_knowledge_search():
    # Real Postgres with known data
    pass

def test_schema_confirmation():
    # Full workflow: preview -> confirm -> write
    pass
```

**Action:** Add integration tests that run in CI. Use `docker-compose` for Postgres.

@phase 3-security-regression-tests
#### 3. **Security Regression Tests**
```python
# test_security.py
def test_no_manifest_denies():
    # app_id without manifest -> all tools denied

def test_schema_preview_no_write():
    # schema_confirm_mapping(preview=True) doesn't write to DB

def test_serve_mode_unbound_denies():
    # Unbound OAuth identity -> all tools denied

def test_path_traversal_prevention():
    # app_id="../../../etc" -> sanitized or rejected
```

**Action:** Automate your security audit findings as regression tests.

@phase 4-performance-benchmarking
#### 4. **Performance Benchmarking**
```python
# benchmark.py
# Use pytest-benchmark or a custom script

def test_store_search_100k_records(benchmark):
    # Insert 100K records, benchmark search latency
    pass

def test_knowledge_search_1m_terms(benchmark):
    # Test with realistic data
    pass
```

**Action:** Establish a baseline for each major tool. Track performance over time.

@phase 5-chaos-engineering
#### 5. **Chaos Engineering**
```python
# test_chaos.py
# Simulate failures:
# - Postgres connection drop (kill container)
# - Disk full (fill temp directory)
# - OOM conditions (memory limit)
# - Network latency (tc netem)
```

**Action:** Document the behavior under failure (does it crash? retry? timeout?) and test those scenarios.

---

## 🔍 Specific Implementation Recommendations

### Based on the README and Tool List

@phase 1-knowledge-ingest-and-schema-confirmation
#### 1. **`knowledge_ingest` and Schema Confirmation**
Your current workflow requires `schema_confirm_mapping` before writes. This is excellent. Ensure:

```python
# Store the confirmation persistently (SOIL)
# This prevents users from having to confirm on every restart

# Example:
WILLOW_HOME/schemas/<table_name>_mapping.json
{
    "confirmed_at": "2026-07-08T12:00:00Z",
    "confirmed_by": "app_id_xyz",
    "mapping": {"id": "record_id", "content": "text_content", ...},
    "fingerprint": "<hash-of-table-schema>"  # Invalidate if schema changes
}
```

**Action:** Document this persistent mapping store behavior.

@phase 2-context-save-ttl-implementation
#### 2. **`context_save` TTL Implementation**
Ensure expired contexts are purged lazily (on read) AND by a background job:
```python
# background_cleanup.py
# Runs every 60 minutes, purges expired contexts
# Prevents SOIL DB from growing unbounded
```

**Action:** Add `WILLOW_CONTEXT_CLEANUP_INTERVAL` env var (default 3600s).

@phase 3-receipts-tail-audit-trail
#### 3. **`receipts_tail` Audit Trail**
Consider adding:
```python
# Add filtering to receipts_tail
receipts_tail(
    app_id: str,
    since: Optional[datetime] = None,
    limit: int = 100,
    tool_name: Optional[str] = None,
    status: Optional[str] = None,  # "success", "error"
)
```

**Action:** Extend `receipts_tail` with filters for better auditability.

@phase 4-fleet-status-and-agent-routing
#### 4. **`fleet_status` and Agent Routing**
This implies multi-agent support. Ensure:
```python
# Agents are registered with a heartbeat
# fleet_health reports stale agents (>60s no heartbeat)
# agent_route fails if target agent is stale
```

**Action:** Add agent heartbeat timeout and automatic deregistration.

---

## 🛠️ Developer Experience Improvements

### Code Quality
- Add `pre-commit` hooks for linting (`ruff`, `black`, `mypy`)
- Use `pyproject.toml` for all tool configuration (you already have this partially)
- Add type hints everywhere (`mypy --strict`)

### Build/Release Automation
- Add a `Makefile` or `justfile` with common commands:
  ```make
  install-dev:  # pip install -e .[dev]
  test:         # pytest
  lint:         # ruff check
  format:       # ruff format
  check:        # mypy
  build:        # build wheel
  publish:      # publish to PyPI
  ```

### Dockerfile (You Have One)
Optimize it:
```dockerfile
# Multi-stage build
FROM python:3.11-slim AS builder
COPY . /app
RUN pip install --no-cache-dir --user .

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
# Add healthcheck:
HEALTHCHECK --interval=30s --timeout=3s CMD willow-mcp check || exit 1
CMD ["willow-mcp"]
```

### Packaging
- Ensure `pyproject.toml` has all dependencies pinned with version ranges
- Add `extras_require`:
  ```toml
  [project.optional-dependencies]
  postgres = ["psycopg[binary]>=3.0"]
  serve = ["uvicorn[standard]>=0.30"]
  dev = ["pytest>=8", "ruff>=0.5", "mypy>=1.10"]
  ```

---

## 📊 Monitoring & Observability

### Prometheus Metrics
Add `/metrics` endpoint in serve mode:
```python
# Use prometheus_client
from prometheus_client import Counter, Histogram, generate_latest

tool_calls = Counter('mcp_tool_calls_total', 'Total tool calls', ['tool', 'app_id', 'status'])
tool_duration = Histogram('mcp_tool_duration_seconds', 'Tool call duration', ['tool'])

@tool_metrics
def store_get(...):
    # Decorator records duration and success/failure
    pass
```

### Structured Logging (JSON)
```python
import structlog

logger = structlog.get_logger()
logger.info("tool_call", tool="store_get", app_id=app_id, duration_ms=45, status="success")
```

**Action:** Add `WILLOW_JSON_LOGS=1` to enable JSON logging for ELK/Splunk ingestion.

---

## 🔧 Configuration Schema

Consider moving to a YAML config file instead of many env vars:
```yaml
# ~/.willow/config.yaml
postgres:
  dbname: willow
  user: $USER
  pool_size: 5
store:
  root: ~/.willow/store
  page_size: 4096
auth:
  manifest_root: ~/.willow/mcp_apps
  oauth:
    google_client_id: xxx
    google_client_secret: xxx
serve:
  host: 127.0.0.1
  port: 8765
  workers: 4
logging:
  level: INFO
  json: false
features:
  postgres_kb: true
  task_queue: true
```

**Action:** Support YAML config alongside env vars. Env vars take precedence.

---

## 📝 Documentation Enhancements

| Section | Current State | Recommended Addition |
| :--- | :--- | :--- |
| **Security** | `SECURITY_AUDIT.md` | Add a "Threat Model" section (what attacks are mitigated) |
| **Performance** | None | Add a "Performance Tuning" section with index recommendations |
| **Troubleshooting** | Basic | Add common errors and solutions table |
| **Architecture** | None | Add a diagram showing components and data flow |
| **API Reference** | Tool list | Add full OpenAPI/Swagger spec for serve mode |
| **Migration** | None | Add guide for migrating from v1 to v2 |

---

## 🚀 Priority Action Items

Based on this deep dive, here's what I recommend you tackle:

### High Priority (Before 2.0 Release)
1. **Remove "Superseded" notice** from README
2. **Add `willow-mcp check`** command for config validation
3. **Add rate limiting** to prevent DoS
4. **Add structured logging** (JSON)
5. **Add `/health` endpoint** for serve mode
6. **Ensure all SQL uses parameterized queries** (audit your codebase)

### Medium Priority
7. **Add connection pooling** for Postgres
8. **Add integration tests** with real Postgres
9. **Add Prometheus metrics** (`/metrics` endpoint)
10. **Document task sandbox** implementation in detail
11. **Add graceful shutdown** handling

### Nice to Have
12. **YAML config** support
13. **Caching layer** for schema mappings and frequent queries
14. **Feature flags** to disable unused components
15. **Performance benchmarks** in CI

---

@phase final-assessment
## Final Assessment

| Category | Score (1-10) | Notes |
| :--- | :--- | :--- |
| **Security** | 8 | Excellent design; needs rate limiting and input validation audit |
| **Performance** | 6 | Good architecture; needs indexes, pooling, caching |
| **Reliability** | 7 | Good diagnostics; needs integration tests and graceful shutdown |
| **Observability** | 5 | Audit trail is good; needs metrics and structured logging |
| **Developer Experience** | 7 | Good docs; needs linting, pre-commit, and build automation |
| **Overall** | **7.5** | Solid foundation with clear path to 9/10 |

---

Would you like me to:
1. **Provide code snippets** for any of these recommendations (rate limiting, metrics, connection pooling, etc.)?
2. **Audit a specific file** from your codebase (if you share the source)?
3. **Draft a `SECURITY.md`** or threat model document?
4. **Review your `pyproject.toml`** for packaging best practices?
5. **Design a benchmark suite** for your tools?

Just let me know what's most useful!
