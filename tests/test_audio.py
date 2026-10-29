"""Feeds synthetic audio through the real Listener loop: noise floor -> speech burst -> silence -> transcription."""
import array, math, os, queue, random, sys, threading, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import audio
from jarvis.config import Config


def block(amp, n=1600):
    return array.array("h", (int(amp * math.sin(i * 0.3) + random.randint(-20, 20)) for i in range(n))).tobytes()


class FakeStream:
    def stop(self): pass
    def close(self): pass


class FakeAudioData:
    def __init__(self, frame_data, rate, width): self.frame_data = frame_data
    def get_raw_data(self, **k): return self.frame_data


class FakeSR:
    """speech_recognition / sounddevice may be missing (or have no PortAudio) on a test machine: stand-ins."""
    AudioData = FakeAudioData
    class Recognizer: pass
    class UnknownValueError(Exception): pass
    class RequestError(Exception): pass


def fake_hw():
    return mock.patch.multiple(audio, sd=object(), sr=FakeSR)


class ListenerVAD(unittest.TestCase):
    def test_detects_utterance_and_ignores_noise(self):
        heard, blocked = [], [False]
        L = audio.Listener(Config(), heard.append, lambda m: None, lambda: blocked[0])
        feed = [block(40)] * 14 + [block(3000)] * 12 + [block(30)] * 12          # room, speech, room
        feed += [block(60)] * 5 + [block(2500)] * 2 + [block(30)] * 12          # a 0.2s click: too short, ignored
        feed += [block(3000)] * 10 + [block(30)] * 12                           # second real utterance
        q = queue.Queue()
        for b in feed:
            q.put(b)
        with fake_hw(), mock.patch.object(L, "_open", return_value=FakeStream()), \
             mock.patch.object(L, "_recognize", side_effect=lambda r, a: "hello jarvis %d" % len(a.frame_data)):
            L._open = lambda qq: (setattr(L, "device_name", "fake"), [qq.put(b) for b in feed], FakeStream())[2]
            t = threading.Thread(target=L.run, daemon=True); t.start()
            time.sleep(1.5); L.stop(); t.join(2)
        self.assertEqual(len(heard), 2, heard)
        self.assertTrue(all(h.startswith("hello jarvis") for h in heard))

    def test_blocked_while_speaking(self):
        heard = []
        L = audio.Listener(Config(), heard.append, lambda m: None, lambda: True)
        feed = [block(40)] * 14 + [block(3000)] * 12 + [block(30)] * 12
        with fake_hw(), mock.patch.object(L, "_recognize", return_value="x"):
            L._open = lambda qq: ([qq.put(b) for b in feed], FakeStream())[1]
            t = threading.Thread(target=L.run, daemon=True); t.start()
            time.sleep(1); L.stop(); t.join(2)
        self.assertEqual(heard, [])


class BargeIn(unittest.TestCase):
    """While Jarvis talks the mic stays open, but only a clearly loud human voice may interrupt."""

    def run_listener(self, feed, speaking, text="stop", barge_result=True):
        heard, barged = [], []
        L = audio.Listener(Config(), heard.append, lambda m: None, lambda: False,
                           is_speaking=lambda: speaking,
                           on_barge=lambda t: (barged.append(t), barge_result)[1])
        with fake_hw(), mock.patch.object(L, "_recognize", return_value=text):
            L._open = lambda qq: ([qq.put(b) for b in feed], FakeStream())[1]
            t = threading.Thread(target=L.run, daemon=True); t.start()
            time.sleep(1.2); L.stop(); t.join(2)
        return heard, barged, L

    def test_loud_voice_interrupts_speech(self):
        feed = [block(40)] * 14 + [block(3000)] * 8 + [block(30)] * 12
        heard, barged, _ = self.run_listener(feed, speaking=True)
        self.assertEqual(barged, ["stop"])
        self.assertEqual(heard, [], "a barge-in must not be handled as a normal command")

    def test_quiet_echo_of_own_voice_is_ignored(self):
        feed = [block(40)] * 14 + [block(300)] * 10 + [block(30)] * 12      # leaks through speakers, not a shout
        heard, barged, _ = self.run_listener(feed, speaking=True)
        self.assertEqual((heard, barged), ([], []))

    def test_same_loudness_is_a_normal_command_when_silent(self):
        feed = [block(40)] * 14 + [block(3000)] * 8 + [block(30)] * 12
        heard, barged, _ = self.run_listener(feed, speaking=False, text="open notepad")
        self.assertEqual((heard, barged), (["open notepad"], []))

    def test_echo_makes_listener_less_jumpy(self):
        feed = [block(40)] * 14 + [block(3000)] * 8 + [block(30)] * 12
        _, barged, L = self.run_listener(feed, speaking=True, text="blah blah", barge_result=False)
        self.assertEqual(barged, ["blah blah"])
        self.assertGreater(L._barge_mult, 1.0)


if __name__ == "__main__":
    unittest.main()
