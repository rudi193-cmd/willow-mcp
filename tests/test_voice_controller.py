"""
test_voice_controller.py — membrane-invariant tests for the Step 1 controller skeleton.

Each test asserts one security property of the ingress membrane, driven by synthetic
frames. No audio, no models. Run: python3 -m unittest test_voice_controller -v
(or pytest tests/test_voice_controller.py)
"""
from __future__ import annotations

import unittest

from willow_mcp.voice.voice_controller import (
    Frame,
    Refused,
    State,
    StubWakeGate,
    VoiceConfig,
    VoiceController,
)


class Spy:
    """Records calls so a test can assert whether/when a stage ran."""

    def __init__(self, ret=None):
        self.calls: list = []
        self.ret = ret

    def __call__(self, *args):
        self.calls.append(args)
        return self.ret


def wake(seq: int) -> Frame:
    return Frame(seq=seq, wake_score=0.95)


def speech(seq: int) -> Frame:
    return Frame(seq=seq, is_speech=True)


def silence(seq: int) -> Frame:
    return Frame(seq=seq, is_speech=False)


class PreWakePrivacy(unittest.TestCase):
    def test_prewake_audio_never_transcribed(self):
        """The core invariant: no wake word => whisper is never called, buffer stays empty."""
        transcribe = Spy(ret="should not run")
        c = VoiceController(transcribe_fn=transcribe)
        # Loud speech, but no wake word — exactly the ambient-conversation case.
        for i in range(20):
            c.step(Frame(seq=i, wake_score=0.1, is_speech=True))
        self.assertEqual(transcribe.calls, [], "transcriber ran on pre-wake audio")
        self.assertIs(c.state, State.IDLE)
        self.assertEqual(c._buffer, [])
        self.assertNotIn("transcribe", c.events())


class HappyPath(unittest.TestCase):
    def test_wake_capture_transcribe_dispatch_speak(self):
        transcribe = Spy(ret="turn on the lights")
        gate = Spy(ret="Lights on. Done.")
        tts = Spy()
        c = VoiceController(transcribe_fn=transcribe, gate_fn=gate, tts_fn=tts)
        c.step(wake(0))
        self.assertIs(c.state, State.CAPTURE)
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):        # 3 silence frames end the utterance
            c.step(silence(i))
        self.assertEqual(len(transcribe.calls), 1)
        self.assertEqual(len(gate.calls), 1)
        self.assertEqual(gate.calls[0][0], "turn on the lights")  # gate sees the text
        self.assertIs(c.state, State.SPEAK)
        # advance the two reply chunks ("Lights on", "Done")
        c.step(silence(7))
        c.step(silence(8))
        self.assertEqual(len(tts.calls), 2)
        self.assertIs(c.state, State.IDLE)
        self.assertIn("armed", c.events())
        self.assertIn("disarm", c.events())


class FalsePositive(unittest.TestCase):
    def test_false_wake_returns_to_idle_without_transcribing(self):
        transcribe = Spy()
        c = VoiceController(transcribe_fn=transcribe,
                            config=VoiceConfig(false_positive_frames=4))
        c.step(wake(0))
        for i in range(1, 8):        # only silence after the wake — a false trigger
            c.step(silence(i))
        self.assertEqual(transcribe.calls, [])
        self.assertIn("false_positive", c.events())
        self.assertIs(c.state, State.IDLE)


class BargeIn(unittest.TestCase):
    def test_barge_interrupts_speak(self):
        c = VoiceController(transcribe_fn=Spy(ret="q"),
                            gate_fn=Spy(ret="one. two. three. four."))
        c.step(wake(0))
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):
            c.step(silence(i))
        self.assertIs(c.state, State.SPEAK)
        c.step(silence(7))                       # speaks chunk "one"
        c.step(Frame(seq=8, barge=True))         # user talks over the reply
        self.assertIs(c.state, State.IDLE)
        self.assertIn("barge_in", c.events())
        barge = [r for r in c.receipts if r.event == "barge_in"][0]
        self.assertGreater(barge.meta["unspoken"], 0)   # chunks were left unspoken


class SpeakerGate(unittest.TestCase):
    def test_unknown_speaker_dropped_before_transcribe(self):
        transcribe = Spy(ret="secret")
        c = VoiceController(transcribe_fn=transcribe,
                            speaker_fn=lambda buf: None)   # never enrolled
        c.step(wake(0))
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):
            c.step(silence(i))
        self.assertEqual(transcribe.calls, [], "unknown speaker reached the transcriber")
        self.assertIn("unknown_speaker", c.events())
        self.assertIs(c.state, State.IDLE)

    def test_known_speaker_binds_identity_through_gate(self):
        gate = Spy(ret="ok")
        c = VoiceController(transcribe_fn=Spy(ret="status"),
                            gate_fn=gate,
                            speaker_fn=lambda buf: "operator")
        c.step(wake(0))
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):
            c.step(silence(i))
        self.assertEqual(gate.calls[0][1], "operator")   # speaker flows to the gate


