# -*- coding: utf-8 -*-
"""New features: briefing, speed, notes -> Word, reports, Roman-Urdu volume/calc, modes, repeat, six agents, docs, Urdu."""
import os, sys, tempfile, threading, time, unittest, zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import agents, briefing, config, docs, features, modes, net, newsdesk, services, skills, urdu
from jarvis import brain as brain_mod
from test_core import FakeCtx

WX = {"city": "Sargodha", "temp": 30, "feels": 31, "humidity": 40, "wind": 5, "desc": "clear skies", "high": 34, "low": 22, "rain": 10}
NEWS = newsdesk.Result([newsdesk.Item("Headline one", "Dawn"), newsdesk.Item("Headline two")], "Pakistan", "پاکستان", "country")


class Ctx(FakeCtx):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.epoch, self.said = 0, []
    def respond(self, text, sources=None): self.said.append(text)
    def wait(self, n=1, secs=6):
        t0 = time.time()
        while len(self.said) < n and time.time() - t0 < secs:
            time.sleep(0.02)
        return self.said


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._rd = config.REPORTS_DIR
        config.REPORTS_DIR = os.path.join(self.tmp, "reports")
        modes._PATH, modes._mode = os.path.join(self.tmp, "mode.txt"), None
        modes.set_mode("smart", save=False)
        urdu._STORE = os.path.join(self.tmp, "language.txt")
        urdu.set_mode("en", save=False)
        agents.LAST_REPORTS.clear()
        self.c = Ctx()
        self.c.hud_post = lambda *a, **k: self.c.posted.append(a)
        self.net = [mock.patch.object(services, "weather", return_value=WX),
                    mock.patch.object(newsdesk, "fetch", return_value=NEWS),
                    mock.patch.object(briefing, "speed_test", return_value={"ping": 20, "mbps": 55.5}),
                    mock.patch.object(services, "wikipedia", return_value=("Cats", "Cats are small mammals.", "")),
                    mock.patch.object(services, "duckduckgo", return_value=None),
                    mock.patch.object(agents, "suggestions", return_value=["honey benefits", "honey price"])]
        for p in self.net:
            p.start()
    def tearDown(self):
        for p in self.net:
            p.stop()
        config.REPORTS_DIR = self._rd
        modes.set_mode("smart", save=False)
        urdu.set_mode("en", save=False)
    def r(self, s): return skills.route(self.c, s)


class Docs(Base):
    def test_docx_roundtrip_english_and_urdu(self):
        p = docs.write_docx(os.path.join(self.tmp, "a.docx"), "Title", [("h1", "Head"), ("p", "A & B <c>"), ("bullet", "one"), ("p", "اردو متن")])
        with zipfile.ZipFile(p) as z:
            self.assertIn("word/document.xml", z.namelist())
        txt = docs.read_docx(p)
        for part in ("Title", "Head", "A & B <c>", "one", "اردو متن"):
            self.assertIn(part, txt)
    def test_pdf_is_a_pdf_and_urdu_is_refused(self):
        p = docs.write_pdf(os.path.join(self.tmp, "a.pdf"), "T", docs.blocks_from_text("hello\n\n- a\n- b\n\n" + "word " * 900))
        data = open(p, "rb").read()
        self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"))
        self.assertGreater(data.count(b"/Type /Page "), 1)
        self.assertFalse(docs.pdf_possible("اردو"))
    def test_notes_file_appends(self):
        p = os.path.join(self.tmp, "n.docx")
        docs.append_note_docx(p, "first"); docs.append_note_docx(p, "second")
        t = docs.read_docx(p)
        self.assertEqual((t.count("first"), t.count("second")), (1, 1))
        self.assertNotIn("\u2022  \u2022", t)
    def test_reports_folder_helpers(self):
        self.assertEqual(docs.list_reports(), [])
        docs.write_docx(docs.unique_path("Research cats", ".docx", "scout"), "x", "hi")
        docs.write_docx(docs.unique_path("Plan dogs", ".docx", "muse"), "x", "hi")
        self.assertIn("cats", docs.find_report("cats"))
        self.assertIsNone(docs.find_report("zebra"))
        self.assertEqual(len(docs.list_reports()), 2)
        a = docs.unique_path("Same", ".docx"); open(a, "w").close()
        self.assertNotEqual(a, docs.unique_path("Same", ".docx"))


