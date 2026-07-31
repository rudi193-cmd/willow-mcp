"""tests for .claude/hooks/session-start.sh's .mcp.json generation.

Found live (2026-07-31): the hook swallowed any scripts/sandbox-bootstrap.sh
failure (`|| true`) but then unconditionally wrote a .mcp.json pointing at
.venv/bin/python3, without checking that file exists -- recreating exactly
the silent-crash-before-handshake footgun the hook's own header says it
exists to prevent. Fixed by guarding that write on the interpreter actually
being executable, matching the -x checks the same script already uses
elsewhere (its pytest-install step, its Kart-worker-start step).

These run the real script as a subprocess against a fake repo, with a
minimal PATH so the best-effort bwrap/Postgres steps see those tools as
absent (safe: they're gated behind `command -v` and skip cleanly) instead
of risking a real system interaction on whatever host runs the suite.
"""
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HOOK = _REPO / ".claude" / "hooks" / "session-start.sh"


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal repo: a no-op sandbox-bootstrap.sh, no .venv yet."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sandbox-bootstrap.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n"
    )
    return tmp_path


@pytest.fixture
def minimal_path(tmp_path_factory):
    """A PATH exposing only what the hook needs to run to completion, so
    bwrap/apt-get/sudo/pg_lsclusters read as absent (command -v fails) no
    matter what's actually installed on the host running the suite -- the
    best-effort steps gated on them are meant to skip cleanly, not be
    exercised for real here."""
    bindir = tmp_path_factory.mktemp("bin")
    for tool in ("bash", "id", "cat", "mv", "grep"):
        real = shutil.which(tool)
        if real:
            (bindir / tool).symlink_to(real)
    return str(bindir)


def _run_hook(fake_repo, minimal_path, venv_python_exists):
    if venv_python_exists:
        py = fake_repo / ".venv" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        py.write_text("#!/usr/bin/env bash\nexit 0\n")
        py.chmod(py.stat().st_mode | stat.S_IEXEC)
    env = {
        "PATH": minimal_path,
        "CLAUDE_CODE_REMOTE": "true",
        "CLAUDE_PROJECT_DIR": str(fake_repo),
        "HOME": str(fake_repo),
    }
    return subprocess.run(
        ["bash", str(_HOOK)], env=env, capture_output=True, text=True, timeout=30
    )


def test_refuses_to_write_mcp_json_when_venv_is_missing(fake_repo, minimal_path):
    """The bug: this used to write .mcp.json anyway, pointing at an
    interpreter that doesn't exist -- moving the failure to the MCP
    handshake instead of surfacing it here."""
    result = _run_hook(fake_repo, minimal_path, venv_python_exists=False)
    assert not (fake_repo / ".mcp.json").exists(), (result.stdout, result.stderr)
    assert "refusing to" in result.stderr


def test_writes_mcp_json_when_venv_is_present(fake_repo, minimal_path):
    """The fix's allow side: a real venv still gets a real .mcp.json --
    the guard must not become a blanket refusal."""
    result = _run_hook(fake_repo, minimal_path, venv_python_exists=True)
    mcp_json = fake_repo / ".mcp.json"
    assert mcp_json.exists(), (result.stdout, result.stderr)
    assert '"command": ".venv/bin/python3"' in mcp_json.read_text()
