"""Microphone capture without PyAudio.

`sounddevice` streams raw audio, a small adaptive energy VAD cuts it into utterances, and each utterance is
transcribed on a worker thread (Google web speech, or an offline Vosk model if the network is down).
"""
from __future__ import annotations

import array
import collections
import json
import logging
import math
import os
import queue
import threading
import time

from . import net
from .config import Config, ROOT

log = logging.getLogger("jarvis.audio")

try:
    import sounddevice as sd
except Exception as _e:        # PortAudio missing, package not installed...
    sd = None
    _SD_ERR = str(_e)
try:
    import speech_recognition as sr
except Exception:
    sr = None
try:
    import vosk
except Exception:
    vosk = None

RATE = 16000


def list_devices() -> str:
    if sd is None:
        return "sounddevice is not available: %s" % _SD_ERR
    return str(sd.query_devices())


def rms(block: bytes) -> float:
    a = array.array("h")
    a.frombytes(block[: len(block) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


class Listener(threading.Thread):
    """Calls on_text(str) for every transcribed utterance. Exposes .level (0..1) and status flags for the HUD.

    is_blocked()  -> True = hard mute (microphone switched off): nothing is recorded.
    is_speaking() -> True while Jarvis is talking. The mic stays open ("barge-in") but the speech threshold is raised
                     so only a clearly louder human voice starts a recording, and those recordings go to on_barge(text)
                     instead of on_text(text). on_barge returns True when the text was a real interruption (stop /
                     close); False means it was probably Jarvis's own voice coming back through the speakers, and the
                     listener becomes a little less sensitive for the rest of that sentence.
    """

    def __init__(self, cfg: Config, on_text, on_info, is_blocked, is_speaking=None, on_barge=None):
        super().__init__(daemon=True, name="listener")
        self.cfg, self.on_text, self.on_info, self.is_blocked = cfg, on_text, on_info, is_blocked
        self.is_speaking = is_speaking or (lambda: False)
        self.on_barge = on_barge
        self._barge_mult = 1.0
        self.level = 0.0
        self.available = False
        self.recording = False
        self.transcribing = 0
        self.device_name = ""
        self.running = True
        self.stt_name = "none"
        self._stt_q: queue.Queue = queue.Queue()
        self._vosk_model = None
        self._rate = RATE
        self._groq_off = 0.0

    # ---- device ---------------------------------------------------------------
    def _pick_device(self):
        want = self.cfg.mic_device
        if not want:
            return None
        if want.isdigit():
            return int(want)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and want.lower() in d["name"].lower():
                return i
        return None

    def _open(self, q: queue.Queue):
        dev = self._pick_device()

        def cb(indata, frames, t, status):
            try:
                q.put_nowait(bytes(indata))
            except queue.Full:
                pass

        for rate in (RATE, None):
            if rate is None:
                rate = int(sd.query_devices(dev, "input")["default_samplerate"])
            try:
                stream = sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                                           blocksize=rate // 10, device=dev, callback=cb)
                stream.start()
                self._rate = rate
                try:
                    self.device_name = sd.query_devices(dev, "input")["name"]
                except Exception:
                    self.device_name = "default"
                return stream
            except Exception as e:
                log.warning("mic open at %s Hz failed: %s", rate, e)
        raise RuntimeError("could not open the microphone")

    # ---- speech to text -------------------------------------------------------
    def _load_vosk(self):
        if not vosk:
            return
        for name in ("model", "vosk-model-small-en-us-0.15"):
            path = os.path.join(ROOT, name)
            if os.path.isdir(path):
                try:
                    vosk.SetLogLevel(-1)
                    self._vosk_model = vosk.Model(path)
                    return
                except Exception as e:
                    log.warning("vosk model failed: %s", e)

    _HALLUCINATIONS = {"you", "thank you", "thanks", "thank you.", "thanks for watching", "thanks for watching!",
                       "bye", "bye.", ".", "okay", "ok", "uh", "um", "hmm", "mm", "the end"}

    def _groq_stt(self, audio) -> str | None:
        """Groq-hosted Whisper: far more accurate than the free Google recogniser, esp. with accents and names.
        Returns the text, "" if nothing was said, or None when it could not be used (caller falls back to Google)."""
        cfg = self.cfg
        if cfg.stt == "google" or not cfg.groq_key or cfg.force_offline or time.time() < self._groq_off:
            return None
        wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
        try:
            data = net.post_multipart(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                {"model": cfg.stt_model, "language": (cfg.language or "en").split("-")[0].lower(),
                 "response_format": "json", "temperature": "0",
                 "prompt": "Jarvis."},
                {"file": ("speech.wav", wav, "audio/wav")}, 20, {"Authorization": "Bearer " + cfg.groq_key})
        except net.NetError as e:
            self._groq_off = time.time() + (600 if e.status in (401, 403) else 45 if e.status == 429 else 20)
            if e.status in (401, 403):
                self.on_info("Groq speech-to-text rejected the key, using Google recognition instead.")
            log.warning("groq stt failed: %s", e)
            return None
        text = str(data.get("text", "")).strip()
        self.stt_name = "groq whisper"
        return "" if text.lower().strip(" .!") in self._HALLUCINATIONS else text

    def _recognize(self, rec, audio) -> str:
        if not self.cfg.force_offline:
            heard = self._groq_stt(audio)
            if heard is not None:
                return heard
        if not (self.cfg.force_offline and self._vosk_model):
            try:
                self.stt_name = "google"
                return rec.recognize_google(audio, language=self.cfg.language)
            except sr.UnknownValueError:
                return ""
            except sr.RequestError:
                pass
        if self._vosk_model:
            self.stt_name = "vosk (offline)"
            k = vosk.KaldiRecognizer(self._vosk_model, 16000)
            k.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
            return json.loads(k.FinalResult()).get("text", "")
        self.on_info("No internet and no offline model - use the text box.")
        return ""

    def _stt_worker(self):
        rec = sr.Recognizer()
        while self.running:
            item = self._stt_q.get()
            if item is None:
                break
            audio, barge = item
            try:
                text = self._recognize(rec, audio)
            except Exception as e:
                log.warning("stt error: %s", e)
                text = ""
            self.transcribing -= 1
            if not text.strip():
                continue
            if barge and self.on_barge:
                try:
                    if not self.on_barge(text.strip()):
                        self._barge_mult = min(self._barge_mult * 1.3, 4.0)      # that was an echo: be less jumpy
                except Exception:
                    log.exception("barge-in handler failed")
            else:
                self.on_text(text.strip())

    # ---- main loop ------------------------------------------------------------
    def run(self):
        if sd is None or sr is None:
            why = "sounddevice" if sd is None else "SpeechRecognition"
            self.on_info("Voice input unavailable (%s not installed). Use the text box." % why)
            return
        self._load_vosk()
        q: queue.Queue = queue.Queue(maxsize=200)
        try:
            stream = self._open(q)
        except Exception as e:
            self.on_info("No microphone found (%s). Use the text box." % e)
            return
        self.available = True
        self.on_info("Microphone ready: %s" % self.device_name)
        threading.Thread(target=self._stt_worker, daemon=True, name="stt").start()

        floor, calib, pre = 0.0, 0, collections.deque(maxlen=4)
        frames, voiced, quiet, loud_run = [], 0, 0, 0
        rec_barge = False
        try:
            while self.running:
                try:
                    block = q.get(timeout=0.3)
                except queue.Empty:
                    continue
                r = rms(block)
                self.level = min(1.0, r / 5000.0) if not self.is_blocked() else 0.0
                if self.is_blocked():                       # muted, or Jarvis is talking
                    frames, voiced, quiet, loud_run = [], 0, 0, 0
                    self.recording = False
                    pre.clear()
                    continue
                if calib < 10:                              # learn the room noise for one second
                    floor = r if calib == 0 else (floor * calib + r) / (calib + 1)
                    calib += 1
                    continue
                speaking = bool(self.is_speaking())
                if not speaking:
                    self._barge_mult = 1.0
                base = max(floor * 3.0, self.cfg.vad_min)
                start_thr = base * max(self.cfg.barge_sens, 1.0) * self._barge_mult if speaking else base
                end_thr = (base if not speaking else base * 1.3) * 0.6
                if not self.recording:
                    pre.append(block)
                    if r > start_thr:
                        loud_run += 1
                    else:
                        loud_run = 0
                        if not speaking:                    # never learn Jarvis's own voice as "room noise"
                            floor = floor * 0.95 + r * 0.05
                    if loud_run >= 2:
                        self.recording, frames, voiced, quiet, rec_barge = True, list(pre), 2, 0, speaking
                else:
                    frames.append(block)
                    if r > end_thr:
                        voiced, quiet = voiced + 1, 0
                    else:
                        quiet += 1
                    # normal: 0.8 s of silence ends it (14 s cap). Interruptions are short ("stop"): 0.5 s, 4 s cap.
                    if quiet >= (5 if rec_barge else 8) or len(frames) >= (40 if rec_barge else 140):
                        self.recording = False
                        loud_run = 0
                        pre.clear()
                        if voiced >= 4:
                            self.transcribing += 1
                            self._stt_q.put((sr.AudioData(b"".join(frames), self._rate, 2), rec_barge))
                        frames = []
        finally:
            stream.stop()
            stream.close()

    def stop(self):
        self.running = False
        self._stt_q.put(None)
