import json
import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from willow_mcp.commitments.proactive import (
    CommitmentProactiveHook,
    chain_heartbeat,
    proactive_enabled,
    publish_dew_signal,
    signal_path,
    surfacings_to_payload,
)
from willow_mcp.voice.capture import MicCapture, pcm_frames
from willow_mcp.voice.silero_vad import SileroVadFn, _CHUNK_SAMPLES
from willow_mcp.voice.transcribe import FasterWhisperTranscriber, frames_to_audio
from willow_mcp.voice.voice_controller import Frame, VoiceController


def _pcm(samples: int, value: int = 1000) -> bytes:
    return struct.pack(f"<{samples}h", *([value] * samples))


def test_frames_to_audio_concatenates_pcm():
    np = pytest.importorskip("numpy")
    frames = [Frame(seq=0, pcm=_pcm(4, 16384)), Frame(seq=1, pcm=_pcm(4, -16384))]
    audio = frames_to_audio(frames)
    assert audio.shape == (8,)
    assert audio[0] == pytest.approx(0.5)
    assert audio[4] == pytest.approx(-0.5)


def test_pcm_frames_yields_incrementing_seq():
    chunks = [_pcm(1280), _pcm(1280)]
    frames = list(pcm_frames(chunks, start_seq=3))
    assert [f.seq for f in frames] == [3, 4]
    assert all(f.pcm is not None for f in frames)


def test_silero_vad_falls_back_to_is_speech_without_pcm():
    vad = SileroVadFn()
    assert vad(Frame(seq=0, is_speech=True)) is True
    assert vad(Frame(seq=1, is_speech=False)) is False


def test_silero_vad_uses_model_on_pcm(monkeypatch):
    calls = []

    class FakeTensor:
        def __init__(self, data):
            self.shape = (1, len(data))

        def unsqueeze(self, dim):
            return self

    class FakeModel:
        def __call__(self, tensor, sample_rate):
            calls.append((tuple(tensor.shape), sample_rate))
            return SimpleNamespace(item=lambda: 0.9)

    monkeypatch.setattr(
        "willow_mcp.voice.silero_vad.SileroVadFn._ensure",
        lambda self: setattr(self, "_model", FakeModel()),
    )
    monkeypatch.setattr(
        "willow_mcp.voice.silero_vad._pcm_to_float32",
        lambda pcm: list(range(_CHUNK_SAMPLES)),
    )
    fake_np = SimpleNamespace(
        float32="float32",
        array=lambda data, dtype=None: data,
        concatenate=lambda parts: sum((list(p) for p in parts), []),
    )
    monkeypatch.setitem(__import__("sys").modules, "numpy", fake_np)
    monkeypatch.setitem(
        __import__("sys").modules,
        "torch",
        SimpleNamespace(from_numpy=lambda arr: FakeTensor(arr)),
    )

    vad = SileroVadFn(threshold=0.5)
    assert vad(Frame(seq=0, pcm=_pcm(_CHUNK_SAMPLES))) is True
    assert calls


def test_faster_whisper_transcriber_calls_model(monkeypatch):
    segment = SimpleNamespace(text=" turn on the lights ")

    class FakeModel:
        def transcribe(self, audio, language=None):
            assert audio.size > 0
            return ([segment], {})

    monkeypatch.setattr(
        "willow_mcp.voice.transcribe.frames_to_audio",
        lambda frames: SimpleNamespace(size=1600),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *a, **k: FakeModel()),
    )

    transcribe = FasterWhisperTranscriber()
    text = transcribe([Frame(seq=0, pcm=_pcm(1600))])
    assert text == "turn on the lights"


def test_voice_controller_with_injected_vad_and_transcribe():
    vad_calls = []
    transcribe = MagicMock(return_value="hello world")

    def vad(frame):
        vad_calls.append(frame.seq)
        return frame.is_speech

    controller = VoiceController(vad_fn=vad, transcribe_fn=transcribe)
    controller.step(Frame(seq=1, wake_score=0.95))
    controller.step(Frame(seq=2, is_speech=True))
    controller.step(Frame(seq=3, is_speech=True))
    controller.step(Frame(seq=4, is_speech=False))
    controller.step(Frame(seq=5, is_speech=False))
    controller.step(Frame(seq=6, is_speech=False))

    assert transcribe.call_count == 1
    assert vad_calls


def test_publish_dew_signal_writes_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    surfacing = SimpleNamespace(kind="imminent", fact="standup in 10m", uids=("evt-1",))
    assert publish_dew_signal([surfacing]) is True
    payload = json.loads(signal_path().read_text())
    assert payload["surfacings"] == [
        {"kind": "imminent", "fact": "standup in 10m", "uids": ["evt-1"]}
    ]


def test_publish_dew_signal_silent_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    assert publish_dew_signal([]) is False
    assert not signal_path().exists()


def test_proactive_hook_respects_env_gate(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_COMMITMENT_PROACTIVE", raising=False)
    hook = CommitmentProactiveHook(surface_fn=lambda: [object()], interval_s=0.0)
    hook(tick_ok=True)
    assert proactive_enabled() is False


def test_proactive_hook_publishes_on_idle_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_COMMITMENT_PROACTIVE", "1")
    surfacing = SimpleNamespace(kind="conflict", fact="overlap", uids=("a", "b"))
    hook = CommitmentProactiveHook(surface_fn=lambda: [surfacing], interval_s=0.0)
    hook(tick_ok=True)
    assert signal_path().exists()


def test_chain_heartbeat_calls_both():
    calls = []

    def primary(**_):
        calls.append("primary")

    def secondary(**_):
        calls.append("secondary")

    chain_heartbeat(primary, secondary)(tick_ok=True)
    assert calls == ["primary", "secondary"]


def test_mic_capture_import_error_without_sounddevice(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", None)
    with pytest.raises(ImportError, match="sounddevice"):
        MicCapture().frames().__next__()
