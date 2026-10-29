"""The behaviours that were missing: stop/close always work, commands are linked to the previous one,
the PC can be inspected, and unmatched commands never turn into encyclopedia answers."""
import os, sys, tempfile, threading, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import brain as brain_mod, dialog as dlg, pcinfo, skills
from jarvis.config import Config
from jarvis.dialog import Dialog
from jarvis.memory import Memory
from test_core import FakeCtx


def run(c, *phrases):
    """Route phrases one after another; returns (replies, urls opened in the browser)."""
    urls, out = [], []
    with mock.patch("webbrowser.open", side_effect=lambda u, *a, **k: urls.append(u)):
        for p in phrases:
            out.append(skills.route(c, p))
    return out, urls


class ControlWords(unittest.TestCase):
    def test_stop_variants(self):
        for s in ("stop", "Stop!", "Jarvis stop", "jarvis, stop it", "I said stop", "stop stop", "be quiet", "shut up",
                  "enough", "that's enough", "hold on", "wait", "never mind", "stop talking", "ok stop jarvis"):
            self.assertEqual(skills.control_of(s), "stop", s)

    def test_exit_variants(self):
        for s in ("Jarvis closed", "jarvis close", "Jarvis, close!", "travis closed", "goodbye", "Jarvis goodbye",
                  "exit", "quit jarvis", "close jarvis", "end session", "jarvis shut down", "jarvis turn off"):
            self.assertEqual(skills.control_of(s), "exit", s)

    def test_bare_close_needs_the_wake_word(self):
        self.assertIsNone(skills.control_of("close"))            # could be about a window
        self.assertIsNone(skills.control_of("close youtube"))
        self.assertIsNone(skills.control_of("close the door"))
        self.assertEqual(skills.control_of("hey jarvis closed"), "exit")

    def test_not_control(self):
        for s in ("open notepad", "stop the music", "play something", "what time is it", "waiter please"):
            self.assertIsNone(skills.control_of(s), s)

    def test_route_runs_them(self):
        c = FakeCtx()
        self.assertEqual(skills.route(c, "jarvis stop"), "")
        self.assertEqual(c.interrupted, 1)
        self.assertEqual(skills.route(c, "Jarvis closed"), "Goodbye. Shutting down.")
        self.assertEqual(c.quit, 2.2)

    def test_close_it_never_quits_jarvis(self):
        c = FakeCtx()
        run(c, "open notepad")
        skills.route(c, "close it")
        self.assertFalse(hasattr(c, "quit"))

    def test_stop_media(self):
        c = FakeCtx()
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "press") as pr:
            self.assertEqual(skills.route(c, "stop the music"), "Done.")
        pr.assert_called_once_with("playpause")


