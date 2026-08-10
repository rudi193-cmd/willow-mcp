"""The ported repo hygiene sweep.

Everything here runs against REAL git repositories in tmp_path rather than mocked
`subprocess` calls. The module is a thin wrapper over git's own output, so a test
that mocks git tests the mock: the org-layout bug this port exists to fix lives
entirely in a glob pattern, and no amount of stubbing `_git` would have caught it.
"""
import subprocess

import pytest

from willow_mcp import repo_sweep


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _make_repo(path, *, commit=True, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True,
                   capture_output=True)
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    if commit:
        (path / "README.md").write_text("hello\n")
        _git(path, "add", "README.md")
        _git(path, "commit", "-qm", "init")
    return path


# ── discovery: the bug the port exists to fix ───────────────────────────────

def test_finds_repos_in_the_org_layout(tmp_path):
    """`<root>/<org>/<repo>` — the 2026-08-10 layout. The original globbed only
    `*/.git` and reported 2 of 32 repos on this tree, calling the other 30
    neither clean nor flagged but simply absent."""
    _make_repo(tmp_path / "org-a" / "repo-1")
    _make_repo(tmp_path / "org-b" / "repo-2")
    found = repo_sweep.find_repos(tmp_path)
    assert {p.name for p in found} == {"repo-1", "repo-2"}


def test_still_finds_flat_repos(tmp_path):
    """The flat layout has not gone away — safe-app-store-public sits directly
    under ~/github while everything else is one level down."""
    _make_repo(tmp_path / "flat-repo")
    assert [p.name for p in repo_sweep.find_repos(tmp_path)] == ["flat-repo"]


def test_finds_both_layouts_at_once_without_duplicates(tmp_path):
    _make_repo(tmp_path / "flat")
    _make_repo(tmp_path / "org" / "nested")
    found = repo_sweep.find_repos(tmp_path)
    assert len(found) == len(set(found)) == 2


def test_max_depth_1_reproduces_the_original_blindness(tmp_path):
    """Pinned deliberately: depth 1 is what shipped, and it is why the sweep
    went quiet after the move."""
    _make_repo(tmp_path / "org" / "nested")
    assert repo_sweep.find_repos(tmp_path, max_depth=1) == []
    assert len(repo_sweep.find_repos(tmp_path, max_depth=2)) == 1


def test_repo_names_are_org_qualified(tmp_path):
    """A bare `willow` is ambiguous across orgs; the report says which one."""
    repo = _make_repo(tmp_path / "willow-memory" / "willow")
    assert repo_sweep.survey_repo(repo, root=tmp_path)["repo"] == "willow-memory/willow"


# ── findings ────────────────────────────────────────────────────────────────

def test_a_clean_repo_has_no_findings(tmp_path):
    repo = _make_repo(tmp_path / "clean")
    assert repo_sweep.survey_repo(repo, root=tmp_path)["findings"] == []


def test_untracked_source_is_flagged_but_scratch_is_not(tmp_path):
    repo = _make_repo(tmp_path / "r")
    (repo / "deliverable.py").write_text("x = 1\n")
    (repo / "junk.pyc").write_bytes(b"\x00")
    findings = repo_sweep.survey_repo(repo, root=tmp_path)["findings"]
    assert any("1 untracked source files" in f and "deliverable.py" in f for f in findings)
    assert not any("junk.pyc" in f for f in findings)


def test_tracked_but_dirty_is_flagged_at_the_threshold(tmp_path):
    """The finding this whole session kept re-deriving by hand: runtime state
    committed into a repo. Threshold is 5, so 4 stays quiet."""
    repo = _make_repo(tmp_path / "r")
    for i in range(6):
        f = repo / f"f{i}.txt"
        f.write_text("v1\n")
        _git(repo, "add", f.name)
    _git(repo, "commit", "-qm", "add")
    for i in range(6):
        (repo / f"f{i}.txt").write_text("v2\n")
    findings = repo_sweep.survey_repo(repo, root=tmp_path)["findings"]
    assert any("6 tracked files dirty (runtime state in git?)" in f for f in findings)


