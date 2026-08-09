"""#297: a Dependabot PR auto-merged with GITHUB_TOKEN reaches master with no
CI run and no release-please run on the result.

GitHub does not trigger `on: push` / `on: pull_request` workflows for events
it generated with GITHUB_TOKEN — its recursion guard, and it is documented and
intentional. `gh pr merge --auto` *arms* a merge; GitHub performs the merge
itself later, once required checks pass, and attributes that merge to
whoever armed it (release-please.yml already documents and tests this same
fact for the release PR). #293 was armed with GITHUB_TOKEN, so its eventual
merge push carried github-actions[bot]'s identity, started zero workflow
runs, and silently dropped two CHANGELOG entries because release-please's
changelog-rebuild step never ran.

The fix reuses the PAT release-please.yml already requires
(`RELEASE_PLEASE_TOKEN`) to arm auto-merge here too, so the eventual merge is
an ordinary push and `Tests` / `Release Please` (both `on: push`) run on it
like any other merge to master. These tests pin that everywhere auto-merge is
armed uses the PAT, not GITHUB_TOKEN — and nowhere else, since read-only
metadata fetches never needed it and giving it that scope would be needless.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML needed to read the workflow")

_REPO = Path(__file__).resolve().parents[1]
_WF = _REPO / ".github" / "workflows" / "dependabot-automerge.yml"


def _load() -> dict:
    return yaml.safe_load(_WF.read_text())


def _steps(job: str) -> list[dict]:
    return _load()["jobs"][job]["steps"]


def _secrets_used(value) -> set[str]:
    return set(re.findall(r"secrets\.([A-Z_]+)", str(value)))


def test_automerge_arming_uses_the_pat_not_github_token():
    """The step that actually calls `gh pr merge --auto` on a fresh Dependabot
    PR must run with the PAT — GITHUB_TOKEN here silently reproduces #297."""
    steps = _steps("dependabot-pr")
    arm = next(s for s in steps if s.get("name") == "Enable auto-merge")
    assert "gh pr merge --auto" in arm["run"]

    used = _secrets_used(arm.get("env"))
    assert "RELEASE_PLEASE_TOKEN" in used, used
    assert "GITHUB_TOKEN" not in used, (
        "arming auto-merge with GITHUB_TOKEN attributes the eventual merge "
        f"to github-actions[bot], which starts no workflow run. Found: {used}"
    )


def test_refresh_stale_prs_also_uses_the_pat():
    """`refresh-stale-dependabot-prs` re-arms auto-merge after the base moves —
    same `gh pr merge --auto` call, same attribution trap, same fix."""
    steps = _steps("refresh-stale-dependabot-prs")
    rearm = next(
        s for s in steps
        if "Re-arm auto-merge" in (s.get("name") or "")
    )
    assert "gh pr merge --auto" in rearm["run"]

    used = _secrets_used(rearm.get("env"))
    assert "RELEASE_PLEASE_TOKEN" in used, used
    assert "GITHUB_TOKEN" not in used, used


def test_metadata_fetch_stays_on_github_token():
    """The Dependabot metadata fetch only reads the PR — it merges nothing, so
    handing it the PAT would be scope it never needs. It must stay narrow
    even though the merge steps around it were widened to the PAT."""
    steps = _steps("dependabot-pr")
    fetch = next(s for s in steps if s.get("name") == "Fetch Dependabot metadata")
    used = _secrets_used(fetch.get("with"))
    assert used == {"GITHUB_TOKEN"}, used


def test_both_jobs_refuse_to_arm_without_the_pat():
    """A missing RELEASE_PLEASE_TOKEN must fail loudly, not silently degrade to
    a GITHUB_TOKEN arm that looks fine until the merge lands untested — the
    same posture release-please.yml already takes on its own PAT requirement."""
    for job, arm_name in (
        ("dependabot-pr", "Enable auto-merge"),
        ("refresh-stale-dependabot-prs", "Re-arm auto-merge on open Dependabot PRs after the base moves"),
    ):
        steps = _steps(job)
        names = [s.get("name") for s in steps]

        guard_idx = next(
            i for i, n in enumerate(names) if n == "Require the release PAT"
        )
        arm_idx = names.index(arm_name)
        assert guard_idx < arm_idx, (job, names)

        guard = steps[guard_idx]
        assert "RELEASE_PLEASE_TOKEN" in _secrets_used(guard.get("env")), (job, guard)
        assert "exit 1" in guard["run"], (job, "guard must fail, not just warn")


def test_no_gh_pr_merge_call_anywhere_uses_github_token():
    """Belt-and-suspenders over the two targeted tests above: scan every step
    in the workflow and refuse GITHUB_TOKEN next to any `gh pr merge --auto`
    call, so a future step added the same way this bug shipped is caught."""
    data = _load()
    for job_name, job in data["jobs"].items():
        for step in job["steps"]:
            run = str(step.get("run", ""))
            if "gh pr merge --auto" not in run:
                continue
            used = _secrets_used(step.get("env"))
            assert "GITHUB_TOKEN" not in used, (
                f"{job_name}/{step.get('name')} arms auto-merge with "
                f"GITHUB_TOKEN — the merge it eventually performs would start "
                f"no workflow run. Found: {used}"
            )
            assert "RELEASE_PLEASE_TOKEN" in used, (job_name, step.get("name"), used)


def test_permissions_are_read_only_now_that_arming_uses_the_pat():
    """GITHUB_TOKEN performs no write in this workflow anymore — only the
    read-only metadata fetch uses it. The `permissions:` block should say so,
    not carry write scope nothing exercises."""
    perms = _load()["permissions"]
    assert perms == {"contents": "read", "pull-requests": "read"}, perms
