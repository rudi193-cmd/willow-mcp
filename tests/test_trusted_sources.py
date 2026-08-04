"""`_TRUSTED_SUFFIXES` must stay answerable to jeles' source registry.

The list carried the comment "Covers all sources registered in
core/jeles_sources.py SOURCES dict". That file is not in this repository, and
nothing checked the claim, so the list drifted in both directions at once: it
was missing `doi.org` — which nine registered sources resolve their citations
through — while carrying `www.w3.org`, picked up from arXiv's Atom *namespace*
identifier and treated as an institution.

`jeles.sources` now declares, per source, the hostnames it contacts, checked
against its own code by `tests/test_source_hosts.py` upstream. This file joins
the two: every host jeles queries must be either trusted here or explicitly
excluded with a reason. A new source in jeles then fails this test until
somebody decides which it is.

**The list is deliberately not generated from the registry.** "jeles queries
this host" and "a link to this host can be believed" are different claims, and
collapsing them is exactly the bug. Generating would mean reducing
`patents.google.com` to a registrable domain and trusting the whole of
google.com — every Blogspot and Google Sites page. The registry says what
changed; a person still says whether it counts.

What this cannot check: 46 of jeles' 61 sources build their citation URL out of
the API response, so where a result *points* is unknowable statically. OpenAlex
or Crossref can legitimately return a link to any publisher on earth. Trust
inferred from a hostname remains a guess for open-web results — this test bounds
the drift, it does not make the inference sound.
"""
from __future__ import annotations

import pytest

from willow_mcp import web_search

jeles_sources = pytest.importorskip(
    "jeles.sources", reason="jeles is the registry this list is checked against")

# Present but too old is a different thing from absent, and must not skip.
# `registered_hosts` and the per-source `hosts` field land in jeles 0.5.0; an
# older jeles would make every check below vacuous while still reporting green,
# so it fails here instead. CI pins the floor (see .github/workflows/tests.yml).
if not hasattr(jeles_sources, "registered_hosts"):  # pragma: no cover
    raise AssertionError(
        "installed jeles predates the source-host registry (jeles >= 0.5.0). "
        "This file cannot check anything against it — upgrade rather than skip."
    )


# Multi-label public suffixes present in jeles' host set. Anything else reduces
# to its last two labels. Not a full PSL — it only has to be right for the hosts
# actually in the registry, and the completeness test below fails if that set
# grows something this does not handle.
_MULTI_LABEL = ("ac.uk", "co.uk", "org.uk", "gov.uk", "go.jp", "ne.jp",
                "ac.jp", "com.br", "org.br", "com.au", "org.au")


def _registrable(host: str) -> str:
    host = host.lower().rstrip(".")
    for suffix in _MULTI_LABEL:
        if host == suffix or host.endswith("." + suffix):
            return ".".join(host.split(".")[-3:])
    return ".".join(host.split(".")[-2:])


def test_every_host_jeles_queries_is_trusted_or_excluded_with_a_reason():
    """The drift check. Absence used to be silent; now it is a failure that
    names the host and makes someone choose."""
    undecided = []
    for host in sorted(jeles_sources.registered_hosts()):
        domain = _registrable(host)
        if web_search._trusted_host(host) or web_search._trusted_host(domain):
            continue
        if domain in web_search._NOT_TRUST_EVIDENCE or host in web_search._NOT_TRUST_EVIDENCE:
            continue
        undecided.append(f"{host} (registrable: {domain})")
    assert not undecided, (
        "jeles queries these hosts and this repo has taken no position on "
        f"them: {undecided}. Add the domain to _TRUSTED_SUFFIXES if a link "
        "there can be believed, or to _NOT_TRUST_EVIDENCE with the reason it "
        "cannot."
    )


def test_the_exclusion_list_has_no_leftovers():
    """An exclusion whose host jeles no longer queries is a stale opinion that
    reads as a live decision. Same failure mode as the phantom entry check
    upstream."""
    queried = {_registrable(h) for h in jeles_sources.registered_hosts()}
    queried |= set(jeles_sources.registered_hosts())
    stale = [d for d in web_search._NOT_TRUST_EVIDENCE if d not in queried]
    assert stale == [], (
        f"_NOT_TRUST_EVIDENCE names hosts jeles no longer queries: {stale}")


def test_every_exclusion_states_why():
    """A bare list of excluded domains is unreviewable — the reason is the
    part a future reader needs."""
    for domain, reason in web_search._NOT_TRUST_EVIDENCE.items():
        assert len(reason.strip()) > 40, f"{domain}: reason too thin to review"


def test_doi_org_is_trusted():
    """The concrete gap this check was written after. Nine registered sources —
    Crossref, DataCite, DOAJ, Europe PMC, INSPIRE-HEP, OpenAIRE, Semantic
    Scholar, USGS, Zenodo — cite through doi.org, and it was not on the list."""
    assert web_search._trusted_host("doi.org")
    assert web_search._trusted_host("dx.doi.org")

    citing = [sid for sid, cfg in jeles_sources.SOURCES.items()
              if "doi.org" in cfg.get("hosts", ())]
    assert len(citing) >= 9, citing


def test_a_namespace_identifier_never_became_a_trusted_institution():
    """`www.w3.org` is arXiv's Atom namespace. It is not a source, and jeles now
    says so — `registered_hosts()` excludes it by name rather than by accident."""
    assert "www.w3.org" not in jeles_sources.registered_hosts()
    assert "purl.org" not in jeles_sources.registered_hosts()
    assert not web_search._trusted_host("w3.org")
    assert not web_search._trusted_host("purl.org")


def test_patents_google_is_trusted_as_a_host_and_google_is_not():
    """The reason the list is curated rather than generated. A registrable-domain
    reduction of `patents.google.com` trusts all of google.com."""
    assert web_search._trusted_host("patents.google.com")
    assert not web_search._trusted_host("google.com")
    assert not web_search._trusted_host("evil.blogspot.google.com.attacker.net")


def test_the_registrable_reduction_covers_every_host_in_the_registry():
    """Guards the helper above: a two-label reduction of a `something.ac.uk`
    host would produce `ac.uk` and silently widen trust to a whole registry."""
    for host in jeles_sources.registered_hosts():
        domain = _registrable(host)
        assert domain.count(".") >= 1, (host, domain)
        assert not domain.startswith("."), (host, domain)
        # A reduction that lands on a bare public suffix means _MULTI_LABEL is
        # missing an entry for this host.
        assert domain not in {"ac.uk", "co.uk", "gov.uk", "org.uk", "go.jp",
                              "com.br", "com.au"}, (host, domain)
