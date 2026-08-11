"""Wires tools/tool_oracle_lint.py into CI — the shipped tool-oracle catalog must
never seal a verb that no longer exists. Stdlib-only and Nestor-free, so it runs
on every push regardless of the optional `nestor` extra."""
from tools.tool_oracle_lint import (
    catalog_canonicals,
    check,
    dangling,
    live_verbs,
)


def test_shipped_catalog_has_no_dangling_canonical():
    assert check() == []


def test_live_verbs_and_catalog_are_nonempty():
    # sanity: the parser found verbs and the bundle shipped seals, so a green
    # `check()` means "all resolve", not "nothing to check".
    assert live_verbs()
    assert catalog_canonicals()


def test_every_catalog_canonical_is_a_live_verb():
    assert set(catalog_canonicals()) <= live_verbs()


def test_dangling_detects_a_removed_verb():
    # the drift the lint exists to catch: a seal whose verb was renamed/removed
    assert dangling(["whoami", "verb_that_was_deleted"], {"whoami"}) == [
        "verb_that_was_deleted"
    ]


def test_dangling_is_clean_when_all_resolve():
    assert dangling(["a", "b"], {"a", "b", "c"}) == []