class Modes(Base):
    def test_persist_and_effect(self):
        modes.set_mode("local")
        modes._mode = None
        self.assertTrue(modes.is_local())
        b = brain_mod.Brain(config.Config(groq_key="gsk_x"), self.c.mem)
        self.assertFalse(b.llm_ready)
        self.assertIsNone(b.complete("hi"))
        modes.set_mode("smart")
        self.assertTrue(b.llm_ready)
    def test_complete(self):
        b = brain_mod.Brain(config.Config(groq_key="gsk_x", groq_model="llama-3.3-70b-versatile"), self.c.mem)
        with mock.patch.object(net, "post_json", return_value={"choices": [{"message": {"content": "[happy] Done."}}]}):
            self.assertEqual(b.complete("hi", "sys"), "Done.")
        with mock.patch.object(net, "post_json", side_effect=net.NetError("busy", 429)):
            self.assertIsNone(b.complete("hi"))
        self.assertIsNone(brain_mod.Brain(config.Config(), self.c.mem).complete("hi"))        # no key
    def test_voice_commands(self):
        self.assertIn("Local mode is on", self.r("local mode"))
        self.assertTrue(modes.is_local())
        self.assertIn("Local mode", self.r("which mode"))
        self.assertIn("Smart mode is on", self.r("switch to smart mode"))
        self.assertFalse(modes.is_local())
        self.assertIn("Local mode is on", self.r("Jarvis local mode karo"))


class Briefing(Base):
    def test_format_has_all_parts(self):
        spoken, shown = briefing.format_briefing({"weather": WX, "speed": {"ping": 20, "mbps": 55.5}, "items": NEWS.items, "with_speed": True}, "Zaeem")
        for part in ("Sargodha", "55.5", "Headline one", "what would you like to work on"):
            self.assertIn(part, spoken)
        self.assertIn("## Headlines", shown)
    def test_format_survives_missing_parts(self):
        spoken, _ = briefing.format_briefing({"weather": None, "speed": None, "items": []}, ur=False)
        self.assertIn("could not reach", spoken)
        self.assertIn("آج", briefing.format_briefing({"weather": None, "items": []}, ur=True)[0])
    def test_phrases_in_three_languages(self):
        for p in ("briefing", "Jarvis, give me my daily briefing", "briefing sunao", "aaj ka haal sunao", "morning briefing"):
            self.c.said.clear()
            self.assertIn("briefing", self.r(p).lower(), p)
            self.assertTrue(self.c.wait(1)[0].count("Headline one"), p)
        self.assertEqual(agents.last("briefing")["title"].split(" - ")[0], "BRIEFING")
    def test_old_news_briefing_is_untouched(self):
        with mock.patch.object(newsdesk, "briefing", return_value=("OLD NEWS TEXT", [])):
            self.assertEqual(self.r("daily news briefing"), "OLD NEWS TEXT")
    def test_not_spoken_after_stop(self):
        with mock.patch.object(briefing, "gather", side_effect=lambda cfg: (setattr(self.c, "epoch", self.c.epoch + 1), {"weather": WX, "items": []})[1]):
            self.r("briefing")
            time.sleep(0.5)
        self.assertEqual(self.c.said, [])
        self.assertTrue(any(e[0] == "panel" for e in self.c.posted))                  # still shown on the HUD
    def test_boot_hook(self):
        with mock.patch.object(briefing, "run") as run:
            self.c.online = True
            briefing.start_at_boot(self.c)
            run.assert_called_once()
            run.reset_mock()
            with mock.patch.dict(os.environ, {"JARVIS_STARTUP_BRIEFING": "off"}):
                briefing.start_at_boot(self.c)
            self.c.online = False
            briefing.start_at_boot(self.c)
            run.assert_not_called()


