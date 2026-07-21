"""WO-1 Step 6 — Kokoro SPEAK + barge-in."""
from __future__ import annotations

import json
import struct
import threading
import wave
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from willow_mcp.voice.barge import BargeDetector
from willow_mcp.voice.kokoro_speak import (
    BargeCoordinator,
    InterruptiblePlayer,
    KokoroSpeaker,
)
from willow_mcp.voice.voice_controller import Frame, State, VoiceController


def _wav_bytes(samples: int = 1600, rate: int = 16000) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{samples}h", *([0] * samples)))
    return buf.getvalue()


def test_kokoro_speaker_synthesizes_and_plays_each_chunk():
    played = []

    def synth(text: str) -> bytes:
        assert text == "hello"
        return _wav_bytes()

    speaker = KokoroSpeaker(
        synthesize=synth,
        player=MagicMock(play_wav=lambda audio, interrupt=None: played.append(len(audio)) or True),
    )
    speaker("hello")
    assert speaker.chunks_spoken == 1
    assert played == [len(_wav_bytes())]


def test_kokoro_speaker_skips_empty_chunks():
    speaker = KokoroSpeaker(synthesize=lambda t: _wav_bytes(), player=MagicMock())
    speaker("   ")
    assert speaker.chunks_spoken == 0


def test_interruptible_player_stops_on_event(monkeypatch):
    np = pytest.importorskip("numpy")
    interrupt = threading.Event()
    played = []

    class FakeSd:
        @staticmethod
        def play(chunk, rate, blocking=True):
            played.append(1)
            if len(played) >= 2:
                interrupt.set()

        @staticmethod
        def stop():
            pass

    monkeypatch.setitem(__import__("sys").modules, "numpy", np)
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", FakeSd)
    player = InterruptiblePlayer(block_ms=50)
    finished = player.play_wav(_wav_bytes(samples=32000), interrupt=interrupt)
    assert finished is False
    assert len(played) >= 2


def test_kokoro_speaker_counts_interrupted_chunks():
    coord = BargeCoordinator()
    coord.signal_barge()

    speaker = KokoroSpeaker(
        synthesize=lambda _t: _wav_bytes(),
        player=MagicMock(play_wav=lambda audio, interrupt=None: False),
        barge=coord,
    )
    speaker("one")
    assert speaker.chunks_spoken == 1
    assert speaker.chunks_interrupted == 1


def test_barge_detector_sets_flag_during_speak():
    detector = BargeDetector(wake_fn=lambda f: 0.9)
    frame = detector.enrich(Frame(seq=1, pcm=b"\x00\x00"), speaking=True)
    assert frame.barge is True
    assert detector.coordinator.interrupted()


def test_barge_detector_ignores_idle_capture():
    detector = BargeDetector(wake_fn=lambda f: 0.9)
    frame = detector.enrich(Frame(seq=1), speaking=False)
    assert frame.barge is False


def test_barge_detector_enrich_for_controller():
    detector = BargeDetector(vad_fn=lambda f: True)
    controller = VoiceController(
        transcribe_fn=lambda _b: "ok",
        gate_fn=lambda t, s: "reply.",
    )
    controller.step(Frame(seq=0, wake_score=0.95))
    for i in range(1, 4):
        controller.step(Frame(seq=i, is_speech=True))
    for i in range(4, 7):
        controller.step(Frame(seq=i, is_speech=False))
    assert controller.state is State.SPEAK
    barge_frame = detector.enrich_for_controller(
        Frame(seq=7, pcm=b"\x00\x00"),
        controller,
    )
    assert barge_frame.barge is True


def test_end_to_end_speak_stream_with_kokoro_and_barge():
    tts_calls = []

    class Player:
        def play_wav(self, audio, *, interrupt=None):
            tts_calls.append(len(audio))
            return True

    speaker = KokoroSpeaker(
        synthesize=lambda text: _wav_bytes(),
        player=Player(),
    )
    controller = VoiceController(
        transcribe_fn=lambda _b: "question",
        gate_fn=lambda t, s: "one. two. three.",
        tts_fn=speaker,
    )
    controller.step(Frame(seq=0, wake_score=0.95))
    for i in range(1, 4):
        controller.step(Frame(seq=i, is_speech=True))
    for i in range(4, 7):
        controller.step(Frame(seq=i, is_speech=False))
    assert controller.state is State.SPEAK
    controller.step(Frame(seq=7))  # speaks "one"
    controller.step(Frame(seq=8, barge=True))
    assert controller.state is State.IDLE
    assert tts_calls == [len(_wav_bytes())]
    assert "barge_in" in controller.events()
