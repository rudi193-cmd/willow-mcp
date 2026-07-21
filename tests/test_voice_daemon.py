"""WO-1 daemon assembly — live voice ingress loop."""
from __future__ import annotations

import pytest

from willow_mcp.voice.daemon import (
    VoiceDaemon,
    VoiceDaemonConfig,
    _echo_handler,
    load_handler,
    resolve_wake_models,
)
from willow_mcp.voice.voice_controller import Frame, State


def _stub_wake_gate(*_args, **_kwargs):
    from willow_mcp.voice.voice_controller import StubWakeGate

    return StubWakeGate()


def _stub_vad(**_kwargs):
    return lambda frame: frame.is_speech


def _stub_transcriber(**_kwargs):
    return lambda _buf: "hello daemon"


@pytest.fixture
def patched_build(monkeypatch):
    monkeypatch.setattr("willow_mcp.voice.daemon.OpenWakeWordGate", _stub_wake_gate)
    monkeypatch.setattr("willow_mcp.voice.daemon.SileroVadFn", _stub_vad)
    monkeypatch.setattr(
        "willow_mcp.voice.daemon.FasterWhisperTranscriber", _stub_transcriber
    )


def test_resolve_wake_models_prefers_config():
    assert resolve_wake_models(["/models/a.onnx"]) == ("/models/a.onnx",)


def test_resolve_wake_models_reads_env(monkeypatch):
    monkeypatch.setenv("WILLOW_VOICE_WAKE_MODELS", "/a.onnx:/b.onnx")
    assert resolve_wake_models([]) == ("/a.onnx", "/b.onnx")


def test_build_requires_wake_models(patched_build):
    daemon = VoiceDaemon(VoiceDaemonConfig(command_handler=_echo_handler))
    with pytest.raises(RuntimeError, match="wake models required"):
        daemon.build()


def test_echo_handler_does_not_echo_utterance():
    reply = _echo_handler("secret phrase", "operator")
    assert "secret" not in reply
    assert "operator" in reply


def test_load_handler_imports_callable():
    handler = load_handler("willow_mcp.voice.daemon:_echo_handler")
    assert handler("x", None) == _echo_handler("x", None)


def test_daemon_run_with_injected_frames(patched_build):
    calls = []

    def handler(text, speaker):
        calls.append((text, speaker))
        return "done"

    frames = iter(
        [
            Frame(seq=0, wake_score=0.95),
            Frame(seq=1, is_speech=True),
            Frame(seq=2, is_speech=True),
            Frame(seq=3, is_speech=True),
            Frame(seq=4, is_speech=False),
            Frame(seq=5, is_speech=False),
            Frame(seq=6, is_speech=False),
        ]
    )
    daemon = VoiceDaemon(
        VoiceDaemonConfig(
            wake_models=["fake.onnx"],
            enable_frank=False,
            enable_kokoro=False,
            command_handler=handler,
        )
    )
    daemon.run(frames=frames)
    assert calls == [("hello daemon", None)]


def test_daemon_build_stack_state_after_one_utterance(patched_build):
    daemon = VoiceDaemon(
        VoiceDaemonConfig(
            wake_models=["fake.onnx"],
            enable_frank=False,
            enable_kokoro=False,
            command_handler=_echo_handler,
        )
    )
    stack = daemon.build()
    stack.driver.step(Frame(seq=0, wake_score=0.95))
    for i in range(1, 4):
        stack.driver.step(Frame(seq=i, is_speech=True))
    for i in range(4, 7):
        stack.driver.step(Frame(seq=i, is_speech=False))
    assert stack.controller.state is State.SPEAK
