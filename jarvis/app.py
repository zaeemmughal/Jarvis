"""Controller: wires microphone, wake word, command skills, AI brain, voice and HUD together."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from . import browser, net, services, skills
from .audio import Listener
from .brain import Brain
from .config import Config, LOG_DIR
from .dialog import Dialog
from .face import Face
from .memory import Memory
from .sysinfo import SysMonitor
from .tts import Speaker
from . import winctl

log = logging.getLogger("jarvis")


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(filename=os.path.join(LOG_DIR, "jarvis.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class Jarvis:
    def __init__(self, cfg: Config, headless: bool = False):
        self.cfg = cfg
        browser.set_preferred(cfg.browser)
        self.running = True
        self.mem = Memory()
        self.brain = Brain(cfg, self.mem)
        self.brain.on_status = lambda kind, msg: self.hud_post("log", "err" if kind == "err" else "sys", msg)
        self.face = Face()
        self.speaker = Speaker(cfg, on_idle=self._speech_done, on_chunk=self._speech_chunk)
        self.monitor = SysMonitor()
        self.stats: dict = {}
        self.weather = None
        self.online = False
        self.mic_on = True
        self.wake_on = cfg.wake_enabled
        self.awake_until = 0.0
        self.last_reply = ""
        self.addressed = True                     # was the current sentence prefixed with "Jarvis"? (set by the router)
        self.epoch = 0                            # bumped by every interrupt; replies from older requests are dropped
        self.dialog = Dialog(cfg.context_secs, winctl.foreground_info if winctl.supported() else None)
        self.hidden = False
        self.tray = None
        self.timers: list[dict] = []
        self.abort_typing = threading.Event()
        self.work_q: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self.listener = Listener(cfg, self.on_heard, lambda m: self.hud_post("log", "sys", m), self._mic_blocked,
                                 is_speaking=self.speaker.speaking.is_set, on_barge=self.on_barge)
        self.hud = None
        if not headless:
            from .ui import HUD
            self.hud = HUD(self, cfg)

    # ------------------------------------------------------------------ plumbing
    def hud_post(self, *event):
        if self.hud:
            self.hud.post(*event)

    @property
    def state(self) -> str:
        if self.speaker.speaking.is_set():
            return "speaking"
        if self._busy.is_set() or self.listener.transcribing > 0:
            return "thinking"
        if not self.mic_on or not self.listener.available:
            return "mic_off"
        if self.listener.recording:
            return "listening"
        if self.wake_on and time.time() > self.awake_until:
            return "standby"
        return "active"

    def _mic_blocked(self) -> bool:
        """Hard mute. While Jarvis talks the mic normally stays open (barge-in) so you can say "stop"."""
        return (not self.mic_on) or (self.speaker.speaking.is_set() and not self.cfg.barge_in)

    def _speech_chunk(self, text: str, secs: float):
        """A clip of speech starts playing right now: type the same words on the HUD over the same time."""
        self.hud_post("chunk", text, secs)

    def _speech_done(self):
        self.awake_until = time.time() + self.cfg.follow_up_secs

    # ------------------------------------------------------------------ controls
    def toggle_mic(self):
        self.set_mic(not self.mic_on)

    def set_mic(self, on: bool):
        self.mic_on = on

    def toggle_wake(self):
        self.set_wake(not self.wake_on)

    def set_wake(self, on: bool):
        self.wake_on = on
        self.awake_until = time.time() + self.cfg.follow_up_secs

    def stop_speaking(self):
        self.interrupt(listen=False)

    def interrupt(self, listen: bool = True):
        """Stop talking NOW, forget queued work and any reply still being thought up, abort typing/demo.
        listen=True also keeps the conversation open (no wake word needed) and plays a small 'go ahead' chime."""
        self.epoch += 1
        try:
            while True:
                item = self.work_q.get_nowait()
                if item is None:                      # shutdown marker: keep it
                    self.work_q.put(None)
                    break
        except queue.Empty:
            pass
        self.speaker.stop()
        self.abort_typing.set()
        if self.work_q.empty():
            self._busy.clear()
        if listen:
            self.awake_until = time.time() + self.cfg.follow_up_secs
            self.hud_post("flash")
            threading.Thread(target=winctl.chime, daemon=True).start()

    def _control(self, intent: str):
        if intent == "stop":
            self.interrupt(listen=True)
        else:                                          # exit: stop whatever is going on, say goodbye, then close
            self.interrupt(listen=False)
            self.respond("Goodbye. Shutting down.")
            self.quit_later(2.2)

    def quit_later(self, secs: float = 2.2):
        """Close once the goodbye has been spoken (or after a few seconds at most)."""
        def go():
            time.sleep(0.5)
            self.wait_speech(secs + 5)
            self.quit()
        threading.Thread(target=go, daemon=True).start()

    # ---- background mode: the window can disappear, the ears stay on --------------------------
    def hide_window(self):
        self.hud_post("hide")

    def show_window(self):
        self.hud_post("show")

    def on_window_close(self):
        """The window's X button."""
        if self.cfg.close_to_background:
            self.hide_window()
            self.hud_post("log", "sys", "Still listening in the background. Say \"Jarvis closed\" to end me.")
        else:
            self.quit()

    def quit(self):
        if not self.running:
            return
        self.running = False
        self.listener.stop()
        self.speaker.stop()
        for t in list(self.timers):
            t["timer"].cancel()
        if self.tray:
            self.tray.stop()
        self.work_q.put(None)
        self.hud_post("quit")

    # ------------------------------------------------------------------ input
    def on_barge(self, text: str) -> bool:
        """An utterance that started while Jarvis was talking. Only 'stop' / 'Jarvis closed' style words count;
        anything else is most likely Jarvis's own voice coming back through the speakers, so it is ignored."""
        intent = skills.control_of(text)
        if not intent:
            return False
        self.hud_post("heard", "You: " + text, False)
        self._control(intent)
        return True

    def on_heard(self, text: str):
        """Called from the listener thread with each transcribed utterance."""
        now = time.time()
        woke = skills.has_wake_word(text)
        intent = skills.control_of(text)
        if intent:
            # Control words are handled right here, never queued behind a slow answer.
            active = (not self.wake_on) or woke or now <= self.awake_until
            busy = self.speaker.speaking.is_set() or self._busy.is_set()
            if (intent == "stop" and (active or busy)) or (intent == "exit" and active):
                self.hud_post("heard", "You: " + text, False)
                self._control(intent)
                return
        if self.wake_on and not woke and now > self.awake_until:
            self.hud_post("heard", "\u00b7 " + text, True)          # dim: heard, but not addressed to me
            return
        self.awake_until = now + self.cfg.follow_up_secs
        self.hud_post("heard", "You: " + text, False)
        self.submit(text)

    def submit(self, text: str, typed: bool = False):
        text = text.strip()
        if not text:
            return
        if typed:
            self.hud_post("heard", "You: " + text, False)
            self.awake_until = time.time() + self.cfg.follow_up_secs
            intent = skills.control_of(text)
            if intent:
                self._control(intent)
                return
        self._busy.set()
        self.work_q.put(text)

    def _worker(self):
        while self.running:
            text = self.work_q.get()
            if text is None:
                return
            try:
                self._process(text)
            except Exception:
                log.exception("request failed")
                self.respond("Apologies, something went wrong with that request.")
            finally:
                if self.work_q.empty():
                    self._busy.clear()

    def _process(self, text: str):
        ep = self.epoch
        self.hud_post("log", "you", text)
        reply = skills.route(self, text)
        if ep != self.epoch:                           # "stop" arrived while this was being worked out
            return
        sources = []
        if reply is None:
            # The answer is spoken sentence by sentence while the model is still writing it.
            ans = self.brain.ask(skills.strip_wake_raw(text), self.dialog.describe(),
                                 on_sentence=lambda sent: ep == self.epoch and self.speaker.say(sent),
                                 on_mood=lambda m: ep == self.epoch and self._apply_mood(m),
                                 should_stop=lambda: ep != self.epoch)
            if ep != self.epoch:
                return
            self._apply_mood(ans.mood)
            reply, sources = ans.text, ans.sources
            self.mem.add_turn("user", text)
            self.mem.add_turn("model", reply)
            if ans.streamed:                                   # already spoken: only log it
                self.last_reply = reply
                self.hud_post("log", "jarvis", reply)
                for title, url in sources:
                    self.hud_post("log", "src", "%s%s" % (title, "\n" + url if url and url != title else ""))
                return
        if reply:
            self.respond(reply, sources)

    def _apply_mood(self, mood: str):
        if mood in ("happy", "sad", "angry", "surprised"):
            self.face.mood(mood, 6)

    def respond(self, reply: str, sources=None):
        self.last_reply = reply
        self.hud_post("log", "jarvis", reply)
        for title, url in (sources or []):
            self.hud_post("log", "src", "%s%s" % (title, "\n" + url if url and url != title else ""))
        self.speaker.say(reply)                      # the HUD text is typed as each clip starts (see _speech_chunk)

    def say_async(self, text: str):
        """Used by timers and the demo: speak without a user request."""
        self.hud_post("flash")
        self.face.mood("surprised", 3)
        self.respond(text)

    # ------------------------------------------------------------------ skills support
    def add_timer(self, seconds: int, message: str, label: str = ""):
        entry = {"due": time.time() + seconds, "label": label or "timer"}

        def fire():
            if entry in self.timers:
                self.timers.remove(entry)
            self.say_async(message)

        entry["timer"] = threading.Timer(seconds, fire)
        entry["timer"].daemon = True
        entry["timer"].start()
        self.timers.append(entry)

    def cancel_timers(self) -> int:
        n = len(self.timers)
        for t in self.timers:
            t["timer"].cancel()
        self.timers.clear()
        return n

    def timers_left(self):
        now = time.time()
        return sorted(((t["label"][:14], t["due"] - now) for t in self.timers), key=lambda x: x[1])

    def type_later(self, text: str):
        self.abort_typing.clear()

        def go():
            time.sleep(2)
            if not winctl.type_text(text, self.abort_typing.is_set):
                self.hud_post("log", "sys", "Typing aborted.")
        threading.Thread(target=go, daemon=True).start()

    def wait_speech(self, timeout: float = 40):
        t0 = time.time()
        time.sleep(0.15)
        while self.speaker.speaking.is_set() and time.time() - t0 < timeout and self.running:
            time.sleep(0.1)

    def run_demo(self):
        who = self.cfg.creator
        steps = [
            ("Hello everyone. I am Jarvis, a voice controlled A I assistant built with Python%s." %
             (", created by %s" % who if who else ""), lambda: self.face.mood("happy", 6)),
            ("I can look around.", lambda: self.face.look(-1, 0, 2)),
            ("In every direction.", lambda: self.face.look(1, 0, 2)),
            ("I can blink, wink, and show how I feel.", lambda: (self.face.blink(), self.face.mood("surprised", 3))),
            ("Ask me anything, and I will search Google and answer you out loud.", lambda: self.face.mood("happy", 4)),
            ("I can check the weather, read the news, set timers, take notes, and do your maths.",
             lambda: self.face.look(0, -0.6, 3)),
            ("I can also open your apps, type for you, and control your computer by voice.",
             lambda: self.face.look(0, 0, 1)),
            ("Just say my name, and ask. Thank you for watching.", lambda: self.face.mood("happy", 6)),
        ]

        ep = self.epoch

        def go():
            for line, act in steps:
                if not self.running or ep != self.epoch:
                    return
                act()
                self.respond(line)
                self.wait_speech()
                time.sleep(0.25)
        threading.Thread(target=go, daemon=True, name="demo").start()

    # ------------------------------------------------------------------ background jobs
    def _stats_loop(self):
        while self.running:
            self.stats = self.monitor.poll()
            time.sleep(1.5)

    def _net_loop(self):
        while self.running:
            self.online = net.is_online()
            time.sleep(20)

    def _boot(self):
        log_ = lambda m: self.hud_post("log", "sys", m)
        log_("Core online.")
        threading.Thread(target=skills.APPS.build, daemon=True).start()
        log_("Voice output: %s." % self.speaker.engine)
        self.online = net.is_online()
        log_("Network: %s." % ("online" if self.online else "OFFLINE"))
        log_("Intelligence: %s." % self.brain.check())
        try:
            self.weather = services.weather(self.cfg.home_city) if self.online else None
        except Exception:
            self.weather = None
        time.sleep(0.9)
        self.face.sleep(False)
        h = int(time.strftime("%H"))
        g = "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
        who = self.mem.name or self.cfg.user_name
        line = "%s%s. Systems online." % (g, ", " + who if who else "")
        line += " Say Jarvis to get my attention." if self.wake_on else " I'm listening."
        if not (self.cfg.groq_key or self.cfg.xai_key or self.cfg.openrouter_key):
            self.hud_post("log", "sys", "Tip: add GROQ_API_KEY (console.groq.com) to .env for smart answers.")
        log_("Websites open in: %s." % browser.name())
        self.respond(line)

    # ------------------------------------------------------------------ run
    def start_threads(self):
        self.face.sleep(True)                      # eyes open during the boot sequence
        for fn in (self._worker, self._stats_loop, self._net_loop, self._boot):
            threading.Thread(target=fn, daemon=True).start()
        self.listener.start()

    def run(self):
        self.start_threads()
        from .tray import Tray
        tray = Tray(self)
        if tray.start():
            self.tray = tray
            self.hud.has_tray = True
        if self.cfg.background:
            self.hud.hide()
        self.hud.run()
        self.quit()

    def selftest(self, phrases):
        """Headless check of the router (no audio, no window)."""
        self.monitor.poll()
        time.sleep(0.2)
        self.stats = self.monitor.poll()
        import webbrowser
        webbrowser.open = lambda *a, **k: print("   [browser] " + a[0])        # do not really open anything
        browser.open_url = lambda url, **k: print("   [%s] %s%s" % (browser.name(), url, " (incognito)" if k.get("incognito") else ""))
        skills.time.sleep = lambda *_: None
        self.quit_later = lambda *a, **k: print("   [would quit]")
        for p in phrases:
            r = skills.route(self, p)
            print("%-34s -> %s" % (p, "(AI brain)" if r is None else r))
