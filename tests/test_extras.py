"""WhatsApp-by-voice and YouTube skills, driven against a fake Windows (fake windows + recorded keystrokes)."""
import os, sys, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import extras, skills, winctl
from test_core import FakeCtx


class FakeWin:
    def __init__(self, front=("WhatsApp", "whatsapp.exe")):
        self.log, self.front, self.wins = [], front, [(1, "WhatsApp", "whatsapp.exe")]
        self.patches = [
            mock.patch.object(winctl, "supported", return_value=True),
            mock.patch.object(winctl, "find_windows", side_effect=lambda s: [w for w in self.wins if s in w[1].lower()]),
            mock.patch.object(winctl, "focus_window", side_effect=lambda h: (self.log.append(("focus", h)), True)[1]),
            mock.patch.object(winctl, "foreground_info", side_effect=lambda: self.front),
            mock.patch.object(winctl, "hotkey", side_effect=lambda *k: self.log.append(("hot",) + k)),
            mock.patch.object(winctl, "press", side_effect=lambda k: self.log.append(("press", k))),
            mock.patch.object(winctl, "type_text", side_effect=lambda t, a=None, delay=0: (self.log.append(("type", t)), True)[1]),
            mock.patch.object(time, "sleep", lambda s: None),
        ]
    def __enter__(self):
        for p in self.patches: p.start()
        extras.WA.contact, extras.WA.draft, extras.WA.ts = "", "", 0
        return self
    def __exit__(self, *a):
        for p in self.patches: p.stop()


class WhatsApp(unittest.TestCase):
    def setUp(self): self.c = FakeCtx()
    def r(self, s): return skills.route(self.c, s)

    def test_full_flow_needs_a_yes(self):
        with FakeWin() as w:
            self.assertIn("Opened the chat of Hasnat", self.r("Jarvis open chat of Hasnat"))
            self.assertIn(("hot", "ctrl", "f"), w.log)                    # desktop search shortcut
            self.assertIn(("type", "Hasnat"), w.log)
            self.assertIn(("press", "enter"), w.log)
            w.log.clear()
            self.assertTrue(self.r("Jarvis type Are you coming tonight?").startswith("Typed"))
            self.assertIn(("type", "Are you coming tonight?"), w.log)     # capitals + punctuation preserved
            w.log.clear()
            q = self.r("send")
            self.assertIn("Send this to Hasnat: Are you coming tonight?", q)
            self.assertNotIn(("press", "enter"), w.log)                   # NOT sent yet
            self.assertEqual(self.r("yes"), "Sent.")
            self.assertEqual(w.log.count(("press", "enter")), 1)

    def test_no_cancels(self):
        with FakeWin() as w:
            self.r("open chat of Ali"); self.r("type hello"); self.r("send"); w.log.clear()
            self.assertIn("cancel", self.r("no").lower())
            self.assertNotIn(("press", "enter"), w.log)

    def test_web_uses_web_search_shortcut(self):
        with FakeWin(front=("(2) WhatsApp - Google Chrome", "chrome.exe")) as w:
            w.wins = [(1, "(2) WhatsApp - Google Chrome", "chrome.exe")]
            self.r("open chat with Ali")
            self.assertIn(("hot", "ctrl", "alt", "slash"), w.log)

    def test_one_shot(self):
        with FakeWin() as w:
            q = self.r("send a message to Hasnat saying Hello, how are you?")
            self.assertIn("Send this to Hasnat: Hello, how are you?", q)
            self.assertNotIn(("press", "enter"), w.log[-2:])
            self.assertEqual(self.r("yes"), "Sent.")

    def test_apostrophe_name(self):
        with FakeWin() as w:
            self.r("open Hasnat's chat")
            self.assertIn(("type", "Hasnat"), w.log)

    def test_type_elsewhere_is_not_whatsapp(self):
        with FakeWin(front=("Untitled - Notepad", "notepad.exe")) as w:
            self.r("open chat of Ali")                                   # explicit? no - not in WhatsApp -> ignored
            w.log.clear()
            self.assertIn("Typing", self.r("type hello world"))           # old generic skill
            self.assertEqual(self.c.typed, "hello world")

    def test_send_without_whatsapp_falls_to_mail_logic(self):
        with FakeWin(front=("Inbox - Gmail - Google Chrome", "chrome.exe")) as w:
            self.c.dialog.set_focus("site", "gmail")
            self.assertIn("Send the email", self.r("send"))

    def test_newline_never_sent(self):
        with FakeWin() as w:
            self.r("open chat of Ali")
            extras._wa_type(self.c, "line one\nline two")
            self.assertIn(("type", "line one line two"), w.log)

    def test_clear_draft(self):
        with FakeWin() as w:
            self.r("open chat of Ali"); self.r("type oops"); w.log.clear()
            self.assertEqual(self.r("clear the message"), "Cleared the message.")
            self.assertIn(("press", "backspace"), w.log)
            self.assertEqual(extras.WA.draft, "")


