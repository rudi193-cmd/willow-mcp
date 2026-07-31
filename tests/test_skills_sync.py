"""skills/ vs. src/willow_mcp/bundle/skills/ must stay identical.

hooks/pre_tool_use.py has test_bundled_hook_is_identical_to_the_repo_copy for
exactly this reason; skills had no analogue. Found live (2026-07-31):
skills/consent.md and its bundled copy had actually diverged — a commit
(B2, the allow_db perimeter) edited only the bundled copy, and nothing
caught it. The bundled copy is what `plugin.json` and a packaged install
ship; the repo copy is what a contributor reads. A fix or an addition
landing in only one is a skill that passes review and is absent in
production, the same failure class the hook's own test guards against.
"""
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO / "skills"
_BUNDLE_DIR = _REPO / "src" / "willow_mcp" / "bundle" / "skills"


def _skill_files(root: Path) -> dict[str, Path]:
    return {p.name: p for p in root.glob("*.md")}


def test_every_skill_is_identical_to_its_bundled_copy():
    repo_skills = _skill_files(_SKILLS_DIR)
    bundled_skills = _skill_files(_BUNDLE_DIR)

    repo_only = sorted(set(repo_skills) - set(bundled_skills))
    bundle_only = sorted(set(bundled_skills) - set(repo_skills))
    assert not repo_only, f"skills/ has files missing from the bundle: {repo_only}"
    assert not bundle_only, f"bundle/skills/ has files missing from skills/: {bundle_only}"

    mismatched = [
        name for name, path in repo_skills.items()
        if path.read_text(encoding="utf-8") != bundled_skills[name].read_text(encoding="utf-8")
    ]
    assert not mismatched, (
        f"skills/ and bundle/skills/ have drifted for: {mismatched} — "
        "a fix or addition landed in only one copy."
    )