class NoNewAuthority(unittest.TestCase):
    def test_refused_command_does_not_speak(self):
        tts = Spy()

        def refusing_gate(text, spk):
            raise Refused("needs operator consent")

        c = VoiceController(transcribe_fn=Spy(ret="delete everything"), gate_fn=refusing_gate, tts_fn=tts)
        c.step(wake(0))
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):
            c.step(silence(i))
        self.assertEqual(tts.calls, [])   # a refused spoken command produces no reply
        self.assertIn("dispatch_refused", c.events())
        self.assertIs(c.state, State.IDLE)


class MaxDurationCap(unittest.TestCase):
    def test_runaway_utterance_is_capped(self):
        transcribe = Spy(ret="x")
        c = VoiceController(transcribe_fn=transcribe, config=VoiceConfig(max_capture_frames=10))
        c.step(wake(0))
        for i in range(1, 30):        # unbroken speech, never a silence endpoint
            c.step(speech(i))
        self.assertEqual(len(transcribe.calls), 1, "cap did not force exactly one endpoint")
        endpoint = [r for r in c.receipts if r.event == "endpoint"][0]
        self.assertTrue(endpoint.meta["capped"])


class MuteOverride(unittest.TestCase):
    def test_mute_forces_idle_and_wipes_buffer(self):
        c = VoiceController(transcribe_fn=Spy())
        c.step(wake(0))
        c.step(speech(1))
        self.assertIs(c.state, State.CAPTURE)
        self.assertTrue(c._buffer)
        c.step(Frame(seq=2, mute=True))
        self.assertIs(c.state, State.IDLE)
        self.assertEqual(c._buffer, [])
        self.assertIn("mute", c.events())


class ReceiptHygiene(unittest.TestCase):
    def test_receipts_never_carry_audio_or_transcript(self):
        c = VoiceController(transcribe_fn=Spy(ret="anything"), gate_fn=Spy(ret="reply. here."))
        c.step(wake(0))
        for i in range(1, 4):
            c.step(speech(i))
        for i in range(4, 7):
            c.step(silence(i))
        c.step(silence(7))
        c.step(silence(8))
        forbidden = {"audio", "samples", "transcript", "text", "utterance", "waveform", "frames_raw"}
        for r in c.receipts:
            self.assertEqual(forbidden & r.meta.keys(), set(), f"{r.event} leaked content")


class WakeGateInterface(unittest.TestCase):
    def test_stub_gate_score_drives_arming(self):
        gate = StubWakeGate()
        c = VoiceController(wake_gate=gate, transcribe_fn=Spy())
        c.step(Frame(seq=0, wake_score=0.7))
        self.assertIs(c.state, State.CAPTURE)

    def test_gate_reset_on_every_return_to_idle(self):
        """openWakeWord's streaming buffer must be cleared on each IDLE re-entry."""
        gate = StubWakeGate()
        c = VoiceController(wake_gate=gate, transcribe_fn=Spy(ret="q"),
                            config=VoiceConfig(false_positive_frames=4))
        # false-positive return to IDLE
        c.step(Frame(seq=0, wake_score=0.9))
        for i in range(1, 8):
            c.step(silence(i))
        self.assertIn("false_positive", c.events())
        self.assertGreaterEqual(gate.reset_count, 1)
        before = gate.reset_count
        # mute return to IDLE increments again
        c.step(Frame(seq=100, wake_score=0.9))
        c.step(Frame(seq=101, mute=True))
        self.assertGreater(gate.reset_count, before)

    def test_pcm_consuming_gate_drives_arming_without_wake_score(self):
        """The real interface shape: a gate that reads frame.pcm, not the synthetic score."""

        class PcmGate:
            def __init__(self):
                self.reset_count = 0

            def score(self, frame):
                return 1.0 if frame.pcm == b"WAKE" else 0.0

            def reset(self):
                self.reset_count += 1

        gate = PcmGate()
        c = VoiceController(wake_gate=gate, transcribe_fn=Spy())
        c.step(Frame(seq=0, pcm=b"quiet"))     # no wake word in the audio
        self.assertIs(c.state, State.IDLE)
        c.step(Frame(seq=1, pcm=b"WAKE"))       # wakes on pcm alone, wake_score stays 0.0
        self.assertIs(c.state, State.CAPTURE)


class RealGateHonesty(unittest.TestCase):
    def test_openwakeword_gate_requires_its_dependency(self):
        """The real adapter must fail loudly, not silently no-op, without openwakeword."""
        from willow_mcp.voice.wake_gate import OpenWakeWordGate

        with self.assertRaises((ImportError, ModuleNotFoundError)):
            OpenWakeWordGate(model_paths=["hey_willow.tflite"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