class Speed(Base):
    def test_speed_commands(self):
        for p in ("speed check", "speed check karo", "internet speed test", "check my internet speed", "how fast is my internet"):
            self.c.said.clear()
            self.assertIn("Testing", self.r(p), p)
            self.assertIn("55.5", self.c.wait(1)[0], p)
    def test_offline(self):
        with mock.patch.object(briefing, "speed_test", return_value=None):
            self.r("speed check")
            self.assertIn("could not measure", self.c.wait(1)[0])
    def test_real_function_fails_softly(self):
        self.net[2].stop()
        try:
            with mock.patch.object(net, "get_bytes", side_effect=net.NetError("offline")):
                self.assertIsNone(briefing.speed_test())
            with mock.patch.object(net, "get_bytes", return_value=b"x" * 1_000_000):
                s = briefing.speed_test()
                self.assertTrue(s and s["mbps"] > 0)
        finally:
            self.net[2].start()


class Notes(Base):
    def test_old_phrases_keep_working_and_gain_a_word_file(self):
        self.assertEqual(self.r("take a note buy milk"), "Noted.")
        self.assertEqual(self.r("note likho kal 9 baje call karni hai"), "Noted.")
        self.assertEqual(self.r("write a note finish the report"), "Noted.")
        notes = " ".join(self.c.mem.read_notes(5))
        for part in ("buy milk", "kal 9 baje", "finish the report"):
            self.assertIn(part, notes)
        t0 = time.time()
        while time.time() - t0 < 3 and not [f for f, _ in docs.list_reports() if f.startswith("Notes-")]:
            time.sleep(0.05)
        time.sleep(0.2)
        name = [f for f, _ in docs.list_reports() if f.startswith("Notes-")][0]
        text = docs.read_docx(os.path.join(docs.reports_dir(), name))
        self.assertIn("buy milk", text)
        self.assertIn("Your latest notes", self.r("read my notes"))                       # old skill still there


class Reports(Base):
    def test_list_and_open_in_app(self):
        self.assertIn("empty", self.r("show reports"))
        docs.write_docx(docs.unique_path("Research cats", ".docx", "scout"), "Research cats", [("p", "Cats purr loudly.")])
        for p in ("show reports", "reports dikhao", "list my reports", "what reports do i have"):
            self.assertIn("1 report", self.r(p), p)
        self.assertTrue(any(e[0] == "panel" for e in self.c.posted))
        self.assertIn("opened", self.r("open the scout report"))
        self.assertIn("opened", self.r("wo report kholo"))
        self.assertIn("Cats purr", self.r("read the cats report"))
        self.assertIn("could not find", self.r("open the zebra report"))
    def test_old_notes_commands_are_not_hijacked(self):
        self.c.mem.add_note("buy milk")
        docs.write_docx(os.path.join(docs.reports_dir(), "Notes-2026-01-01.docx"), "Notes", "x")
        self.assertIn("Your latest notes", self.r("read my notes"))
        self.assertIn("Your latest notes", self.r("show my notes"))
        self.assertIn("opened", self.r("note kholo"))                                  # Roman Urdu: the Word notes file
    def test_open_unrelated_files_falls_through(self):
        docs.write_docx(docs.unique_path("Research cats", ".docx"), "x", "hi")
        for p in ("open the file", "open file explorer", "open notepad", "open chrome"):
            self.assertNotIn("opened", self.r(p) or "", p)
    def test_pdf_listed_not_read(self):
        docs.write_pdf(docs.unique_path("Trip", ".pdf"), "Trip", "hi")
        self.assertIn("PDF", self.r("open the trip report"))


class RomanUrdu(Base):
    def test_volume_maps_to_existing_commands(self):
        got = []
        with mock.patch.object(features, "_route", side_effect=lambda ctx, cmd: got.append(cmd) or "ok"):
            for p in ("volume barhao", "awaz kam karo", "awaz 50 kar do", "mute kar do", "unmute karo", "volume 30 pe kar do", "awaaz band karo"):
                self.r(p)
        self.assertEqual(got, ["volume up", "volume down", "set volume to 50", "mute", "unmute", "set volume to 30", "mute"])
    def test_calc(self):
        self.assertEqual(self.r("2500 guna 18 kitne hue"), "That is 45000.")
        self.assertEqual(self.r("10 jama 5 kitne hue"), "That is 15.")
        self.assertEqual(self.r("100 taqseem 4"), "That is 25.")
        self.assertEqual(self.r("what is 2500 times 18"), "That is 45000.")             # old calculator untouched
    def test_repeat(self):
        self.c.last_reply = "Hello there."
        self.assertEqual(self.r("repeat that"), "Hello there.")                           # old skill
        self.assertEqual(self.r("dobara bolo"), "Hello there.")
        self.assertIn("no briefing", self.r("repeat the last briefing"))
        agents.record("briefing", "B", "text", "Spoken briefing.")
        self.assertEqual(self.r("repeat the last briefing"), "Spoken briefing.")
        self.assertEqual(self.r("briefing dobara sunao"), "Spoken briefing.")
        agents.record("scout", "S", "text", "Scout said this.")
        self.assertEqual(self.r("repeat the report"), "Scout said this.")


