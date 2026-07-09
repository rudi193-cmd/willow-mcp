"""Regression test: `willow-mcp gates | head`, `... | grep -q`, etc. must exit
clean, not crash with an unhandled BrokenPipeError traceback.

Several subcommands (`gates`, `net-status`, `tree`) print multiple lines and
are exactly the shape someone pipes into `head`/`grep -q` — a downstream
reader closing early raises BrokenPipeError on the next write, and Python
does not handle that for you. `main()` wraps `_main()` specifically to catch
it (see server.py); this pins that wrapper's behavior without needing to
actually race a real pipe closure (which `head -c1`-style tests only trigger
non-deterministically, depending on output size and OS scheduling).
"""
import os

import pytest

from willow_mcp import server


def test_main_catches_broken_pipe_and_exits_1(monkeypatch):
    def _raise_broken_pipe():
        raise BrokenPipeError()

    # Don't let the handler's real os.dup2(devnull, stdout_fd) touch this
    # test process's actual fd 1 — pytest's own output capturing depends on
    # it, and clobbering it here would silently break capture for whatever
    # runs after this test in the same session.
    dup2_calls = []
    monkeypatch.setattr(server, "_main", _raise_broken_pipe)
    monkeypatch.setattr(os, "dup2", lambda src, dst: dup2_calls.append((src, dst)))

    with pytest.raises(SystemExit) as exc_info:
        server.main()
    assert exc_info.value.code == 1
    assert len(dup2_calls) == 1  # the devnull redirect was attempted


def test_main_does_not_swallow_other_exceptions(monkeypatch):
    def _raise_other():
        raise ValueError("not a broken pipe")

    monkeypatch.setattr(server, "_main", _raise_other)
    with pytest.raises(ValueError):
        server.main()
