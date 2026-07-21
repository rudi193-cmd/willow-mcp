"""transcribe.py — faster-whisper adapter for the TRANSCRIBE stage (Step 4).

The controller's ``transcribe_fn`` contract is ``(list[Frame]) -> str``. This
adapter concatenates captured ``frame.pcm`` chunks (mono int16 @ 16 kHz), runs
local faster-whisper, and returns the transcript. Heavy deps are imported only
when the transcriber is constructed or first called.

Design: willow/design/willow-voice-ingress-membrane.md · ΔΣ=42
"""
from __future__ import annotations

from typing import Optional

from willow_mcp.voice.voice_controller import Frame


def frames_to_audio(frames: list[Frame]):
    import numpy as np

    parts = [np.frombuffer(f.pcm, dtype=np.int16) for f in frames if f.pcm]
    if not parts:
        return np.array([], dtype=np.float32)
    pcm = np.concatenate(parts)
    return pcm.astype(np.float32) / 32768.0


class FasterWhisperTranscriber:
    """Drop-in ``transcribe_fn`` backed by faster-whisper."""

    def __init__(
        self,
        *,
        model_size: str = "base",
        language: Optional[str] = "en",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _ensure(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )

    def __call__(self, frames: list[Frame]) -> str:
        audio = frames_to_audio(frames)
        if audio.size == 0:
            return ""
        self._ensure()
        segments, _ = self._model.transcribe(audio, language=self.language)
        return " ".join(segment.text.strip() for segment in segments).strip()


def faster_whisper_transcribe_fn(**kwargs) -> FasterWhisperTranscriber:
    """Factory for ``VoiceController(transcribe_fn=faster_whisper_transcribe_fn())``."""
    return FasterWhisperTranscriber(**kwargs)