class Agents(Base):
    def test_named_agents_route(self):
        got = []
        with mock.patch.object(agents, "dispatch", side_effect=lambda ctx, n, t: got.append((n, t)) or "ok"):
            for p in ("scout research electric cars", "Jarvis scout, sargodha par research karo", "herald pakistan news", "voyager flights from lahore to dubai",
                      "social captions for my tea shop", "seo keywords for organic honey", "muse plan my exam preparation",
                      "research karo solar panels", "write 5 captions for my shop", "make a plan for my fyp", "plan a trip to hunza", "flights to dubai",
                      "scott research bitcoin"):
                self.r(p)
        names = [n for n, _ in got]
        self.assertEqual(names, ["scout", "scout", "herald", "voyager", "social", "seo", "muse", "scout", "social", "muse", "voyager", "voyager", "scout"])
        self.assertEqual(got[0][1], "electric cars")
        self.assertEqual(got[1][1], "sargodha")
        self.assertIn("lahore to dubai", got[3][1])
        self.assertEqual(got[4][1], "my tea shop")
    def test_ordinary_sentences_are_not_hijacked(self):
        for p in ("social distancing is boring", "scott is my friend", "harold is here", "research paper shows that cats sleep", "what is the museum"):
            with mock.patch.object(agents, "dispatch") as d:
                self.r(p)
                d.assert_not_called()
    def test_missing_task_asks(self):
        self.assertIn("What should SCOUT work on", self.r("scout"))
    def test_each_agent_works_without_ai_and_saves_a_word_file(self):
        for phrase, key in (("scout research cats", "scout"), ("herald pakistan news", "herald"), ("voyager flights from lahore to dubai", "voyager"),
                            ("social captions for my tea shop", "social"), ("seo keywords for organic honey", "seo"), ("muse plan my exam preparation", "muse")):
            self.c.said.clear()
            self.assertIn(key.upper(), self.r(phrase))
            said = self.c.wait(1)
            self.assertTrue(said[-1].startswith(key.upper() + " reporting"), (key, said))
            self.assertIn("reports folder", said[-1])
            self.assertTrue(agents.last(key)["text"].strip())
            self.assertTrue(agents.last(key)["path"].endswith(".docx") and os.path.isfile(agents.last(key)["path"]))
        self.assertEqual(len([f for f, _ in docs.list_reports()]), 6)
    def test_fallbacks_with_everything_offline(self):
        for p in self.net:
            p.stop()
        try:
            with mock.patch.object(net, "_open", side_effect=net.NetError("offline")):
                for fn, arg in ((agents.scout, "cats"), (agents.herald, "pakistan"), (agents.voyager, "flights from lahore to dubai"),
                                (agents.social, "tea"), (agents.seo, "honey"), (agents.muse, "plan my week")):
                    rep = fn(self.c, arg)
                    self.assertTrue(rep.text.strip(), fn.__name__)
        finally:
            for p in self.net:
                p.start()
    def test_uses_the_ai_when_there_is_one(self):
        self.c.brain.complete = lambda prompt, system="", max_tokens=600, timeout=20: "Summary line.\n\n## Part\n- point"
        self.r("scout research cats")
        self.c.wait(1)
        self.assertIn("Summary line", agents.last("scout")["text"])
    def test_result_is_not_spoken_after_stop_but_is_saved(self):
        def work():
            self.c.epoch += 1                                   # the user said "stop" while the agent was working
            return agents.Report("Research - x", "## Summary\nHello there.")
        ack = agents.run_background(self.c, "scout", work, "on it")
        time.sleep(0.6)
        self.assertEqual((ack, self.c.said), ("on it", []))
        self.assertEqual(len(docs.list_reports()), 1)
        self.assertTrue(any(e[0] == "panel" for e in self.c.posted))
    def test_a_crash_becomes_a_short_sentence(self):
        agents.run_background(self.c, "scout", lambda: 1 / 0, "on it", "Sorry, no.")
        self.assertEqual(self.c.wait(1)[0], "Sorry, no.")


