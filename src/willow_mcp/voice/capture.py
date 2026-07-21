"""capture.py — frame producers for the live audio path (Step 2 wiring).

The controller stays pure; a driver feeds ``Frame`` objects carrying ``pcm``.
This module holds small helpers: iterate injected PCM chunks, or (optionally)
read from the microphone via sounddevice. All heavy audio deps are lazy.

Design: willow/design/willow-voice-ingress-membrane.md · ΔΣ=42
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Optional

from willow_mcp.voice.voice_controller import Frame


def pcm_frames(
    pcm_chunks: Sequence[bytes],
    *,
    start_seq: int = 0,
) -> Iterator[Frame]:
    """Yield ``Frame`` objects from fixed-size PCM chunks (mono int16)."""
    for offset, pcm in enumerate(pcm_chunks):
        yield Frame(seq=start_seq + offset, pcm=pcm)


class MicCapture:
    """Blocking microphone iterator — one ``Frame`` per PortAudio buffer.

    Defaults match openWakeWord (16 kHz, 1280 samples / 80 ms). Importing this
    class does not pull sounddevice; construction does.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_samples: int = 1280,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.device = device
        self._seq = 0

    def frames(self) -> Iterator[Frame]:
        sd, np = _import_audio()
        dtype = "int16"
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=dtype,
            blocksize=self.frame_samples,
            device=self.device,
        ) as stream:
            while True:
                data, _overflowed = stream.read(self.frame_samples)
                pcm = bytes(data)
                frame = Frame(seq=self._seq, pcm=pcm)
                self._seq += 1
                yield frame


def _import_audio():
    try:
        import numpy as np
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise ImportError(
            "voice capture requires sounddevice and numpy "
            "(pip install willow-mcp[voice])"
        ) from exc
    return sd, np
