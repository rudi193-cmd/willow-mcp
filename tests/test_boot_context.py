import json

from willow_mcp import seed_loader as sl


def test_seed_corpus_corrections_idempotent(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "feedback_no_bash.md").write_text(
        "---\ntitle: x\n---\nDo not use Bash for fleet work.\n"
    )
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setattr(sl, "claude_memory_dir", lambda: memory)
    first = sl.seed_corpus_corrections()
    second = sl.seed_corpus_corrections()
    assert first == 1
    assert second == 0
    lanes = sl.load_corpus_lanes()
    assert any("Bash" in c for c in lanes["corrections"])


def test_session_start_includes_boot_context(tmp_path, monkeypatch):
    from willow_mcp import session_start_hook as ssh
    from willow_mcp import server

    monkeypatch.setenv("WILLOW_APP_ID", "hanuman")
    monkeypatch.setattr(
        server,
        "session_enter",
        lambda **kwargs: {
            "entry_mode": "human",
            "orientation": {},
        },
    )
    monkeypatch.setattr(sl, "seed_corpus_corrections", lambda: 0)
    out = ssh.handle({"session_id": "s1", "source": "startup"})
    payload = json.loads(out["additional_context"])
    assert "boot_context" in payload
    assert "[CLOCK]" in payload["boot_context"]