class Linking(unittest.TestCase):
    """The headline complaint: 'open youtube' then 'search karan ojla' must search YouTube."""

    def test_search_after_open_goes_to_the_open_site(self):
        c = FakeCtx()
        out, urls = run(c, "open youtube", "search karan ojla")
        self.assertEqual(out[0], "Opening youtube.")
        self.assertEqual(out[1], "Searching YouTube for karan ojla.")
        self.assertIn("youtube.com/results?search_query=karan%20ojla", urls[-1])

    def test_follow_up_verbs(self):
        for phrase in ("search for cats", "find cats", "look up cats", "play cats", "jarvis search cats please"):
            c = FakeCtx()
            _, urls = run(c, "open youtube", phrase)
            self.assertIn("youtube.com/results", urls[-1], phrase)

    def test_no_context_means_google(self):
        _, urls = run(FakeCtx(), "search karan ojla")
        self.assertIn("google.com/search?q=karan%20ojla", urls[-1])

    def test_follows_whatever_site_was_opened(self):
        for site, frag in (("github", "github.com/search"), ("amazon", "amazon.com/s?k="),
                           ("wikipedia", "wikipedia.org/w/index.php?search="), ("google maps", "google.com/maps/search"),
                           ("daraz", "daraz.pk/catalog")):
            c = FakeCtx()
            _, urls = run(c, "open " + site, "search shoes")
            self.assertIn(frag, urls[-1], site)

    def test_explicit_site_wins(self):
        c = FakeCtx()
        _, urls = run(c, "open youtube", "search python tutorial on google")
        self.assertIn("google.com/search", urls[-1])
        _, urls = run(c, "search lo-fi in spotify")
        self.assertIn("open.spotify.com/search/lo-fi", urls[-1])

    def test_context_expires(self):
        c = FakeCtx()
        run(c, "open youtube")
        c.dialog.focus.ts -= 10_000
        _, urls = run(c, "search cats")
        self.assertIn("google.com/search", urls[-1])

    def test_compound_command(self):
        c = FakeCtx()
        out, urls = run(c, "jarvis open youtube and search karan ojla")
        self.assertEqual(out[0], "Opening youtube. Searching YouTube for karan ojla.")
        self.assertEqual(len(urls), 2)

    def test_compound_does_not_split_free_text(self):
        self.assertEqual(dlg.split_compound("type tom and open jerry"), ["type tom and open jerry"])
        self.assertEqual(dlg.split_compound("search tom and jerry"), ["search tom and jerry"])
        self.assertEqual(dlg.split_compound("open notepad then type hello"), ["open notepad", "type hello"])
        self.assertEqual(dlg.split_compound("play despacito and open chrome"), ["play despacito", "open chrome"])

    def test_play_after_youtube(self):
        c = FakeCtx()
        _, urls = run(c, "open youtube", "play kesariya")
        self.assertIn("youtube.com/results?search_query=kesariya", urls[-1])

    def test_generic_play_is_play_pause_not_a_search(self):
        c = FakeCtx()
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "press") as pr, mock.patch("webbrowser.open") as wb:
            skills.route(c, "play music")
        pr.assert_called_with("playpause")
        wb.assert_not_called()

    def test_close_it_and_open_it_again(self):
        c = FakeCtx()
        run(c, "open notepad")
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills, "IS_WIN", True), mock.patch("subprocess.run") as sp:
            sp.return_value.returncode = 0
            r = skills.route(c, "close it")
        self.assertEqual(r, "Closing notepad.")
        self.assertEqual(sp.call_args[0][0][:3], ["taskkill", "/im", "notepad.exe"])   # graceful, no /f
        self.assertNotIn("/f", sp.call_args[0][0])
        with mock.patch.object(skills, "launch", return_value=True) as ln:
            self.assertEqual(skills.route(c, "open it again"), "Opening notepad.")
        ln.assert_called()

    def test_again(self):
        c = FakeCtx()
        self.assertEqual(skills.route(c, "again"), "There is nothing to repeat yet.")
        run(c, "open youtube", "search cats")
        _, urls = run(c, "do that again")
        self.assertIn("search_query=cats", urls[-1])

    def test_missing_slot_is_asked_and_remembered(self):
        c = FakeCtx()
        self.assertEqual(skills.route(c, "set a timer"), "For how long?")
        self.assertEqual(skills.route(c, "five minutes"), "Timer set for 5 minutes.")
        self.assertEqual(c.timers_added[-1][0], 300)
        out, urls = run(c, "open youtube", "search")
        self.assertEqual(out[1], "What should I search for?")
        out, urls = run(c, "arijit singh")
        self.assertIn("youtube.com/results?search_query=arijit%20singh", urls[-1])

    def test_slot_answer_can_be_a_new_command(self):
        c = FakeCtx()
        skills.route(c, "set a timer")
        with mock.patch.object(skills, "launch", return_value=True):
            self.assertEqual(skills.route(c, "open notepad"), "Opening notepad.")
        self.assertEqual(c.timers_added, [])

    def test_confirmation_yes_no(self):
        c = FakeCtx()
        with mock.patch.object(pcinfo, "power", return_value="Shutting down the computer.") as pw:
            q = skills.route(c, "shut down the pc")
            self.assertIn("Are you sure", q)
            pw.assert_not_called()
            self.assertEqual(skills.route(c, "no"), "Okay, cancelled.")
            skills.route(c, "restart the computer")
            self.assertEqual(skills.route(c, "yes"), "Shutting down the computer.")
            pw.assert_called_once_with("restart")
        self.assertIsNone(c.dialog.pending)

    def test_confirmation_expires_and_unrelated_speech_drops_it(self):
        c = FakeCtx()
        with mock.patch.object(pcinfo, "power") as pw:
            skills.route(c, "shut down the pc")
            skills.route(c, "what time is it")
            self.assertIsNone(skills.route(c, "yes"))            # question was dropped: 'yes' is just chat now
            pw.assert_not_called()

    def test_jarvis_shutdown_vs_pc_shutdown(self):
        c = FakeCtx()
        self.assertEqual(skills.route(c, "jarvis shut down"), "Goodbye. Shutting down.")
        c = FakeCtx()
        self.assertIn("Are you sure", skills.route(c, "shut down the computer"))
        self.assertFalse(hasattr(c, "quit"))


