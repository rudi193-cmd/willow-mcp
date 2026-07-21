"""kokoro_speak.py — Kokoro TTS adapter for SPEAK (WO-1 Step 6).

The controller streams reply text sentence-by-sentence through ``tts_fn``; this
adapter synthesizes each chunk via the fleet Kokoro HTTP surface (same contract
as ``willow-2.0/core/jukebox.py``) and plays WAV audio through an interruptible
player so a barge-in can stop mid-utterance.

Heavy deps (sounddevice, numpy) are lazy — constructing the adapter does not
import them.

Design: willow/design/willow-voice-ingress-membrane.md (Step 6) · ΔΣ=42
"""
from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
import urllib.request
import wave
from typing import Callable, Optional

DEFAULT_KOKORO_URL = "http://localhost:5000/v1/audio/speech"
DEFAULT_KOKORO_VOICE = "am_michael"


class BargeCoordinator:
    """Shared stop signal between capture (wake/VAD) and playback."""

    def __init__(self) -> None:
        self._interrupt = threading.Event()

    def signal_barge(self) -> None:
        self._interrupt.set()

    def clear(self) -> None:
        self._interrupt.clear()

    def interrupted(self) -> bool:
        return self._interrupt.is_set()

    @property
    def event(self) -> threading.Event:
        return self._interrupt


class InterruptiblePlayer:
    """Play WAV bytes in small blocks; honour a stop event for barge-in."""

    def __init__(self, *, block_ms: int = 50):
        self.block_ms = block_ms

    def play_wav(self, wav_bytes: bytes, *, interrupt: threading.Event | None = None) -> bool:
        """Return True when the clip finished; False when interrupted."""
        import numpy as np
        import sounddevice as sd

        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())
        if not frames:
            return True
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels)
        block = max(1, int(rate * self.block_ms / 1000))
        pos = 0
        length = len(samples)
        while pos < length:
            if interrupt is not None and interrupt.is_set():
                sd.stop()
                return False
            chunk = samples[pos : pos + block]
            sd.play(chunk, rate, blocking=True)
            pos += block
        return True


class KokoroSpeaker:
    """Drop-in ``tts_fn`` backed by Kokoro over HTTP."""

    def __init__(
        self,
        *,
        url: str | None = None,
        voice: str | None = None,
        timeout_s: float = 30.0,
        player: InterruptiblePlayer | None = None,
        barge: BargeCoordinator | None = None,
        synthesize: Callable[[str], bytes] | None = None,
    ):
        self.url = (url or os.environ.get("WILLOW_KOKORO_URL") or DEFAULT_KOKORO_URL).strip()
        self.voice = (voice or os.environ.get("WILLOW_KOKORO_VOICE") or DEFAULT_KOKORO_VOICE).strip()
        self.timeout_s = timeout_s
        self._player = player or InterruptiblePlayer()
        self._barge = barge or BargeCoordinator()
        self._synthesize = synthesize or self._http_synthesize
        self.chunks_spoken = 0
        self.chunks_interrupted = 0

    def _http_synthesize(self, text: str) -> bytes:
        body = json.dumps(
            {
                "input": text,
                "voice": self.voice,
                "response_format": "wav",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"kokoro synthesis failed: {exc}") from exc

    def __call__(self, chunk: str) -> None:
        clean = (chunk or "").strip()
        if not clean:
            return
        self._barge.clear()
        audio = self._synthesize(clean)
        finished = self._player.play_wav(audio, interrupt=self._barge.event)
        self.chunks_spoken += 1
        if not finished:
            self.chunks_interrupted += 1


def kokoro_tts_fn(**kwargs) -> KokoroSpeaker:
    """Factory for ``VoiceController(tts_fn=kokoro_tts_fn())`` wiring."""
    return KokoroSpeaker(**kwargs)