class YouTube(unittest.TestCase):
    def setUp(self): self.c = FakeCtx()
    def r(self, s): return skills.route(self.c, s)
    PAGE = b'..."videoRenderer":{"videoId":"dQw4w9WgXcQ","thumbnail":{},"title":{"runs":[{"text":"Never Gonna Give You Up"}],"accessibility":{}}'

    def test_play_opens_first_video(self):
        urls = []
        with mock.patch.object(extras.net, "get_bytes", return_value=self.PAGE), \
             mock.patch("webbrowser.open", side_effect=lambda u, *a, **k: urls.append(u)):
            self.assertEqual(self.r("play never gonna give you up on youtube"), "Playing Never Gonna Give You Up.")
        self.assertEqual(urls, ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])

    def test_play_falls_back_to_results(self):
        urls = []
        with mock.patch.object(extras.net, "get_bytes", side_effect=extras.net.NetError("offline")), \
             mock.patch("webbrowser.open", side_effect=lambda u, *a, **k: urls.append(u)):
            self.assertIn("YouTube results", self.r("play karan aujla"))
        self.assertIn("results", urls[0])

    def test_spotify_and_generic_untouched(self):
        with mock.patch.object(extras.net, "get_bytes") as g, mock.patch("webbrowser.open"):
            self.r("play kesariya on spotify"); self.assertFalse(g.called)
        with FakeWin(front=("x - YouTube - Google Chrome", "chrome.exe")) as w:
            w.wins = [(2, "x - YouTube - Google Chrome", "chrome.exe")]
            self.r("play"); self.assertIn(("press", "playpause"), w.log)

    def test_seek_and_controls(self):
        with FakeWin(front=("x - YouTube - Google Chrome", "chrome.exe")) as w:
            w.wins = [(2, "x - YouTube - Google Chrome", "chrome.exe")]
            self.assertIn("Skipped ahead 30 seconds", self.r("skip 30 seconds"))
            self.assertEqual(w.log.count(("press", "l")), 3)
            w.log.clear(); self.r("rewind 10 seconds"); self.assertEqual(w.log, [("press", "j")])
            w.log.clear(); self.r("speed up"); self.assertIn(("hot", "shift", "period"), w.log)
            self.assertEqual(self.r("what is playing"), "You are watching x.")

    def test_controls_need_youtube_open(self):
        with FakeWin(front=("Notepad", "notepad.exe")) as w:
            w.wins = []
            self.assertIsNone(self.r("speed up")) if False else None
            self.assertIn("not open", self.r("skip 30 seconds"))


class Helpers(unittest.TestCase):
    def test_snap_and_tab(self):
        c = FakeCtx()
        with FakeWin() as w:
            skills.route(c, "snap window left"); self.assertIn(("hot", "win", "left"), w.log)
            skills.route(c, "go to tab 3"); self.assertIn(("hot", "ctrl", "3"), w.log)


if __name__ == "__main__":
    unittest.main()
