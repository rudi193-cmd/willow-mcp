"""silero_vad.py — Silero VAD adapter for CAPTURE endpointing (Step 3).

The controller's ``vad_fn`` contract is ``(Frame) -> bool``. This adapter reads
``frame.pcm`` (mono int16 @ 16 kHz), feeds 512-sample windows through Silero's
streaming ONNX model, and returns whether the latest processed window is speech.
Synthetic test frames without ``pcm`` fall back to ``frame.is_speech`` so the
existing membrane-invariant suite stays valid without models installed.

Design: willow/design/willow-voice-ingress-membrane.md · ΔΣ=42
"""
from __future__ import annotations

from typing import Optional

from willow_mcp.voice.voice_controller import Frame

_CHUNK_SAMPLES = 512  # 32 ms @ 16 kHz


def _pcm_to_float32(pcm: bytes):
    import numpy as np

    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class SileroVadFn:
    """Drop-in ``vad_fn`` backed by Silero VAD (ONNX, ~2 MB)."""

    def __init__(self, *, threshold: float = 0.5, sample_rate: int = 16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._model = None
        self._carry = None

    def _ensure(self) -> None:
        if self._model is not None:
            return
        from silero_vad import load_silero_vad

        self._model = load_silero_vad(onnx=True)

    def reset(self) -> None:
        self._carry = None

    def __call__(self, frame: Frame) -> bool:
        if frame.pcm is None:
            return frame.is_speech
        self._ensure()
        import numpy as np
        import torch

        if self._carry is None:
            self._carry = np.array([], dtype=np.float32)
        self._carry = np.concatenate([self._carry, _pcm_to_float32(frame.pcm)])
        latest = False
        while len(self._carry) >= _CHUNK_SAMPLES:
            chunk = self._carry[:_CHUNK_SAMPLES]
            self._carry = self._carry[_CHUNK_SAMPLES:]
            tensor = torch.from_numpy(chunk).unsqueeze(0)
            prob = float(self._model(tensor, self.sample_rate).item())
            latest = prob >= self.threshold
        return latest


def silero_vad_fn(*, threshold: float = 0.5, sample_rate: int = 16000) -> SileroVadFn:
    """Factory for ``VoiceController(vad_fn=silero_vad_fn())`` wiring."""
    return SileroVadFn(threshold=threshold, sample_rate=sample_rate)
