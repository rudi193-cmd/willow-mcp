"""The envelope registry's default home moved from a sibling `willow` charter
repo (~/github/willow/envelopes/) to $WILLOW_HOME/constitutional/ — see
paths.envelope_registry_path / paths.syscall_table_path and envelopes.py's
registry_path/syscall_path. WILLOW_ENVELOPE_REGISTRY / WILLOW_SYSCALL_TABLE
still override unconditionally; these tests cover only the new default and
the seeding behaviour, since every other envelope test already exercises the
override path with its own temp registry.
"""
import json

from willow_mcp import envelopes, home_init as hi, paths


def test_registry_path_defaults_under_home_when_unset(home, monkeypatch):
    monkeypatch.delenv("WILLOW_ENVELOPE_REGISTRY", raising=False)
    assert envelopes.registry_path() == home / "constitutional" / "pre-approved.json"


def test_syscall_path_defaults_under_home_when_unset(home, monkeypatch):
    monkeypatch.delenv("WILLOW_ENVELOPE_REGISTRY", raising=False)
    monkeypatch.delenv("WILLOW_SYSCALL_TABLE", raising=False)
    assert envelopes.syscall_path() == home / "constitutional" / "syscall-table.json"


def test_syscall_path_still_follows_a_custom_registry_directory(home, monkeypatch, tmp_path):
    # Unchanged behaviour: an operator pointing WILLOW_ENVELOPE_REGISTRY
    # elsewhere still gets the syscall table alongside it, not under $WILLOW_HOME.
    custom_dir = tmp_path / "elsewhere"
    custom_dir.mkdir()
    monkeypatch.setenv("WILLOW_ENVELOPE_REGISTRY", str(custom_dir / "pre-approved.json"))
    monkeypatch.delenv("WILLOW_SYSCALL_TABLE", raising=False)
    assert envelopes.syscall_path() == custom_dir / "syscall-table.json"


def test_home_init_seeds_an_empty_registry_and_a_real_syscall_table(home, monkeypatch):
    monkeypatch.delenv("WILLOW_ENVELOPE_REGISTRY", raising=False)
    monkeypatch.delenv("WILLOW_SYSCALL_TABLE", raising=False)
    result = hi.ensure_home_layout()

    registry_path = paths.envelope_registry_path()
    table_path = paths.syscall_table_path()
    assert registry_path.is_file()
    assert table_path.is_file()
    assert str(registry_path.relative_to(home)) in result["seeds_copied"]["constitutional"]
    assert str(table_path.relative_to(home)) in result["seeds_copied"]["constitutional"]

    registry = json.loads(registry_path.read_text())
    # The seeded starter must never carry real grants — those are the
    # operator's to issue, not willow-mcp's to ship.
    assert registry["active"] == []
    assert registry["pre_approved"] == []
    assert registry["proposals"] == []
    assert "envelope_schema" in registry  # the shape is real even though the content isn't

    table = json.loads(table_path.read_text())
    # The syscall table's content IS real — it's mechanism, not a secret.
    assert table["verbs"], "the bundled syscall table must ship its actual verb set"


def test_home_init_never_overwrites_an_existing_registry(home, monkeypatch):
    monkeypatch.delenv("WILLOW_ENVELOPE_REGISTRY", raising=False)
    monkeypatch.delenv("WILLOW_SYSCALL_TABLE", raising=False)

    registry_path = paths.envelope_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    real_grant = {"active": [{"id": "env-operator-issued", "status": "active"}], "pre_approved": [], "proposals": []}
    registry_path.write_text(json.dumps(real_grant))

    hi.ensure_home_layout()

    assert json.loads(registry_path.read_text()) == real_grant, (
        "an operator's real registry must survive init untouched — this is governance state, not a cache"
    )


def test_seeded_registry_passes_the_fail_closed_ownership_check(home, monkeypatch):
    """A file `shutil.copy2`'d by init must still clear trusted_read()'s
    ownership/permission gate — otherwise every fresh install would boot with
    an unusable (fail-closed-refused) registry."""
    monkeypatch.delenv("WILLOW_ENVELOPE_REGISTRY", raising=False)
    monkeypatch.delenv("WILLOW_SYSCALL_TABLE", raising=False)
    hi.ensure_home_layout()

    paths.trusted_read(envelopes.registry_path())  # raises PermissionError on failure
    paths.trusted_read(envelopes.syscall_path())
