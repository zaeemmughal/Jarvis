"""Voice output.

Order of preference: Microsoft Edge neural voice (edge-tts, natural British "Jarvis" voice, needs internet)
-> the operating system voice (Windows SAPI via PowerShell, `say` on macOS, espeak on Linux).
Replies are cut into short clips. Every clip starts being synthesised the moment it is queued (up to three in
parallel), so the first sentence is heard as soon as it exists while the rest is still being made - and the HUD is told
when each clip starts playing, so the on-screen text is typed in step with the voice.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from .brain import clean_for_speech
from .config import Config

log = logging.getLogger("jarvis.tts")
IS_WIN = os.name == "nt"
NOWIN = 0x08000000 if IS_WIN else 0

try:
    import edge_tts
except Exception:
    edge_tts = None


def chunk_text(text: str, limit: int = 200, target: int = 70) -> list[str]:
    """Cut text into clips of roughly `target`..`limit` characters on sentence ends. Short clips mean the first one is
    ready (and heard) quickly; a single huge sentence is broken at commas."""
    pieces: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", clean_for_speech(text)):
        while len(s) > limit:
            cut = max(s.rfind(", ", 0, limit), s.rfind("; ", 0, limit), s.rfind(" ", 0, limit))
            if cut < 40:
                cut = limit
            pieces.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            pieces.append(s)
    chunks, cur = [], ""
    for s in pieces:
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
        if len(cur) >= target:
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    return [c for c in chunks if re.search(r"\w", c)]


def estimate_secs(text: str) -> float:
    return max(0.8, len(text) / 14.0)


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


class Speaker:
    """Queue of clips -> sound. say() may be called from any thread, as often as you like (once per sentence while an
    answer is still being written); clips play in order with no gap. stop() silences everything immediately."""

    def __init__(self, cfg: Config, on_idle=None, on_chunk=None):
        self.cfg, self.on_idle, self.on_chunk = cfg, on_idle, on_chunk   # on_chunk(text, seconds): a clip starts now
        self.speaking = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._proc = None
        self._edge_bad_until = 0.0
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tts-synth")
        self._mci_n = 0
        self.engine = self._detect()
        self._pending = 0
        self._active = False
        self._gen = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="tts").start()

    # ---- engine selection -----------------------------------------------------
    def _system_ok(self) -> bool:
        if IS_WIN or sys.platform == "darwin":
            return True
        return bool(shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("spd-say"))

    def _detect(self) -> str:
        want = self.cfg.tts_engine
        if want == "off":
            return "off"
        if want in ("auto", "edge") and edge_tts is not None:
            return "edge-tts neural"
        return "system voice" if self._system_ok() else "off"

    # ---- public ---------------------------------------------------------------
    def say(self, text: str) -> None:
        for chunk in chunk_text(text):
            fut = None
            if self.engine.startswith("edge") and time.time() >= self._edge_bad_until:
                fut = self._pool.submit(self._synth, chunk)            # start making the sound right now
            with self._lock:
                self._pending += 1
                self.speaking.set()
                self._jobs.put((self._gen, chunk, fut))

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._jobs.put(None)
                break
            self._discard(item[2])
            with self._lock:
                self._pending = max(0, self._pending - 1)
        with self._lock:
            if self._pending == 0 and not self._active:
                self.speaking.clear()

    @staticmethod
    def _discard(fut) -> None:
        if fut is None or fut.cancel():
            return
        fut.add_done_callback(lambda f: (not f.cancelled() and f.exception() is None) and _rm(f.result()))

    # ---- worker ---------------------------------------------------------------
    def _run(self):
        while True:
            item = self._jobs.get()
            if item is None:
                return
            gen, text, fut = item
            with self._lock:
                live = gen == self._gen
                if live:
                    self._stop.clear()
                    self._active = True
            try:
                if live:
                    self._play_chunk(text, fut)
                else:
                    self._discard(fut)
            except Exception as e:
                log.warning("tts error: %s", e)
            with self._lock:
                self._active = False
                self._pending = max(0, self._pending - 1)
                idle = self._pending == 0 and self._jobs.empty()
            if idle:
                time.sleep(0.25)                                       # let the room go quiet before the mic re-opens
                with self._lock:
                    idle = self._pending == 0 and self._jobs.empty() and not self._active
                    if idle:
                        self.speaking.clear()
                if idle and self.on_idle:
                    self.on_idle()

    def _announce(self, text: str, secs: float) -> None:
        if self.on_chunk:
            try:
                self.on_chunk(text, secs)
            except Exception:
                log.exception("on_chunk failed")

    def _wait_synth(self, fut):
        """Wait for a clip to be made, but give up at once if stop() is called."""
        t0 = time.time()
        while not self._stop.is_set():
            try:
                return fut.result(timeout=0.1)
            except FutureTimeout:
                if time.time() - t0 > 30:
                    raise RuntimeError("speech synthesis timed out")
        self._discard(fut)
        return None

    def _play_chunk(self, text: str, fut):
        path = None
        if fut is not None:
            try:
                path = self._wait_synth(fut)
            except Exception as e:
                log.warning("edge-tts failed, using system voice: %s", e)
                self._edge_bad_until = time.time() + 90
        if self._stop.is_set():
            if path:
                _rm(path)
            return
        if path:
            try:
                self._play_file(path, text)
            finally:
                _rm(path)
            return
        if self.engine == "off":
            secs = min(6.0, 0.05 * len(text) + 0.6)
            self._announce(text, secs)
            end = time.time() + secs
            while time.time() < end and not self._stop.is_set():
                time.sleep(0.05)
            return
        if self._system_ok():
            self._play_system(text)

    # ---- edge neural voice ----------------------------------------------------
    def _synth(self, text: str) -> str:
        last = None
        for _ in range(2):                                             # edge-tts sometimes returns nothing: retry once
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_")
            os.close(fd)
            try:
                async def go():
                    await edge_tts.Communicate(text, self.cfg.tts_voice, rate=self.cfg.tts_rate).save(path)
                asyncio.run(go())
                if os.path.getsize(path) >= 200:
                    return path
                last = RuntimeError("empty audio")
            except Exception as e:
                last = e
            _rm(path)
        raise last or RuntimeError("synthesis failed")

    def _mci(self, cmd: str) -> str:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
        return buf.value

    def _play_file(self, path: str, text: str = ""):
        if IS_WIN:
            self._mci_n += 1
            alias = "jv%d" % self._mci_n
            self._mci('open "%s" type mpegvideo alias %s' % (path, alias))
            try:
                try:
                    secs = int(self._mci("status %s length" % alias) or 0) / 1000.0
                except ValueError:
                    secs = 0.0
                self._announce(text, secs or estimate_secs(text))
                self._mci("play %s" % alias)
                t0 = time.time()
                while not self._stop.is_set():
                    time.sleep(0.04)
                    if time.time() - t0 > 0.3 and self._mci("status %s mode" % alias) != "playing":
                        break
                self._mci("stop %s" % alias)
            finally:
                self._mci("close %s" % alias)
            return
        player = next((p for p in (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"],
                                   ["afplay"], ["mpv", "--no-video", "--really-quiet"]) if shutil.which(p[0])), None)
        if not player:
            raise RuntimeError("no audio player found")
        self._announce(text, estimate_secs(text))
        self._proc = subprocess.Popen(player + [path])
        while self._proc.poll() is None and not self._stop.is_set():
            time.sleep(0.04)
        if self._proc.poll() is None:
            self._proc.terminate()

    # ---- system voice ---------------------------------------------------------
    def _play_system(self, text: str):
        env = dict(os.environ, JARVIS_SAY=clean_for_speech(text))
        if IS_WIN:
            ps = ("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                  "$v=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Gender -eq 'Male' -and $_.Enabled}|Select-Object -First 1;"
                  "if($v){$s.SelectVoice($v.VoiceInfo.Name)};$s.Rate=1;$s.Speak($env:JARVIS_SAY)")
            cmd = ["powershell", "-NoProfile", "-Command", ps]
        elif sys.platform == "darwin":
            cmd = ["say", env["JARVIS_SAY"]]
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("spd-say")
            cmd = [exe, env["JARVIS_SAY"]]
        self._announce(text, estimate_secs(text))
        self._proc = subprocess.Popen(cmd, env=env, creationflags=NOWIN,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while self._proc.poll() is None and not self._stop.is_set():
            time.sleep(0.05)
        if self._proc.poll() is None:
            self._proc.terminate()