class ScreenAwareness(unittest.TestCase):
    def ctx(self, title, exe):
        c = FakeCtx()
        c.dialog = Dialog(600, probe=lambda: (title, exe))
        return c

    def test_search_follows_the_page_you_are_actually_on(self):
        c = self.ctx("Karan Aujla - YouTube - Google Chrome", "chrome.exe")     # opened by hand, not by Jarvis
        _, urls = run(c, "search sidhu moose wala")
        self.assertIn("youtube.com/results?search_query=sidhu%20moose%20wala", urls[-1])

    def test_foreground_amazon_beats_older_youtube(self):
        c = self.ctx("Shoes - Amazon.com - Google Chrome", "chrome.exe")
        c.dialog.set_focus("site", "youtube")
        c.dialog.focus.ts -= 60
        _, urls = run(c, "search running shoes")
        self.assertIn("amazon.com/s?k=", urls[-1])

    def test_just_opened_site_wins_over_stale_foreground(self):
        c = self.ctx("main.py - Visual Studio Code", "Code.exe")
        _, urls = run(c, "open youtube", "search cats")
        self.assertIn("youtube.com/results", urls[-1])

    def test_unrelated_foreground_app_keeps_last_searched_site(self):
        c = self.ctx("main.py - Visual Studio Code", "Code.exe")
        run(c, "open youtube")
        c.dialog.focus.ts -= 60
        _, urls = run(c, "search cats")
        self.assertIn("youtube.com/results", urls[-1])

    def test_jarvis_own_window_is_ignored(self):
        self.assertIsNone(dlg.infer_focus("J.A.R.V.I.S", "python.exe"))

    def test_infer_focus(self):
        f = dlg.infer_focus("Inbox (3) - zaeem@gmail.com - Gmail - Google Chrome", "chrome.exe")
        self.assertEqual((f.kind, f.key), ("site", "gmail"))
        self.assertEqual(dlg.infer_focus("Untitled - Notepad", "notepad.exe").key, "notepad")
        self.assertEqual(dlg.infer_focus("New Tab - Google Chrome", "chrome.exe").key, "browser")

    def test_fullscreen_acts_on_the_page_in_front(self):
        c = self.ctx("Video - YouTube - Google Chrome", "chrome.exe")
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "press") as pr:
            skills.route(c, "full screen")
        pr.assert_called_once_with("f")
        c = FakeCtx()                                            # nothing else in front: it is the HUD's own fullscreen
        skills.route(c, "full screen")
        self.assertIn(("fullscreen", True), [e[:2] for e in c.posted])


class Mail(unittest.TestCase):
    def test_compose_after_open_mail(self):
        c = FakeCtx()
        out, urls = run(c, "open mail", "compose a new mail")
        self.assertIn("mail.google.com", urls[0])
        self.assertEqual(out[1], "Opening a new email.")
        self.assertIn("view=cm", urls[1])

    def test_compose_phrasings(self):
        for p in ("compose a new mail", "compose new email", "write an email", "new mail", "create a new email",
                  "draft an email", "open a new mail", "jarvis compose a new mail please", "start a new email"):
            _, urls = run(FakeCtx(), p)
            self.assertEqual(len(urls), 1, p)
            self.assertIn("view=cm", urls[0], p)

    def test_compose_never_goes_to_the_ai(self):
        c = FakeCtx(key="x")                                     # AI brain is on
        self.assertIsNotNone(skills.route(c, "compose a new mail"))

    def test_fields(self):
        _, urls = run(FakeCtx(), "write an email to ali at gmail dot com subject project update saying i will be late")
        u = urls[0]
        self.assertIn("to=ali%40gmail.com", u)
        self.assertIn("su=project%20update", u)
        self.assertIn("body=i%20will%20be%20late", u)

    def test_contacts(self):
        c = FakeCtx()
        self.assertIn("Saved", skills.route(c, "save contact ali as ali at example dot com"))
        _, urls = run(c, "compose an email to ali")
        self.assertIn("to=ali%40example.com", urls[0])
        out, urls = run(c, "compose an email to bilal")
        self.assertIn("don't have an address for bilal", out[0])

    def test_mail_clients(self):
        c = FakeCtx()
        c.cfg.mail = "outlook"
        _, urls = run(c, "compose a new mail")
        self.assertIn("outlook.office.com", urls[0])
        c.cfg.mail = "default"
        _, urls = run(c, "compose a new mail")
        self.assertTrue(urls[0].startswith("mailto:"))

    def test_send_asks_first(self):
        c = FakeCtx()
        run(c, "compose a new mail")
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "hotkey") as hk:
            self.assertIn("Send the email now", skills.route(c, "send it"))
            hk.assert_not_called()
            self.assertEqual(skills.route(c, "yes"), "Sent.")
            hk.assert_called_once_with("ctrl", "enter")

    def test_message_to_a_person_is_not_an_email(self):
        _, urls = run(FakeCtx(), "send a message to ali on whatsapp")
        self.assertEqual(urls, [])