def test_branch_litter_respects_the_limit(tmp_path):
    repo = _make_repo(tmp_path / "r")
    for i in range(4):
        _git(repo, "branch", f"b{i}")
    assert not any("branch litter" in f
                   for f in repo_sweep.survey_repo(repo, branch_limit=15, root=tmp_path)["findings"])
    assert any("branch litter: 5 local branches" in f
               for f in repo_sweep.survey_repo(repo, branch_limit=3, root=tmp_path)["findings"])


def test_an_unborn_repo_reports_that_not_a_tracking_complaint(tmp_path):
    """A freshly-cloned empty repo has no resolvable HEAD, so `rev-parse
    --abbrev-ref` fails and the branch reads as ''. Before this was handled the
    sweep said `on branch '' with no upstream tracking`, which sounds like a
    problem with the branch rather than an empty repo."""
    repo = _make_repo(tmp_path / "empty", commit=False, branch="main")
    s = repo_sweep.survey_repo(repo, root=tmp_path)
    assert s["branch"] == "main"
    assert any("no commits yet" in f for f in s["findings"])
    assert not any("upstream tracking" in f for f in s["findings"])


def test_the_sweep_never_writes_to_the_repos_it_surveys(tmp_path):
    """Read-only by design — it must not fetch, stage, commit, or stash."""
    repo = _make_repo(tmp_path / "r")
    (repo / "untracked.py").write_text("x=1\n")
    before = _status(repo), _head(repo), _reflog(repo)
    repo_sweep.sweep(tmp_path)
    assert (_status(repo), _head(repo), _reflog(repo)) == before


def _status(repo):
    return subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                          capture_output=True, text=True).stdout


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout


def _reflog(repo):
    return subprocess.run(["git", "-C", str(repo), "reflog"],
                          capture_output=True, text=True).stdout


# ── flags ───────────────────────────────────────────────────────────────────

def test_flag_collection_is_valid_and_inside_willows_store_scope():
    """The original wrote to `willow/flags`. willow-mcp collection names are
    regex-validated and reject a slash, so the namespace had to become a flat
    name — and this one matches the willow manifest's existing `willow_*` scope,
    so raising flags needs no manifest change."""
    from willow_mcp.db import _validate_collection, collection_in_scope

    _validate_collection(repo_sweep.DEFAULT_FLAG_COLLECTION)
    assert collection_in_scope(repo_sweep.DEFAULT_FLAG_COLLECTION, ["willow_*"])
    with pytest.raises(ValueError):
        _validate_collection("willow/flags")     # what the predecessor used


def test_emit_flags_writes_one_stable_record_per_flagged_repo(tmp_path, monkeypatch):
    """Stable ids: a weekly sweep updates a repo's flag, it does not accumulate
    a new one every Monday."""
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    repo = _make_repo(tmp_path / "org" / "dirty")
    (repo / "thing.py").write_text("x=1\n")
    _make_repo(tmp_path / "org" / "clean")

    surveys = repo_sweep.sweep(tmp_path)
    written = repo_sweep.emit_flags(surveys, "willow_flags")
    assert written == 1                       # only the repo with findings
    assert repo_sweep.emit_flags(surveys, "willow_flags") == 1

    from willow_mcp.db import Store
    rows = Store(str(tmp_path / "store")).all("willow_flags")
    assert len(rows) == 1, "re-running must update the flag, not add a second"


def test_report_and_json_agree_on_what_was_flagged(tmp_path):
    _make_repo(tmp_path / "org" / "clean")
    repo = _make_repo(tmp_path / "org" / "flagged")
    (repo / "x.py").write_text("x=1\n")
    surveys = repo_sweep.sweep(tmp_path)

    text = repo_sweep.format_report(tmp_path, surveys)
    assert "2 repos" in text and "1 with findings" in text and "1 clean" in text

    import json as _json
    data = _json.loads(repo_sweep.format_report(tmp_path, surveys, as_json=True))
    assert data["repos"] == 2 and len(data["flagged"]) == 1
    assert data["flagged"][0]["repo"] == "org/flagged"
