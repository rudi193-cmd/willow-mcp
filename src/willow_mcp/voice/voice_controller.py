"""
voice_controller.py — Willow voice ingress-membrane controller (Step 1 skeleton).

Pure-script state machine. NO audio libraries, NO models. Every model/DSP stage is an
injected callable, so the security invariants are unit-testable with synthetic frames.

Design:  willow/design/willow-voice-ingress-membrane.md
Axiom:   the state machine IS the security model.
         - Pre-wake audio never reaches the transcriber (wake gate = consent boundary).
         - Receipts record the FACT (armed@T, speaker, disarmed@T), never audio/transcript.
         - The mic adds NO authority: DISPATCH hands text to the SAME gate the typed path uses.

Imperative-shell pattern: the real daemon's asyncio loop only feeds frames into step();
all dwell states, gating, and security logic live in this deterministic core.

Dwell states (where the machine waits for the next frame): IDLE, CAPTURE, SPEAK.
The pipeline stages ARMED / ENDPOINT / IDENTIFY / TRANSCRIBE / DISPATCH run synchronously
within a single step() and are narrated by receipts rather than dwelt in.

Step 1 of the build order — pure script, no models, no network. ΔΣ=42
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Protocol, runtime_checkable


class State(Enum):
    IDLE = auto()
    CAPTURE = auto()
    SPEAK = auto()


@dataclass
class Frame:
    """One audio frame.

    Synthetic path (tests): wake_score / is_speech are what the DETERMINISTIC front-end
    (openWakeWord / Silero VAD) would derive from raw audio; the controller compares them
    without ever inspecting samples — the whole point of the membrane.

    Real path (Step 2+): pcm carries the raw int16 audio a live WakeGate/VAD consumes.
    The controller still never reads pcm itself — only the injected front-end does, and
    only while IDLE. A real capture loop (in-tree voice_mode.py) fills pcm; wake_score /
    is_speech stay 0/False and the gate derives them.
    """
    seq: int
    wake_score: float = 0.0
    is_speech: bool = False
    mute: bool = False   # hard-mute override — forces IDLE from any state
    barge: bool = False  # wake/VAD hit detected during SPEAK → interrupt the reply
    pcm: Optional[bytes] = None  # raw int16 audio for a live gate; None on synthetic frames


# Keys that would turn a receipt into a recording. Enforced at write time.
_FORBIDDEN_RECEIPT_KEYS = frozenset(
    {"audio", "samples", "transcript", "text", "utterance", "waveform", "frames_raw"}
)


@dataclass
class Receipt:
    tick: int
    event: str
    meta: dict = field(default_factory=dict)


class Refused(Exception):
    """Raised by the command gate to refuse a spoken command — the same stop a typed one hits."""


@runtime_checkable
class WakeGate(Protocol):
    """Streaming wake-word scorer — the drop-in contract for a real engine (openWakeWord).

    Lifecycle the controller guarantees, and a real engine may rely on:
      - score(frame) is called ONLY while IDLE, one frame at a time, and returns a wake
        probability in [0, 1]. The controller compares it to VoiceConfig.wake_threshold.
        A live engine reads frame.pcm; it must not require anything a pre-wake frame lacks.
      - reset() is called on EVERY return to IDLE, so a streaming engine clears its ring
        buffer and no partial activation survives a CAPTURE/SPEAK excursion. Stateless
        gates make reset() a no-op.
    """

    def score(self, frame: "Frame") -> float: ...

    def reset(self) -> None: ...


class StubWakeGate:
    """Deterministic synthetic WakeGate: score = frame.wake_score.

    reset() counts invocations so tests can prove the controller resets the gate on every
    return to IDLE — the property a streaming openWakeWord depends on. Drop-in swap: replace
    StubWakeGate() with wake_gate.OpenWakeWordGate(...) and feed frames carrying .pcm; the
    controller does not change.
    """

    def __init__(self) -> None:
        self.reset_count = 0

    def score(self, frame: "Frame") -> float:
        return frame.wake_score

    def reset(self) -> None:
        self.reset_count += 1


@dataclass
class VoiceConfig:
    wake_threshold: float = 0.6       # openWakeWord score to cross IDLE→ARMED
    endpoint_silence_frames: int = 3  # trailing non-speech frames that end an utterance
    false_positive_frames: int = 5    # armed but no speech within N frames → false wake
    max_capture_frames: int = 50      # max-duration cap on a single utterance


class VoiceController:
    """Deterministic ingress-membrane state machine. Drive it with step(frame)."""

    def __init__(
        self,
        *,
        config: Optional[VoiceConfig] = None,
        wake_gate: Optional[WakeGate] = None,
        wake_fn: Optional[Callable[[Frame], float]] = None,
        vad_fn: Optional[Callable[[Frame], bool]] = None,
        transcribe_fn: Optional[Callable[[list[Frame]], str]] = None,
        gate_fn: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
        tts_fn: Optional[Callable[[str], None]] = None,
        speaker_fn: Optional[Callable[[list[Frame]], Optional[str]]] = None,
    ):
        self.cfg = config or VoiceConfig()
        # Wake gate (streaming scorer). Precedence: explicit gate > legacy wake_fn > stub.
        # A bare wake_fn has no reset lifecycle; only a WakeGate is reset on return to IDLE.
        if wake_gate is not None:
            self._wake_gate: Optional[WakeGate] = wake_gate
            self.wake_fn = wake_gate.score
        elif wake_fn is not None:
            self._wake_gate = None
            self.wake_fn = wake_fn
        else:
            _stub = StubWakeGate()
            self._wake_gate = _stub
            self.wake_fn = _stub.score
        self.vad_fn = vad_fn or (lambda f: f.is_speech)
        # THE MODEL. Default stub returns a placeholder and must NEVER run before a wake.
        self.transcribe_fn = transcribe_fn or (lambda buf: f"<{len(buf)} frames>")
        # The EXISTING SAFE gate. Voice adds no authority: (text, speaker) -> response | Refused.
        self.gate_fn = gate_fn or (lambda text, spk: "ok")
        self.tts_fn = tts_fn or (lambda chunk: None)
        # Optional speaker-ID. None disables the IDENTIFY stage.
        self.speaker_fn = speaker_fn

        self.state = State.IDLE
        self.tick = 0
        self.receipts: list[Receipt] = []
        self._buffer: list[Frame] = []   # populated ONLY during CAPTURE; wiped on IDLE
        self._armed_at = 0
        self._saw_speech = False
        self._silence_run = 0
        self._speak_queue: list[str] = []

    # ---- receipts: record the fact, never the content ----
    def _receipt(self, event: str, **meta) -> None:
        leaked = _FORBIDDEN_RECEIPT_KEYS & meta.keys()
        if leaked:
            raise AssertionError(f"receipt {event!r} would leak content via {sorted(leaked)}")
        self.receipts.append(Receipt(self.tick, event, meta))

    def _to_idle(self, event: str, **meta) -> None:
        self._buffer = []          # buffer wiped on EVERY return to IDLE
        self._speak_queue = []
        self._saw_speech = False
        self._silence_run = 0
        self.state = State.IDLE
        if self._wake_gate is not None:
            self._wake_gate.reset()   # streaming wake engine starts each IDLE session clean
        self._receipt(event, **meta)

    # ---- driver entry point ----
    def step(self, frame: Frame) -> None:
        self.tick += 1
        if frame.mute:                       # hard mute wins from any state, and is logged
            self._to_idle("mute")
            return
        if self.state is State.IDLE:
            self._step_idle(frame)
        elif self.state is State.CAPTURE:
            self._step_capture(frame)
        elif self.state is State.SPEAK:
            self._step_speak(frame)

    # ---- IDLE: only the wake gate runs; whisper is never called ----
    def _step_idle(self, frame: Frame) -> None:
        score = self.wake_fn(frame)
        if score >= self.cfg.wake_threshold:
            self._buffer = []
            self._armed_at = self.tick
            self._saw_speech = False
            self._silence_run = 0
            self.state = State.CAPTURE
            self._receipt("armed", score=round(score, 3))
        # else: discard the frame. The near-miss is never transcribed or logged.

    # ---- CAPTURE: VAD gates frames; transcribe is NOT called yet ----
    def _step_capture(self, frame: Frame) -> None:
        self._buffer.append(frame)
        if self.vad_fn(frame):
            self._saw_speech = True
            self._silence_run = 0
        else:
            if self._saw_speech:
                self._silence_run += 1
            elif self.tick - self._armed_at >= self.cfg.false_positive_frames:
                self._to_idle("false_positive")   # armed but no speech ever arrived
                return
        ended = (self._saw_speech and self._silence_run >= self.cfg.endpoint_silence_frames)
        capped = len(self._buffer) >= self.cfg.max_capture_frames
        if ended or capped:
            self._endpoint(capped=capped)

    def _endpoint(self, *, capped: bool) -> None:
        self._receipt("endpoint", frames=len(self._buffer), capped=capped)
        speaker: Optional[str] = None
        # IDENTIFY (optional): an unknown speaker is dropped BEFORE any transcription.
        if self.speaker_fn is not None:
            speaker = self.speaker_fn(list(self._buffer))
            if speaker is None:
                self._to_idle("unknown_speaker")
                return
            self._receipt("identify", speaker=speaker)
        # TRANSCRIBE — first and only model touch of the captured audio.
        text = self.transcribe_fn(list(self._buffer))
        self._receipt("transcribe", chars=len(text), speaker=speaker)
        # DISPATCH — the existing SAFE gate. A spoken command hits the same stop as a typed one.
        try:
            response = self.gate_fn(text, speaker)
        except Refused as exc:
            self._to_idle("dispatch_refused", speaker=speaker, reason=str(exc)[:80])
            return
        self._receipt("dispatch", speaker=speaker, refused=False)
        # SPEAK — enqueue the reply in chunks; each later frame speaks one (barge-interruptible).
        self._speak_queue = self._chunk(response)
        self.state = State.SPEAK
        if not self._speak_queue:
            self._to_idle("disarm")

    @staticmethod
    def _chunk(response: Optional[str]) -> list[str]:
        if not response:
            return []
        flat = response.replace("!", ".").replace("?", ".")
        return [p.strip() for p in flat.split(".") if p.strip()]

    # ---- SPEAK: stream chunks; a barge-in interrupts immediately ----
    def _step_speak(self, frame: Frame) -> None:
        if frame.barge:
            self._to_idle("barge_in", unspoken=len(self._speak_queue))
            return
        if self._speak_queue:
            chunk = self._speak_queue.pop(0)
            self.tts_fn(chunk)
            self._receipt("speak", chunk_chars=len(chunk))
        if not self._speak_queue:
            self._to_idle("disarm")

    # ---- read helpers for tests / driver ----
    def events(self) -> list[str]:
        return [r.event for r in self.receipts]