class PCAccess(unittest.TestCase):
    def setUp(self):
        self.c = FakeCtx()
        self.apps = mock.patch.multiple(skills.APPS, ready=True, start_names=["chrome", "notepad", "spotify", "vlc"],
                                        programs=["Google Chrome", "Notepad++", "VLC media player", "Python 3.13"])
        self.apps.start()

    def tearDown(self):
        self.apps.stop()

    def test_count_apps_phrasings(self):
        for p in ("how many apps are installed", "how many applications are installed on my pc",
                  "how many programs do i have installed", "jarvis how many apps are installed in this pc",
                  "number of installed apps", "count my apps"):
            r = skills.route(FakeCtx(), p)
            self.assertIn("4 apps in your Start menu", r, p)
            self.assertIn("4 installed programs", r, p)

    def test_count_then_yes_lists_them(self):
        r = skills.route(self.c, "how many apps are installed")
        self.assertIn("Want me to list them", r)
        r = skills.route(self.c, "yes")
        self.assertIn("Chrome", r)
        self.assertTrue(any("Notepad" in e[2] for e in self.c.posted if e[0] == "log"))

    def test_list_apps(self):
        self.assertIn("Spotify", skills.route(self.c, "list my installed apps"))

    def test_is_installed(self):
        self.assertIn("Yes, vlc is installed", skills.route(self.c, "is vlc installed"))
        self.assertIn("Shall I open it", skills.route(self.c, "do i have spotify installed on my pc"))
        self.assertIn("No, I can't find photoshop", skills.route(self.c, "is photoshop installed"))

    def test_running_apps(self):
        wins = [("chrome", "YouTube - Google Chrome"), ("Code", "main.py"), ("python", "J.A.R.V.I.S")]
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(pcinfo, "running_windows", return_value=wins):
            for p in ("what apps are running", "what is open", "which programs are open", "show open windows",
                      "how many apps are open"):
                r = skills.route(self.c, p)
                self.assertEqual(r, "You have 2 apps open: chrome, code.", p)

    def test_running_is_not_confused_with_installed(self):
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(pcinfo, "running_windows", return_value=[("chrome", "x")]):
            self.assertIn("apps open", skills.route(self.c, "how many apps are open"))
        self.assertIn("Start menu", skills.route(self.c, "how many apps are installed"))

    def test_disk_ip_uptime(self):
        with mock.patch.object(pcinfo, "disk_info", return_value=(500.0, 125.0, 375.0)):
            self.assertIn("375 gigabytes free out of 500", skills.route(self.c, "how much storage is left"))
            self.assertIn("25 percent full", skills.route(self.c, "how much disk space do i have"))
        with mock.patch.object(pcinfo, "local_ip", return_value="192.168.1.7"):
            self.assertIn("192 dot 168 dot 1 dot 7", skills.route(self.c, "what is my ip address"))
        with mock.patch.object(pcinfo, "uptime_secs", return_value=3 * 3600 + 25 * 60):
            self.assertIn("3 hours 25 minutes", skills.route(self.c, "how long has my pc been on"))

    def test_open_folder(self):
        with mock.patch.object(skills, "launch", return_value=True) as ln, \
             mock.patch("os.path.isdir", return_value=True):
            self.assertEqual(skills.route(self.c, "open downloads folder"), "Opening your downloads folder.")
            self.assertEqual(skills.route(self.c, "open my documents"), "Opening your documents folder.")
        self.assertEqual(ln.call_count, 2)

    def test_store_apps_open_by_name(self):
        skills.APPS.index = {"photos": "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"}
        with mock.patch.object(skills, "launch", return_value=True) as ln:
            self.assertEqual(skills.route(self.c, "open photos"), "Opening photos.")
        self.assertTrue(ln.call_args[0][0].startswith("shell:AppsFolder"))

    def test_volume_set(self):
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "press") as pr:
            self.assertEqual(skills.route(self.c, "set volume to 40"), "Volume set to 40 percent.")
        names = [a[0][0] for a in pr.call_args_list]
        self.assertEqual((names.count("volumedown"), names.count("volumeup")), (50, 20))

    def test_brightness(self):
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(pcinfo, "get_brightness", return_value=50), \
             mock.patch.object(pcinfo, "set_brightness", return_value=True) as sb:
            self.assertEqual(skills.route(self.c, "increase the brightness"), "Brightness set to 70 percent.")
            skills.route(self.c, "set brightness to 30")
        self.assertEqual([a[0][0] for a in sb.call_args_list], [70, 30])

    def test_switch_window(self):
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(pcinfo, "focus_window", return_value=True) as fw:
            self.assertEqual(skills.route(self.c, "switch to word"), "Switching to word.")
        fw.assert_called_with("word")

    def test_navigation_shortcuts(self):
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "hotkey") as hk, mock.patch.object(skills.winctl, "press") as pr:
            skills.route(self.c, "go back")
            skills.route(self.c, "zoom in")
            skills.route(self.c, "scroll down")
            skills.route(self.c, "press the f key")
        self.assertEqual([a[0] for a in hk.call_args_list], [("alt", "left"), ("ctrl", "plus"), ("pagedown",)])
        pr.assert_called_with("f")

    def test_force_close_vs_graceful(self):
        with mock.patch.object(skills, "IS_WIN", True), mock.patch("subprocess.run") as sp:
            sp.return_value.returncode = 0
            skills.route(self.c, "close chrome")
            self.assertNotIn("/f", sp.call_args[0][0])
            skills.route(self.c, "force close chrome")
            self.assertIn("/f", sp.call_args[0][0])

    def test_closing_a_website_closes_the_tab_not_a_process(self):
        c = FakeCtx()
        c.dialog = Dialog(600, probe=lambda: ("Home - YouTube - Google Chrome", "chrome.exe"))
        with mock.patch.object(skills.winctl, "supported", return_value=True), \
             mock.patch.object(skills.winctl, "hotkey") as hk:
            self.assertEqual(skills.route(c, "close youtube"), "Closed the youtube tab.")
        hk.assert_called_once_with("ctrl", "w")

    def test_find_file(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "Resume 2026 final.pdf"), "w").close()
        self.assertEqual([os.path.basename(x) for x in pcinfo.find_files("resume pdf", roots=[d])],
                         ["Resume 2026 final.pdf"])
        with mock.patch.object(pcinfo, "find_files", return_value=[os.path.join(d, "Resume 2026 final.pdf")]), \
             mock.patch.object(skills, "launch", return_value=True) as ln:
            self.assertEqual(skills.route(self.c, "open file resume"), "Opening Resume 2026 final.pdf.")
        ln.assert_called_once()

    def test_background_mode(self):
        self.assertIn("Going to the background", skills.route(self.c, "go to background"))
        self.assertTrue(self.c.hidden)
        self.assertEqual(skills.route(self.c, "jarvis show yourself"), "Here I am.")
        self.assertFalse(self.c.hidden)


