"""Regression tests for Kart Postgres lane gating (dispatch 75246C61)."""

from kartikeya import sandbox


def test_parse_task_network_reports_allow_db():
    body, net, local, db = sandbox.parse_task_network("pytest tests/\n# allow_db")
    assert db is True
    assert net is False
    assert local is False
    assert "# allow_db" not in body


def test_allow_db_task_gets_socket_bind_when_present(monkeypatch):
    real_exists = sandbox.Path.exists

    def exists(self):
        if str(self) == "/var/run/postgresql":
            return True
        return real_exists(self)

    monkeypatch.setattr(sandbox.Path, "exists", exists)
    monkeypatch.setattr(sandbox.os.path, "isdir", lambda _p: True)
    argv = sandbox.build_bwrap_argv(allow_db=True)
    assert any("postgresql" in part for part in argv)