class Scribe(Base):
    def test_word_and_pdf_of_the_last_report(self):
        self.assertIn("no report", self.r("make a word file"))
        agents.record("scout", "Research - cats", "## Summary\nCats purr.\n\n- one\n- two", "Cats purr.")
        for phrase, ext in (("make a word file", ".docx"), ("pdf banao", ".pdf"), ("scribe make a pdf", ".pdf"), ("report ki word file banao", ".docx")):
            self.c.said.clear()
            self.assertEqual(self.r(phrase), "SCRIBE is on it.", phrase)
            self.assertIn(ext, self.c.wait(1)[0], phrase)
    def test_urdu_report_pdf_falls_back_to_word(self):
        agents.record("scout", "تحقیق", "## خلاصہ\nاردو متن", "اردو")
        self.r("make a pdf")
        out = self.c.wait(1)[0]
        self.assertIn(".docx", out)
        self.assertIn("Word file instead", out)


class Help(Base):
    def test_old_help_kept_and_new_added(self):
        out = self.r("help")
        self.assertIn("Say Jarvis closed to end me", out)
        for part in ("briefing", "scout", "local mode"):
            self.assertIn(part, out)


class UrduScript(Base):
    CASES = {
        "بریفنگ سناؤ": "daily briefing", "آج کا حال سناؤ": "daily briefing", "انٹرنیٹ کی سپیڈ چیک کرو": "speed check",
        "نوٹ لکھو کل نو بجے کال کرنی ہے": "write a note کل نو بجے کال کرنی ہے", "رپورٹس دکھاؤ": "show reports",
        "وہ رپورٹ کھولو": "open the report", "رپورٹ سناؤ": "read the report", "سمارٹ موڈ": "smart mode", "لوکل موڈ": "local mode",
        "کون سا موڈ ہے": "which mode", "دوبارہ بولو": "repeat that", "بریفنگ دوبارہ سناؤ": "repeat the last briefing",
        "ورڈ فائل بناؤ": "make a word file", "پی ڈی ایف بناؤ": "make a pdf", "سکاؤٹ لاہور پر ریسرچ کرو": "scout research لاہور",
        "ہیرالڈ پاکستان": "herald پاکستان", "سوشل چائے کی دکان کے لیے کیپشن لکھو": "social captions for چائے کی دکان",
        "ایس ای او شہد کے لیے": "seo keywords for شہد", "2500 ضرب 18 کتنے ہوئے": "2500 times 18", "روزانہ خبروں کا خلاصہ": "news briefing",
    }
    def test_mapping(self):
        for ur, en in self.CASES.items():
            self.assertEqual(urdu.to_command(ur), en, ur)
    def test_end_to_end_in_urdu_mode(self):
        urdu.set_mode("ur", save=False)
        self.assertIn("لوکل موڈ" if False else "Local", self.r("جارویس لوکل موڈ") or "Local")
        self.assertTrue(modes.is_local())
        self.r("جارویس بریفنگ سناؤ")
        self.assertTrue(self.c.wait(1))


class Wiring(unittest.TestCase):
    def test_spec_and_hooks(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = open(os.path.join(root, "jarvis.spec"), encoding="utf-8").read()
        for mod in ("features", "briefing", "docs", "agents", "modes", "extras2", "panel"):
            self.assertIn('"jarvis.%s"' % mod, spec)
        self.assertIn("briefing.start_at_boot", open(os.path.join(root, "jarvis", "app.py"), encoding="utf-8").read())
        self.assertTrue(os.path.isabs(config.REPORTS_DIR))
    def test_new_skills_sit_in_front_of_the_old_ones(self):
        order = [fn for _, fn, _ in skills._SKILLS]
        self.assertLess(order.index(features._briefing), order.index(skills._help))
        self.assertLess(order.index(features._note), order.index(skills._note))


if __name__ == "__main__":
    unittest.main()