class Planner(unittest.TestCase):
    """Commands no rule matches are translated by the language model using the context - never answered as facts."""

    def ctx_with_ai(self, plan):
        c = FakeCtx(key="K")
        c.brain.plan = mock.Mock(return_value=plan)
        return c

    def test_planner_rewrites_and_runs(self):
        c = self.ctx_with_ai({"kind": "command", "command": "search karan aujla on youtube"})
        out, urls = run(c, "look karan ojla up over there")
        self.assertEqual(out[0], "Searching YouTube for karan aujla.")
        self.assertIn("karan%20aujla", urls[0])
        self.assertIn("No recent", c.brain.plan.call_args[0][1])

    def test_planner_gets_the_conversation(self):
        c = self.ctx_with_ai({"kind": "command", "command": "open notepad"})
        run(c, "open youtube", "search cats")
        with mock.patch.object(skills, "launch", return_value=True):
            skills.route(c, "pull up the text editor thing")
        desc = c.brain.plan.call_args[0][1]
        self.assertIn("youtube", desc)
        self.assertIn("search cats", desc)

    def test_question_goes_to_brain(self):
        c = self.ctx_with_ai({"kind": "question", "command": ""})
        self.assertIsNone(skills.route(c, "find out who won the world cup"))

    def test_unknown_command_is_not_answered_with_facts(self):
        c = self.ctx_with_ai({"kind": "command", "command": "transform sofa"})
        r = skills.route(c, "turn the sofa into a rocket")
        self.assertIn(r, skills._CANT)

    def test_plain_questions_skip_the_planner(self):
        c = self.ctx_with_ai({"kind": "command", "command": "x"})
        for q in ("who is the prime minister of japan", "what is photosynthesis", "why is the sky blue"):
            self.assertIsNone(skills.route(c, q))
        c.brain.plan.assert_not_called()

    def test_without_ai_unmatched_commands_get_a_clear_answer(self):
        c = FakeCtx()
        r = skills.route(c, "minimize everything and restart")
        self.assertIsNotNone(r)
        self.assertIsNone(skills.route(c, "write me a poem about rain"))     # creative: still the brain's job
        self.assertIsNone(skills.route(c, "what is photosynthesis"))

    def test_plan_parsing(self):
        mk = lambda t: {"candidates": [{"content": {"parts": [{"text": t}]}}]}
        self.assertEqual(brain_mod.Brain.parse_plan(mk('{"kind":"command","command":"open notepad"}')),
                         {"kind": "command", "command": "open notepad"})
        self.assertEqual(brain_mod.Brain.parse_plan(mk('```json\n{"kind":"chat","command":null}\n```')),
                         {"kind": "chat", "command": ""})
        self.assertIsNone(brain_mod.Brain.parse_plan(mk("not json")))
        self.assertIsNone(brain_mod.Brain.parse_plan(mk('{"kind":"weird"}')))
        self.assertIsNone(brain_mod.Brain.parse_plan({}))

    def test_plan_request_shape_and_failure_is_soft(self):
        b = brain_mod.Brain(Config(xai_key="K", grok_model="grok-test"), Memory(tempfile.mkdtemp()))
        ok = {"choices": [{"message": {"content": 'Sure! {"kind":"command","command":"open notepad"}'}}]}
        with mock.patch.object(brain_mod.net, "post_json", return_value=ok) as pj:
            self.assertEqual(b.plan("open the editor", "ctx")["command"], "open notepad")
        body = pj.call_args[0][1]
        self.assertEqual(body["temperature"], 0)
        self.assertIn("ctx", body["messages"][1]["content"])
        with mock.patch.object(brain_mod.net, "post_json", side_effect=brain_mod.net.NetError("down", 503)):
            self.assertIsNone(b.plan("open the editor", "ctx"))
        with mock.patch.object(brain_mod.net, "post_json") as pj:        # paused after a failure: no hammering
            self.assertIsNone(b.plan("open the editor", "ctx"))
        pj.assert_not_called()

    def test_ai_prompt_knows_the_context_and_forbids_encyclopedia_for_commands(self):
        b = brain_mod.Brain(Config(xai_key="K"), Memory(tempfile.mkdtemp()))
        b._context = "Last thing opened: youtube (site)."
        p = b._system_prompt()
        self.assertIn("youtube", p)
        self.assertIn("according to Wikipedia", p)


