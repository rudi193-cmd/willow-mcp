"""tests for scripts/operator-onboard.sh's argument handling.

Found live (2026-07-31, UX audit): every default in this script pointed at
the maintainer's own machine layout (`$HOME/github/.willow/venvs/...`,
`$HOME/github/willow`, app-id `willow`) -- silently wrong for any other
operator who ran it without arguments, and a direct violation of this repo's
own "agent-neutral, no personal/fleet-specific references" convention
(CONTRIBUTING.md). It also had a copy-paste bug: the final "project sync"
hint always printed the literal app-id `willow` rather than the caller's
`$APP_ID`. Fixed by requiring the venv Python, project root, and app-id
explicitly (env var + two positional args) with a usage message instead of
a personal-path default, and by using `$APP_ID` in the sync hint.

These run the real script as a subprocess so a missing-argument regression
shows up as a failing test, not just eyeballing the diff.
"""
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "operator-onboard.sh"


def _run(args, env=None):
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        env=env or {},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_usage_and_failure_when_venv_python_env_var_is_missing():
    result = _run(["/some/project", "someapp"], env={"PATH": "/usr/bin:/bin"})
    assert result.returncode != 0
    assert "Usage:" in result.stderr
    assert "WILLOW_MCP_PYTHON" in result.stderr


def test_usage_and_failure_when_project_root_arg_is_missing():
    result = _run([], env={"PATH": "/usr/bin:/bin", "WILLOW_MCP_PYTHON": "/x/bin/python"})
    assert result.returncode != 0
    assert "Usage:" in result.stderr


def test_usage_and_failure_when_app_id_arg_is_missing():
    result = _run(
        ["/some/project"],
        env={"PATH": "/usr/bin:/bin", "WILLOW_MCP_PYTHON": "/x/bin/python"},
    )
    assert result.returncode != 0
    assert "Usage:" in result.stderr


def test_no_hardcoded_personal_or_fleet_paths_remain():
    """Regression guard for the specific footgun: no default should reference
    a maintainer's home directory layout or a literal 'willow' app-id."""
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "$HOME/github" not in text
    assert ":-willow}" not in text  # a `${APP_ID:-willow}`-style personal default


def test_sync_hint_uses_the_callers_app_id_not_a_literal():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "project sync $APP_ID" in text
    assert "project sync willow" not in text
