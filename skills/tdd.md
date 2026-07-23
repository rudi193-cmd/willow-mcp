---
name: tdd
description: Test-driven development for willow-mcp — pytest, real Postgres where needed, mock MCP at the Python boundary
---

@markdownai v1.0

# /tdd

Strict red/green/refactor for changes where tests are the contract.

## Rules

- Tests live under `tests/` and run with `pytest` (see `CONTRIBUTING.md`).
- **Never mock the database** when the behavior under test is SQL or schema-backed —
  use the real Postgres fixtures (`PGHOST`, etc.) or the in-memory SQLite paths the
  suite already provides.
- Each behavior is tested in isolation. Mock **MCP transport**, not the code you own.
- Hook handlers: test by passing mock stdin and capturing stdout (see below).
- Commit each green state. Never batch test + implementation into one commit.

## Cycle

1. **Write the failing test first.** Run it. Confirm it fails with the expected error —
   `ImportError`, `AssertionError`, not a crash.
2. **Write the minimum code to pass.** No extra logic, no preemptive abstractions.
3. **Run the test.** Green → commit → next test. Red → fix only what the test says.

## Running tests

```bash
# full suite
.venv/bin/python3 -m pytest tests/ -q

# one file or test
.venv/bin/python3 -m pytest tests/test_foo.py::test_bar -q
```

CI runs the same suite on every PR (`.github/workflows/tests.yml`).

## MCP boundary mocking

When testing a tool handler that would call another layer, patch at the Python import
site — not the wire protocol:

```python
from unittest.mock import patch

def test_behavior_calls_store(tmp_path, home):
    with patch("willow_mcp.some_module.store_put") as mock_put:
        mock_put.return_value = {"status": "ok"}
        result = my_behavior("arg")
    mock_put.assert_called_once()
```

## Hook handler test pattern

```python
import json
from io import StringIO
from unittest.mock import patch

def _run_hook(stdin_data: dict) -> str:
    import willow_mcp.bundle.hooks.pre_tool_use as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()
```

Prefer testing the pure helper functions in `pre_tool_use.py` directly when the hook
entrypoint is heavy.

## Layout / home fixtures

Many tests use the `home` fixture from `tests/conftest.py` — an isolated `$WILLOW_HOME`
under `tmp_path`. Call `home_init.ensure_home_layout()` when the test needs bundled
skills, hooks, or manifests materialized.

## Bug fixes

Write a regression test that fails on the old behavior, then fix. See `debugging.md`.

## Constraints

@constraint severity=error
Never mock the database when the behavior under test is SQL or schema-backed — use the real Postgres fixtures or the in-memory SQLite paths the suite already provides. Mock the MCP transport, not the code you own. Commit each green state; never batch test + implementation into one commit.