class AppLevel(unittest.TestCase):
    """The controller: stop must work while speaking and while a slow answer is being thought up."""

    def setUp(self):
        from jarvis.app import Jarvis
        self.app = Jarvis(Config(tts_engine="off", wake_enabled=True), headless=True)
        self.app.speaker = mock.Mock()
        self.app.speaker.speaking = threading.Event()
        self.app.hud_post = lambda *a: None
        self.app.quit_later = mock.Mock()

    def test_stop_while_speaking_is_handled_immediately_without_wake_word(self):
        self.app.speaker.speaking.set()
        self.app.work_q.put("something queued")
        self.app.on_heard("stop")
        self.app.speaker.stop.assert_called_once()
        self.assertTrue(self.app.work_q.empty())
        self.assertGreater(self.app.epoch, 0)
        self.assertGreater(self.app.awake_until, time.time())          # and he is listening for the next thing

    def test_stop_while_idle_in_standby_is_ignored(self):
        self.app.on_heard("stop")
        self.app.speaker.stop.assert_not_called()

    def test_stop_while_busy_thinking(self):
        self.app._busy.set()
        self.app.on_heard("jarvis stop")
        self.app.speaker.stop.assert_called_once()

    def test_jarvis_closed_quits_even_while_speaking(self):
        self.app.speaker.speaking.set()
        self.app.on_heard("Jarvis closed")
        self.app.quit_later.assert_called_once()
        self.app.speaker.stop.assert_called()

    def test_bare_close_does_not_quit_jarvis(self):
        self.app.awake_until = time.time() + 5
        self.app.on_heard("close")
        self.app.quit_later.assert_not_called()

    def test_barge_in_accepts_only_control_words(self):
        self.assertTrue(self.app.on_barge("stop"))
        self.assertFalse(self.app.on_barge("opening notepad for you"))          # Jarvis's own voice, heard back
        self.assertFalse(self.app.on_barge("close the door"))
        self.assertTrue(self.app.on_barge("jarvis closed"))

    def test_typed_stop_does_not_wait_in_the_queue(self):
        self.app.submit("stop", typed=True)
        self.app.speaker.stop.assert_called_once()
        self.assertTrue(self.app.work_q.empty())

    def test_reply_from_an_interrupted_request_is_dropped(self):
        replies = []
        self.app.respond = lambda r, s=None: replies.append(r)

        def slow_route(ctx, text):
            self.app.interrupt()                                    # user says stop while the answer is being made
            return "this answer arrives too late"
        with mock.patch.object(skills, "route", slow_route):
            self.app._process("tell me a story")
        self.assertEqual(replies, [])

    def test_normal_reply_still_spoken(self):
        replies = []
        self.app.respond = lambda r, s=None: replies.append(r)
        self.app._process("what time is it")
        self.assertTrue(replies and replies[0].startswith("It is"))

    def test_interrupt_keeps_the_shutdown_marker(self):
        self.app.work_q.put("a"); self.app.work_q.put(None)
        self.app.interrupt()
        self.assertIsNone(self.app.work_q.get_nowait())

    def test_mic_stays_open_while_speaking_unless_disabled(self):
        self.app.speaker.speaking.set()
        self.assertFalse(self.app._mic_blocked())
        self.app.cfg.barge_in = False
        self.assertTrue(self.app._mic_blocked())

    def test_window_close_hides_instead_of_quitting(self):
        posted = []
        self.app.hud_post = lambda *a: posted.append(a)
        self.app.quit = mock.Mock()
        self.app.on_window_close()
        self.assertIn(("hide",), posted)
        self.app.quit.assert_not_called()
        self.app.cfg.close_to_background = False
        self.app.on_window_close()
        self.app.quit.assert_called_once()


class Config_(unittest.TestCase):
    def test_new_settings_load_from_env(self):
        env = {"XAI_API_KEY": "x", "OPENROUTER_API_KEY": "o", "JARVIS_AI": "OpenRouter", "JARVIS_BARGE_IN": "false", "JARVIS_BARGE_SENS": "3.5", "JARVIS_BACKGROUND": "true",
               "JARVIS_MAIL": "Outlook", "JARVIS_CONTEXT_SECS": "120"}
        with mock.patch.dict(os.environ, env), mock.patch("jarvis.config.load_env"):
            c = Config.load()
        self.assertEqual((c.barge_in, c.barge_sens, c.background, c.mail, c.context_secs),
                         (False, 3.5, True, "outlook", 120.0))
        self.assertEqual((c.xai_key, c.openrouter_key, c.ai_provider), ("x", "o", "openrouter"))


if __name__ == "__main__":
    unittest.main()
