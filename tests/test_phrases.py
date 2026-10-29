"""Regression table: many ways of saying the same thing must all reach the same action.
If a new fix breaks an older command, THIS file fails - run `python -m pytest tests -q` after every change."""
import itertools
import unittest
from unittest import mock

from jarvis import skills, winctl
from jarvis.app import Jarvis
from jarvis.config import Config

PREFIX = ["", "jarvis ", "jarvis, ", "hey jarvis ", "can you ", "could you please ", "jarvis can you ", "i said ",
          "jarvis i said ", "please ", "okay "]
VERBS = ["open", "open up", "launch", "start", "run"]
APPS = ["chrome", "google chrome", "the chrome browser", "vs code", "visual studio code", "settings", "youtube",
        "notepad", "calculator", "file explorer", "this pc", "my computer"]
TAIL = ["", " please", " for me", " now", " again", "."]


class PhraseTable(unittest.TestCase):
    def setUp(self):
        self.launched, self.keys = [], []
        patches = [mock.patch.object(skills, "launch", lambda t, fallback=False: self.launched.append(t) or True),
                   mock.patch.object(skills.browser, "open_url", lambda *a, **k: self.launched.append(a[0])),
                   mock.patch.object(winctl, "supported", lambda: True),
                   mock.patch.object(winctl, "hotkey", lambda *a: self.keys.append(a)),
                   mock.patch.object(skills.subprocess, "run",
                                     lambda *a, **k: type("R", (), {"returncode": 0})())]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.app = Jarvis(Config.load(), headless=True)
        self.app.quit_later = mock.Mock()
        mock.patch.object(type(self.app.brain), "llm_ready", new_callable=mock.PropertyMock, return_value=False).start()
        self.addCleanup(mock.patch.stopall)

    def test_open_phrases_never_fall_through(self):
        for p, v, a, t in itertools.product(PREFIX, VERBS, APPS, TAIL):
            phrase = "%s%s %s%s" % (p, v, a, t)
            self.launched.clear()
            r = skills.route(self.app, phrase)
            self.assertTrue(r and r.startswith("Opening"), "%r -> %r" % (phrase, r))
            self.assertTrue(self.launched, "%r launched nothing" % phrase)

    def test_open_targets(self):
        want = {"chrome": "chrome", "google chrome": "chrome", "vs code": "code", "visual studio code": "code",
                "settings": "ms-settings:", "notepad": "notepad.exe", "file explorer": "explorer.exe",
                "this pc": "shell:MyComputerFolder", "my computer": "shell:MyComputerFolder"}
        for name, target in want.items():
            self.launched.clear()
            skills.route(self.app, "Jarvis, I said open %s please." % name)
            self.assertEqual(self.launched[:1], [target], name)

    def test_close_settings_and_apps(self):
        for ph in ("close settings", "Jarvis, close settings.", "please close notepad", "close chrome now"):
            self.assertTrue(skills.route(self.app, ph).startswith("Closing"), ph)

    def test_stop_and_exit_phrases(self):
        for ph in ("Jarvis, stop.", "Jarvis stop", "stop", "I said stop", "Jarvis, stop please", "stop talking"):
            self.assertEqual(skills.control_of(ph), "stop", ph)
        for ph in ("Jarvis, shut down.", "Jarvis shut down", "Jarvis, I said shut down.", "Jarvis, I said you to be shut down.",
                   "Jarvis, shut down please", "Jarvis closed", "goodbye", "Closet.", "exit jarvis"):
            self.assertEqual(skills.control_of(ph), "exit", ph)

    def test_things_that_must_not_quit_or_stop(self):
        for ph in ("close", "close the door", "shut down the pc", "stop the music", "open file resume"):
            self.assertIsNone(skills.control_of(ph), ph)

    def test_new_tab_and_window(self):
        for ph in ("open a new tab", "Open a new tab.", "jarvis open new tab please", "new tab"):
            self.keys.clear()
            skills.route(self.app, ph)
            self.assertEqual(self.keys, [("ctrl", "t")], ph)
        self.keys.clear()
        skills.route(self.app, "open a new window")
        self.assertEqual(self.keys, [("ctrl", "n")])

    def test_file_search_still_works(self):
        with mock.patch.object(skills.pcinfo, "find_files", lambda q: []):
            self.assertIn("couldn't find a file", skills.route(self.app, "open file resume"))


if __name__ == "__main__":
    unittest.main()
