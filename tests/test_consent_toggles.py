"""The two consent keys that persist, reconcile, and display but gate nothing.

`consent.CONSENT_KEYS` declares three keys. `consent.py` supplies exactly one
enforcing helper — `internet_permitted()` — and only that key has callers.
`consent.cloud_llm` and `consent.lan` are accepted by `permitted()`, written by
`consent_admin`, mirrored into `consent.json`, returned by `diagnostic_summary`,
and rendered by `gates_panel`. An operator can flip either one, watch it persist,
watch it reconcile across two files, and receive no protection at all.

`gates_panel.py:159-163` relabelled them "(reserved — not yet enforced)". That
string lives in one dictionary in one renderer; the key is still in the model,
still required by the writer, still mirrored, and still shown as an off switch
by `README.md:154` and `skills/consent.md`. Relabelling is why this is still
open — see `docs/design/consent-toggles.md`.

**PARTIALLY ENFORCED AS OF 2026-07-28.** `cloud_llm` now gates the Nest model
sinks (`model_egress.py`); `lan` still gates nothing. The tests below are in
three states, and the mix is the point:

  * **unmarked and passing** — the enforcement that landed, now real coverage
  * **`xfail(strict=True)`** — still-open gaps. Strict, so each flips to a hard
    failure the moment someone closes it, and the marker comes off then
  * the carve-out guards, which passed before and must keep passing

`lan` is deliberately still a stub rather than half-enforced: gating Kart's
`# allow_localhost` on it denies a mode that works on every install today
(`home_init` writes `lan: false` everywhere), which is a breaking change needing
a release note. See docs/design/consent-toggles.md.

A note on method, because it changed. These tests originally patched
`nest/embed.py`'s and `nest/llm.py`'s module constants, on the assumption the
gate would live where the socket is opened. It cannot: those modules are
vendored byte-for-byte from safe-app-store's `libs/nest-pipeline` under a CI
drift-guard, and are deliberately policy-free. The gate sits at willow-mcp's own
tool boundary instead, so the tests patch `$OLLAMA_HOST` — the thing an operator
actually sets — rather than a module attribute.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from willow_mcp import consent

NOT_YET = "not yet enforced — see docs/design/consent-toggles.md"


class EgressAttempted(Exception):
    """Raised by the socket sentinel. Deliberately not an OSError/URLError, so
    it escapes the broad `except` clauses in the modules under test instead of
    being swallowed into a silent `return None` that would look like a denial."""


def _sentinel_urlopen(*_args, **_kwargs):
    raise EgressAttempted("a socket was opened without a consent check")


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Pin WILLOW_HOME. A consent test that reads the developer's real ~/.willow
    passes or fails on the state of that machine rather than on the code —
    the false-green shape recorded in docs/BUGS.md."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_SETTINGS_GLOBAL", raising=False)
    return tmp_path


def _canonical(home, **con):
    (home / "settings.global.json").write_text(json.dumps({"version": 1, "consent": con}))


def _legacy(home, **con):
    (home / "consent.json").write_text(json.dumps(con))


# ── the general antidote ─────────────────────────────────────────────────────


def test_every_consent_key_has_an_enforcing_helper():
    """Every key in CONSENT_KEYS has a named enforcing helper in consent.py.

    Both live gaps arrived the same way: a key was added to the model and no
    reader was added with it, and nothing in the code noticed. This is the
    invariant that makes the fourth key impossible to add silently. It is the
    single most important assertion in this file — the other stubs describe two
    specific holes; this one closes the hole that produces them.
    """
    missing = [
        key for key in consent.CONSENT_KEYS
        if not callable(getattr(consent, f"{key}_permitted", None))
    ]
    assert missing == [], f"consent keys with no enforcing helper: {missing}"


def test_cloud_llm_permitted_exists_and_is_fail_closed(home):
    """`cloud_llm_permitted()` denies when no policy can be read.

    The helper must inherit `permitted()`'s posture, not invent a laxer one: an
    absent file is not consent, and a key that reads permissive on a missing
    policy is willow-2.0's all-True `DEFAULT_CONSENT`, which this module exists
    to reject.
    """
    assert consent.cloud_llm_permitted() is False
    _canonical(home, internet=True, cloud_llm="true", lan=True)
    assert consent.cloud_llm_permitted() is False, '"true" is not true'
    _canonical(home, internet=False, cloud_llm=True, lan=False)
    assert consent.cloud_llm_permitted() is True


def test_lan_permitted_exists_and_is_fail_closed(home):
    """`lan_permitted()` denies when no policy can be read. Same property as
    `cloud_llm_permitted`, asserted separately so a partial implementation that
    lands one helper and forgets the other cannot pass."""
    assert consent.lan_permitted() is False
    _canonical(home, internet=True, cloud_llm=True, lan="yes")
    assert consent.lan_permitted() is False, '"yes" is not true'
    _canonical(home, internet=False, cloud_llm=False, lan=True)
    assert consent.lan_permitted() is True


# ── cloud_llm: the model-inference sinks ─────────────────────────────────────
#
# willow-mcp calls no cloud LLM provider — there is no Anthropic/OpenAI/Gemini
# client anywhere in the tree. What it does have is three model-inference calls
# whose destination is an environment variable defaulting to loopback, and four
# written claims that "nothing leaves the machine" (server.py:1452,
# nest/llm.py:4, docs/NEST.md:41, docs/BUGS.md:344). Those claims are true of
# the default and false of the variable.


# ── the gate, at the boundary it can actually live on ───────────────────────
#
# These three were written asserting the gate inside `nest/embed.py` and
# `nest/llm.py`, where the socket is opened. That is the right answer to "where
# does egress happen" and the wrong answer to "where does the check go": those
# modules are vendored BYTE-FOR-BYTE from safe-app-store's libs/nest-pipeline
# under a hash pin and a CI vendor-sync job (nest/__init__.py:19-25), and the
# library is deliberately policy-free so each consumer keeps its own layers
# outside the shared core. A consent check there would fork the canonical
# library to carry one consumer's policy, and break the drift-guard.
#
# So they now assert at willow-mcp's own boundary — the tool that decides to
# invoke the pipeline, which is also where the false promise was written. The
# property under test is unchanged: document content does not reach an off-box
# model without consent.


def _app(home, name="nesty", perms=("nest_read", "nest_write")):
    d = home / "mcp_apps" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"permissions": list(perms)}))
    return name


def test_nest_scan_to_an_off_box_model_is_denied_without_cloud_llm_consent(home, monkeypatch):
    """Document text must not reach an off-box model unconsented.

    `nest_scan` defaults to `use_embed=True` and `nest/classify.py` embeds the
    document *body*, not metadata — into what `nest/__init__.py` calls the local
    PII zone. With $OLLAMA_HOST pointed off-box that body went to whoever
    answered, and no consent key was consulted.
    """
    from willow_mcp import model_egress

    _canonical(home, internet=True, cloud_llm=False, lan=False)
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example.net")

    denial = model_egress.denial("nest_scan")
    assert denial is not None, "off-box model host was permitted with cloud_llm false"
    assert "cloud_llm_denied" in denial["error"]
    # The denial must name the key and the file, or it just trains people to
    # route around it.
    assert "consent.cloud_llm" in denial["error"]
    assert "settings.global.json" in denial["error"]


def test_nest_scan_returns_the_denial_instead_of_opening_a_socket(home, monkeypatch, tmp_path):
    """End to end through the real tool: denied, and nothing dialled out."""
    import urllib.request

    from willow_mcp import server

    _canonical(home, internet=True, cloud_llm=False, lan=False)
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example.net")
    monkeypatch.setattr(urllib.request, "urlopen", _sentinel_urlopen)
    app = _app(home)
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "diary.txt").write_text("a private document body")

    fn = getattr(server.nest_scan, "__wrapped__", server.nest_scan)
    out = fn(app_id=app, folder=str(folder), use_embed=True, dry_run=True)

    assert "error" in out and "cloud_llm_denied" in out["error"]


def test_nest_scan_on_loopback_needs_no_consent_key(home, monkeypatch):
    """The carve-out, pinned. `home_init` writes cloud_llm:false into every
    install, so requiring the key for localhost would deny the default
    configuration everywhere and teach operators to switch it on permanently —
    which is how a consent gate becomes a formality."""
    from willow_mcp import model_egress

    _canonical(home, internet=False, cloud_llm=False, lan=False)
    for host in ("http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"):
        monkeypatch.setenv("OLLAMA_HOST", host)
        assert model_egress.denial("nest_scan") is None, host


def test_an_unresolvable_or_malformed_model_host_fails_closed(home, monkeypatch):
    """"I could not tell where this goes" must not read as "it goes nowhere"."""
    from willow_mcp import model_egress

    _canonical(home, internet=True, cloud_llm=False, lan=False)
    # NB: an EMPTY value is not here — it means "unset", falls back to the
    # localhost default, and is correctly allowed.
    for host in ("http://nonexistent.invalid", "not a url", "http://"):
        monkeypatch.setenv("OLLAMA_HOST", host)
        assert model_egress.denial("nest_scan") is not None, host


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_nest_availability_probe_is_gated_too(home, monkeypatch):
    """The `/api/tags` probe opens its own socket outside the inference funnels.

    `nest/llm.py:80` and `nest/embed.py:40` reach the configured host before any
    classification happens. Gating only `_http_json`/`_post` would still tell a
    third-party host that this install exists and which models it expects —
    a smaller leak than the document body, but the same unconsented socket.
    """
    from willow_mcp.nest import llm

    _canonical(home, internet=True, cloud_llm=False, lan=False)
    monkeypatch.setattr(llm, "DEFAULT_HOST", "https://ollama.example.net")
    monkeypatch.setattr(llm, "_installed_models", None)
    monkeypatch.setattr(llm.urllib.request, "urlopen", _sentinel_urlopen)

    assert llm.installed_models() == set()


def test_nest_embedding_to_loopback_needs_no_consent_key(home, monkeypatch):
    """Loopback is the carve-out, and it must survive enforcement.

    NOT a stub — this passes today and is here to fail if the enforcement is
    written too broadly. Bytes to 127.0.0.1 never leave the host, so requiring a
    key for them would break every default install for no security gain, and an
    operator whose local Ollama stopped working would reasonably conclude the
    consent gate is broken rather than protective.
    """
    from willow_mcp.nest import embed

    _canonical(home, internet=False, cloud_llm=False, lan=False)
    calls: list = []

    def _recording_urlopen(req, *args, **kwargs):
        calls.append(req)
        return _FakeResponse(b'{"embedding": [0.25, 0.5]}')

    monkeypatch.setattr(embed, "DEFAULT_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(embed, "_installed", {"nomic-embed-text"})
    monkeypatch.setattr(embed.urllib.request, "urlopen", _recording_urlopen)

    assert embed.embed_document("a private document body") == [0.25, 0.5]
    assert len(calls) == 1


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_kokoro_synthesis_to_a_public_host_is_denied_without_cloud_llm_consent(home, monkeypatch):
    """The assistant's reply text must not reach an off-box TTS model unconsented.

    Kokoro is TTS, not an LLM — the debatable member of the set. It is included
    because the payload is user-facing conversation text, the destination is the
    same shape of environment variable (`voice/kokoro_speak.py:24`), and an
    operator reading "Cloud AI access" will assume it covers the thing that says
    their words out loud. If the implementer scopes `cloud_llm` to inference
    only, the honest alternative is a fourth key, not silence.
    """
    from willow_mcp.voice import kokoro_speak

    _canonical(home, internet=True, cloud_llm=False, lan=False)
    monkeypatch.setenv("WILLOW_KOKORO_URL", "https://tts.example.net/v1/audio/speech")
    monkeypatch.setattr(kokoro_speak.urllib.request, "urlopen", _sentinel_urlopen)
    speaker = kokoro_speak.KokoroSpeaker(player=object(), barge=kokoro_speak.BargeCoordinator())

    with pytest.raises(RuntimeError, match="consent"):
        speaker._http_synthesize("something the operator said out loud")


# ── lan: the local-network destination class ─────────────────────────────────
#
# `# allow_localhost` is named for loopback and implemented as the *absence* of
# --unshare-net (kartikeya/sandbox.py:390-401) — it shares the host network
# namespace, reaching the LAN and the public internet. kartikeya's own docstring
# (sandbox.py:561-565) says so. `network_mode = "localhost"` (sandbox.py:747) is
# a string in a manifest dict, not a restriction.


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_allow_localhost_task_requires_lan_consent(tmp_path, monkeypatch):
    """A host-network-namespace task is denied when consent.lan is off.

    Today `server.py:1917` folds `allow_localhost` into `allow_net` and checks
    only `consent.internet`, so `consent.lan` governs the one Kart mode named
    after it and grants nothing. The operator who set `lan: false` has not
    restricted this task in any way.
    """
    from willow_mcp import server

    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "lanapp"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access", "task_net"]})
    )
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_SETTINGS_GLOBAL", raising=False)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    _canonical(tmp_path, internet=True, cloud_llm=True, lan=False)
    monkeypatch.setattr(server, "get_pg", lambda: SimpleNamespace())

    result = server.task_submit(
        app_id="lanapp", task="echo hi", allow_localhost=True,
    )

    assert "consent.lan" in result.get("error", "")


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_executor_applies_the_same_lan_split_as_submit(tmp_path, monkeypatch):
    """Submit-time and execution-time must agree on which key applies.

    `ExecutorNetworkAuthorizer` (egress_authorization.py:384-393) re-checks the
    host policy immediately before shell launch and today reads only
    `internet_permitted()`. A `lan` key enforced at submit but not at the
    executor is a gate with a documented bypass — the exact class of bug B-29
    closed for `internet`, reintroduced one key over.

    The check belongs beside the existing `consent.internet_permitted()` call at
    egress_authorization.py:390 — ahead of the lease and trust-root checks, so
    the denial names the key the operator actually turned off.
    """
    from willow_mcp import egress_authorization

    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / "lanapp"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["full_access", "task_net"]})
    )
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_SETTINGS_GLOBAL", raising=False)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    _canonical(tmp_path, internet=True, cloud_llm=True, lan=False)

    row = SimpleNamespace(
        submitted_by="lanapp", task_id="LANTASK1", agent="kart",
        task="echo hi\n# allow_localhost",
    )
    authorizer = egress_authorization.ExecutorNetworkAuthorizer()

    assert authorizer(row, "{}") is False
    assert "lan" in authorizer.last_error


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_nest_embedding_to_a_private_host_requires_lan_consent(home, monkeypatch):
    """An RFC1918 model host is LAN egress, not internet egress.

    This is what makes `lan` a real key rather than a synonym for `internet`:
    pointing OLLAMA_HOST at the GPU box in the next room is exactly the
    destination class that `web_fetch.py:35-54` and `mai/parser.py:133-146`
    already go out of their way to block, reached by a path that checks nothing.
    """
    from willow_mcp.nest import embed

    _canonical(home, internet=True, cloud_llm=True, lan=False)
    monkeypatch.setattr(embed, "DEFAULT_HOST", "http://192.168.1.50:11434")
    monkeypatch.setattr(embed, "_installed", {"nomic-embed-text"})
    monkeypatch.setattr(embed.urllib.request, "urlopen", _sentinel_urlopen)

    assert embed.embed_document("a private document body") is None


# ── the mirror as a write path into a security decision ──────────────────────
#
# consent.json is continuously rewritten by willow-2.0's
# save_global_settings(sync_legacy=True) and by Grove's settings pane. Today the
# most it can grant is `internet`, which still needs a capability, a lease, and
# a signed envelope behind it. On the nest path there is no second key.


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_legacy_mirror_cannot_grant_the_newly_enforced_keys(home):
    """The mirror may disagree; it may not grant model or LAN egress.

    `consent.py:157-160` adopts the flat mirror wholesale when the canonical
    file is absent — a fresh install before `willow-mcp-init`, or a
    WILLOW_SETTINGS_GLOBAL pointing at a path that does not exist yet. Once
    `cloud_llm`/`lan` bite, that branch lets a file written by another
    repository turn on a one-key permission with no capability and no lease
    behind it. `internet` keeps its historical fallback; the new keys must be
    canonical-only, which narrows the mirror's authority rather than extending
    it.
    """
    _legacy(home, internet=True, cloud_llm=True, lan=True)

    out = consent.read_consent()
    assert out["source"] == "legacy"
    assert consent.permitted("internet") is True, "internet keeps its historical fallback"
    assert consent.permitted("cloud_llm") is False
    assert consent.permitted("lan") is False


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_an_enforced_key_turned_on_outside_willow_mcp_is_reported(home):
    """A grant with no audit line behind it was written by something else.

    `consent_admin.write_consent` (consent_admin.py:91-142) is willow-mcp's only
    writer and appends `intent`/`committed` lines with before/after hashes to
    config/audit/consent.jsonl around every change. So a canonical
    `cloud_llm: true` whose hash appears nowhere in that log did not come from
    here. That matters because willow-2.0's fail-open writer substitutes an
    all-True DEFAULT_CONSENT for a malformed block and then *saves* it to both
    files — after which the canonical file holds a genuine, well-formed `true`,
    the mirror agrees with it, and `disagreement` stays None. Fail-closed
    reading cannot rescue you from a fail-open writer; only provenance can.

    Surface, never resolve: this must report, not deny. The field name below is
    one possible shape — move it if you like, but do not drop the property.
    """
    _canonical(home, internet=False, cloud_llm=True, lan=True)

    out = consent.read_consent()
    unattested = out.get("unattested") or []
    assert "cloud_llm" in unattested
    assert "lan" in unattested


def test_canonical_still_wins_over_a_permissive_mirror_for_the_new_keys(home):
    """Precedence must not drift while the new keys are being wired.

    NOT a stub — this passes today. It pins the property enforcement is most
    likely to break by accident: canonical governs, the mirror is reported, and
    the operator decides which file states their intent.
    """
    _canonical(home, internet=False, cloud_llm=False, lan=False)
    _legacy(home, internet=True, cloud_llm=True, lan=True)

    out = consent.read_consent()
    assert out["source"] == "canonical"
    assert consent.permitted("cloud_llm") is False
    assert consent.permitted("lan") is False
    assert sorted(out["disagreement"]["keys"]) == ["cloud_llm", "internet", "lan"]


# ── the UI must stop calling a live key reserved ─────────────────────────────


@pytest.mark.xfail(strict=True, reason=NOT_YET)
def test_gates_panel_stops_calling_enforced_keys_reserved():
    """Relabelling was the previous attempt; it has to be undone, not extended.

    `gates_panel.py:162-163` labels both keys "(reserved — not yet enforced)".
    Leaving that string in place after enforcement lands is the same failure
    inverted: a panel telling an operator that a live protection is inert. The
    panel's honesty about the gap is only honest while the gap exists.
    """
    from willow_mcp import gates_panel

    for key in ("cloud_llm", "lan"):
        label = gates_panel.FRIENDLY_LABELS[f"consent.{key}"]
        assert "reserved" not in label.lower(), f"consent.{key} is enforced but still labelled reserved"
        assert "not yet enforced" not in label.lower()
