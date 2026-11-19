# -*- coding: utf-8 -*-
"""Part B: S1 prayer times, S2 focus timer, S3 translate, S4 converters, S5 to-do, S6 clipboard, S7 page summary, S8 journal."""
import os, sys, time, unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import agents, config, docs, extras2, features, net, urdu
from test_features import Base

AL = {"data": {"timings": {"Fajr": "04:58 (PKT)", "Sunrise": "06:20", "Dhuhr": "12:05", "Asr": "15:40", "Maghrib": "18:02", "Isha": "19:25", "Midnight": "00:00"}}}
RATES = {"rates": {"USD": 1, "PKR": 280.0, "EUR": 0.9, "GBP": 0.8, "SAR": 3.75}}
PAGE = (b"<html><head><title>Solar Panels 101</title><script>var x=1;</script></head><body><nav>menu</nav>"
        b"<p>Solar panels turn sunlight into electricity using photovoltaic cells made of silicon.</p>"
        b"<p>A typical home system needs between ten and twenty panels depending on your daily usage.</p>"
        b"<p>Prices have fallen sharply over the last decade, which makes solar attractive in sunny countries.</p></body></html>")


class B(Base):
    def setUp(self):
        super().setUp()
        extras2._TODO_PATH = os.path.join(self.tmp, "todo.json")
        extras2._pcache.update(day="", city="", t=None)
        extras2._rates.update(t=0.0, r=None)
        extras2._jreset()
        if extras2._POMO["stop"]:
            extras2._POMO["stop"].set()
        self.c.timers, self.c.spoken_async = [], []
        self.c.say_async = lambda s: self.c.spoken_async.append(s)
        self.c.add_timer = lambda secs, msg, label="": self.c.timers.append({"due": time.time() + secs, "label": label, "msg": msg, "timer": None})
    def tearDown(self):
        extras2._jreset()
        if extras2._POMO["stop"]:
            extras2._POMO["stop"].set()
        super().tearDown()
    def wait_said(self, n=1, secs=6):
        return self.c.wait(n, secs)


class S1Prayer(B):
    def test_next_prayer_logic(self):
        t = {"fajr": "04:58", "dhuhr": "12:05", "asr": "15:40", "maghrib": "18:02", "isha": "19:25"}
        d = datetime(2026, 11, 19, 13, 0)
        self.assertEqual(extras2.next_prayer(t, d)[0], "asr")
        self.assertEqual(extras2.next_prayer(t, datetime(2026, 11, 19, 3, 0))[0], "fajr")
        n, when = extras2.next_prayer(t, datetime(2026, 11, 19, 22, 0))
        self.assertEqual((n, when.day), ("fajr", 20))
        self.assertEqual(extras2._clock("15:40"), "3:40 PM")
        self.assertEqual(extras2._clock("00:05"), "12:05 AM")
    def test_phrases(self):
        with mock.patch.object(net, "get_json", return_value=AL):
            out = self.r("prayer times")
            self.assertTrue(all(x in out for x in ("Fajr 4:58 AM", "Isha 7:25 PM")), out)
            self.assertIn("Fajr", self.r("namaz ke auqaat batao"))
            self.assertIn("Maghrib is at 6:02 PM", self.r("maghrib ka time"))
            self.assertIn("Asr is at 3:40 PM", self.r("when is asr"))
            self.assertIn("The next prayer is", self.r("next namaz kab hai"))
            self.assertIn("The next prayer is", self.r("agli namaz kab hai"))
            self.assertTrue(any(e[0] == "panel" for e in self.c.posted))
    def test_bare_name_is_not_a_question_and_offline_is_polite(self):
        with mock.patch.object(net, "get_json", return_value=AL):
            self.assertIsNone(self.r("asr"))
        with mock.patch.object(net, "get_json", side_effect=net.NetError("offline")):
            self.assertIn("could not get the prayer times", self.r("prayer times"))
    def test_reminder_sets_a_timer(self):
        when = datetime.now() + timedelta(minutes=45)
        with mock.patch.object(net, "get_json", return_value=AL), mock.patch.object(extras2, "next_prayer", return_value=("asr", when)):
            self.assertIn("remind you 10 minutes before Asr", self.r("remind me before the next prayer"))
            self.assertIn("remind you 20 minutes before Asr", self.r("namaz se 20 minute pehle yaad dilao"))
        self.assertEqual(len(self.c.timers), 2)
        self.assertAlmostEqual(self.c.timers[0]["due"] - time.time(), 35 * 60, delta=5)
        near = datetime.now() + timedelta(minutes=5)
        with mock.patch.object(net, "get_json", return_value=AL), mock.patch.object(extras2, "next_prayer", return_value=("asr", near)):
            self.assertIn("less than 10 minutes", self.r("remind me before the next prayer"))


class S2Focus(B):
    def test_start_status_stop(self):
        self.assertIn("not running", self.r("focus status"))
        self.assertIn("25 minutes of work", self.r("start focus mode"))
        self.assertIn("already running", self.r("start pomodoro"))
        time.sleep(0.2)
        self.assertTrue(self.c.spoken_async and "Focus round 1" in self.c.spoken_async[0])
        self.assertTrue(any(e["label"] == "focus" for e in self.c.timers))
        self.assertRegex(self.r("focus status"), r"Round 1, focus time: 2[45] minutes")
        self.assertIn("Focus mode is off", self.r("stop focus mode"))
        self.assertIn("not running", self.r("stop focus mode"))
    def test_custom_length_and_cancel_timers_handle(self):
        self.assertIn("50 minutes of work", self.r("pomodoro 50 minutes"))
        time.sleep(0.2)
        self.c.timers[0]["timer"].cancel()                       # what "cancel timers" does
        self.assertFalse(extras2.pomodoro_running())
        self.assertIn("30 minutes of work", self.r("30 minute focus mode shuru karo"))
        self.assertIn("5 minutes of work", self.r("focus mode shuru karo") and self.r("stop focus mode") and self.r("start focus mode for 1 minutes"))
    def test_roman_urdu(self):
        self.assertIn("Focus mode on", self.r("focus mode shuru karo"))
        self.assertIn("Focus mode is off", self.r("focus mode band karo"))


class S3Translate(B):
    def test_ai_path(self):
        prompts = []
        self.c.brain.complete = lambda p, s="", mt=600, to=20: prompts.append(p) or "\u0635\u0628\u062d \u0628\u062e\u06cc\u0631"
        self.assertEqual(self.r("translate good morning into urdu"), "\u0635\u0628\u062d \u0628\u062e\u06cc\u0631")
        self.assertIn("Urdu (Urdu script)", prompts[0])
        self.assertTrue(self.r("how do you say thank you in urdu"))
        self.assertTrue(self.r("good night ko urdu mein translate karo"))
        self.assertTrue(self.r("urdu mein batao good night"))
        self.assertTrue(self.r("what is thank you in urdu"))
        self.assertTrue(self.r("good morning ka urdu tarjuma batao"))
        self.assertEqual(len(prompts), 6)
        self.assertTrue(self.r("translate hello to roman urdu"))
    def test_free_fallback_and_failures(self):
        seen = []
        def gj(url, params=None, timeout=12):
            seen.append(params)
            return {"responseData": {"translatedText": "Good morning"}}
        with mock.patch.object(net, "get_json", side_effect=gj):
            urdu.set_mode("ur", save=False)                       # Urdu script arrives in Urdu mode
            self.assertEqual(self.r("\u062c\u0627\u0631\u0648\u06cc\u0633 \u0635\u0628\u062d \u0628\u062e\u06cc\u0631 \u06a9\u0627 \u0627\u0646\u06af\u0631\u06cc\u0632\u06cc \u0645\u06cc\u06ba \u062a\u0631\u062c\u0645\u06c1 \u06a9\u0631\u0648"), "In English: Good morning")
            urdu.set_mode("en", save=False)
        self.assertEqual(seen[0]["langpair"], "ur|en")
        with mock.patch.object(net, "get_json", side_effect=net.NetError("offline")):
            self.assertIn("could not translate", self.r("translate good morning into urdu"))
        with mock.patch.object(net, "get_json", return_value={"responseData": {"translatedText": "MYMEMORY WARNING: QUOTA"}}):
            self.assertIn("could not translate", self.r("translate good morning into urdu"))
        self.assertIn("Smart mode with an AI key", self.r("translate good morning to roman urdu"))
    def test_not_hijacking(self):
        self.assertIsNone(self.r("what is the capital of france"))


class S4Convert(B):
    def go(self, p):
        with mock.patch.object(net, "get_json", return_value=RATES):
            return self.r(p)
    def test_currency(self):
        self.assertIn("28,000 Pakistani rupees", self.go("100 dollars in rupees"))
        self.assertIn("28,000", self.go("100 dollar kitne rupees"))
        self.assertIn("28,000", self.go("100 dollar ke kitne rupay hue"))
        self.assertIn("about 280 Pakistani rupees", self.go("dollar rate"))
        self.assertIn("about 311.11", self.go("1 euro kitne pkr"))
        self.assertIn("about 560", self.go("2 dollars in rupees"))
    def test_units(self):
        self.assertIn("3.11 miles", self.go("convert 5 km to miles"))
        self.assertIn("212 fahrenheit", self.go("100 celsius in fahrenheit"))
        self.assertIn("4.54 kg", self.go("10 pounds to kg"))              # a weight, not money
        self.assertIn("3.79 liters", self.go("1 gallon in liters"))
    def test_rates_cached_and_offline(self):
        with mock.patch.object(net, "get_json", return_value=RATES) as g:
            self.r("100 dollars in rupees"); self.r("5 dollars in rupees")
            self.assertEqual(g.call_count, 1)
        extras2._rates.update(t=0.0, r=None)
        with mock.patch.object(net, "get_json", side_effect=net.NetError("offline")):
            self.assertIn("could not get the exchange rate", self.r("100 dollars in rupees"))
    def test_unknown_units_and_old_calc_fall_through(self):
        self.assertIsNone(self.go("5 apples in basket"))
        self.assertEqual(self.go("2500 guna 18 kitne hue"), "That is 45000.")
        self.assertEqual(self.go("what is 2500 times 18"), "That is 45000.")


class S5Todo(B):
    def test_add_list_done_remove_clear(self):
        self.assertIn("empty", self.r("my to do list"))
        for p, task in (("add task buy milk", "buy milk"), ("add a task to call ali", "call ali"), ("to-do mein add karo FYP report", "fyp report"),
                        ("add send the invoice to my to do list", "send the invoice"), ("task add karo pay bills", "pay bills")):
            self.assertIn("Added to your to-do list", self.r(p), p)
            self.assertIn(task, [x.lower() for x in extras2.pending()], p)
        self.assertEqual(len(extras2.pending()), 5)
        out = self.r("show my tasks")
        self.assertIn("5 open tasks", out)
        self.assertIn("1, buy milk", out)
        self.assertTrue(any(e[0] == "panel" for e in self.c.posted))
        for p in ("to do list dikhao", "what is on my to-do list", "aaj ke kaam batao"):
            self.assertIn("open tasks", self.r(p), p)
        self.assertIn("Done: buy milk", self.r("mark task 1 done"))
        self.assertIn("Done: call ali", self.r("task 1 done karo"))
        self.assertEqual(len(extras2.pending()), 3)
        self.assertIn("Done: pay bills", self.r("mark pay bills done"))
        self.assertIn("task number 9", self.r("mark task 9 done"))
        self.assertIn("Removed: fyp report", self.r("remove task 1").replace("FYP", "fyp"))
        self.assertIn("Cleared 3 finished", self.r("clear completed tasks"))
        self.assertIn("cleared (1 item)", self.r("clear my to do list"))
    def test_persists_on_disk_and_survives_bad_file(self):
        extras2.add_task("one")
        self.assertEqual(extras2.pending(), ["one"])
        open(extras2._TODO_PATH, "w").write("{not json")
        self.assertEqual(extras2.pending(), [])
        extras2.add_task("two")
        self.assertEqual(extras2.pending(), ["two"])
    def test_other_mark_sentences_fall_through(self):
        self.assertIsNone(self.r("mark my homework as done"))
        self.assertEqual(self.r("take a note buy milk"), "Noted.")                       # notes unaffected
    def test_briefing_includes_tasks(self):
        extras2.add_task("finish report")
        from jarvis import briefing
        spoken, shown = briefing.format_briefing({"weather": None, "items": [], "todos": extras2.pending()})
        self.assertIn("1 open task on your list: finish report", spoken)
        self.assertIn("## To-do", shown)


class S6Clipboard(B):
    def test_read_summary_save(self):
        text = "The meeting is moved to Friday. Bring the report. Ali will join late. Lunch is provided."
        with mock.patch.object(extras2, "get_clipboard", return_value=text):
            for p in ("read the clipboard", "clipboard padho", "what did i copy"):
                self.assertIn("You copied: The meeting is moved", self.r(p), p)
            self.assertIn("Reading", self.r("summarize the clipboard"))
            self.assertIn("meeting", self.wait_said(1)[0].lower())
            self.assertEqual(self.r("save clipboard to notes"), "Saved your clipboard as a note.")
            self.assertIn("meeting is moved", " ".join(self.c.mem.read_notes(3)))
        with mock.patch.object(extras2, "get_clipboard", return_value=None):
            for p in ("read the clipboard", "summarize the clipboard", "save clipboard to notes"):
                self.assertIn("clipboard is empty", self.r(p), p)
    def test_summary_uses_ai(self):
        self.c.brain.complete = lambda p, s="", mt=600, to=20: "AI says: short."
        with mock.patch.object(extras2, "get_clipboard", return_value="x " * 50):
            self.r("clipboard ka summary do")
            self.assertEqual(self.wait_said(1)[0], "AI says: short.")


class S7Page(B):
    def test_link_summary_saves_a_report(self):
        with mock.patch.object(net, "get_bytes", return_value=PAGE):
            self.assertIn("Reading the page", self.r("summarize https://example.com/solar"))
            said = self.wait_said(1)[0]
        self.assertTrue(said.startswith("SUMMARY reporting"), said)
        self.assertIn("Solar panels", said)
        rep = agents.last("summary")
        self.assertIn("Solar Panels 101", rep["title"])
        self.assertTrue(os.path.isfile(rep["path"]))
    def test_this_page_and_clipboard_link(self):
        with mock.patch.object(net, "get_bytes", return_value=PAGE), mock.patch.object(extras2, "_current_tab_url", return_value="https://example.com/a"):
            self.assertIn("Reading the page", self.r("is page ka summary do"))
            self.wait_said(1)
        self.c.said.clear()
        with mock.patch.object(net, "get_bytes", return_value=PAGE), mock.patch.object(extras2, "get_clipboard", return_value="https://example.com/b"):
            self.assertIn("Reading the page", self.r("summarize the link"))
            self.assertIn("SUMMARY reporting", self.wait_said(1)[0])
        with mock.patch.object(extras2, "_current_tab_url", return_value=None):
            self.assertIn("could not read the address", self.r("summarize this page"))
        with mock.patch.object(extras2, "get_clipboard", return_value="no link here"):
            self.assertIn("did not find a link", self.r("summarize the link"))
    def test_failure_is_one_sentence(self):
        with mock.patch.object(net, "get_bytes", side_effect=net.NetError("offline")):
            self.r("summarize https://example.com/x")
            self.assertIn("could not read that page", self.wait_said(1)[0])
    def test_fetch_page_strips_noise(self):
        with mock.patch.object(net, "get_bytes", return_value=PAGE):
            title, text = extras2.fetch_page("example.com")
        self.assertEqual(title, "Solar Panels 101")
        self.assertNotIn("menu", text)
        self.assertNotIn("var x", text)


class S8Journal(B):
    def test_full_flow(self):
        self.assertIn("How was your day", self.r("journal likho"))
        self.assertTrue(extras2.journal_active())
        self.assertIn("What did you get done", self.r("Pretty good, a bit tiring."))
        self.assertIn("one thing for tomorrow", self.r("Finished the Jarvis features"))
        self.assertIn("Saving your journal", self.r("Call the client at ten"))
        said = self.wait_said(1)[0]
        self.assertIn("Journal saved as Journal-", said)
        self.assertIn("Call the client at ten", said)
        self.assertFalse(extras2.journal_active())
        name = [f for f, _ in docs.list_reports() if f.startswith("Journal-")][0]
        text = docs.read_docx(os.path.join(docs.reports_dir(), name))
        for part in ("Pretty good, a bit tiring.", "Finished the Jarvis features", "Call the client at ten"):          # capitals and commas kept
            self.assertIn(part, text)
        self.assertIn("Call the client at ten", extras2.pending())
        self.assertIn("Finished the Jarvis features", self.r("read my journal"))
    def test_cancel_and_not_intercepting_when_idle(self):
        self.assertIn("no journal entry", self.r("cancel journal"))
        self.r("journal likho")
        self.assertIn("cancelled", self.r("cancel journal"))
        self.assertFalse(extras2.journal_active())
        self.assertNotIn("journal", (self.r("what is on my to do list") or "").lower())
        with mock.patch.object(agents, "dispatch") as d:
            self.r("journal likho")
            self.r("scout is great")                                             # an answer, not an agent call
            d.assert_not_called()
    def test_expires(self):
        self.r("journal likho")
        extras2._JOURNAL["t"] = time.time() - 700
        self.assertFalse(extras2.journal_active())
        with mock.patch.object(agents, "dispatch", return_value="ok") as d:
            self.r("scout research cats")
            d.assert_called_once()
    def test_ai_reflection_is_added(self):
        self.c.brain.complete = lambda p, s="", mt=600, to=20: "You did well today."
        self.r("journal likho"); self.r("good"); self.r("done stuff"); self.r("rest")
        self.assertIn("You did well today.", self.wait_said(1)[0])
    def test_urdu_answers_reach_the_journal(self):
        self.r("journal likho")
        self.assertEqual(urdu.to_command("آج کا دن اچھا رہا"), "journal answer آج کا دن اچھا رہا")
        urdu.set_mode("ur", save=False)
        self.r("جارویس آج کا دن اچھا رہا")
        self.assertEqual(extras2._JOURNAL["step"], 2)
        self.assertEqual(extras2._JOURNAL["answers"], ["آج کا دن اچھا رہا"])
        self.assertEqual(urdu.to_command("جرنل منسوخ"), "cancel journal")


class PartBUrdu(B):
    CASES = {
        "نماز کے اوقات بتاؤ": "prayer times", "اگلی نماز کب ہے": "next prayer", "مغرب کا وقت": "maghrib time",
        "نماز سے پہلے یاد دلاؤ": "remind me before the next prayer", "فوکس موڈ شروع کرو": "start focus mode",
        "فوکس موڈ بند کرو": "stop focus mode", "25 منٹ کا فوکس": "start focus mode for 25 minutes",
        "صبح بخیر کا انگریزی میں ترجمہ کرو": "translate صبح بخیر to english", "100 ڈالر کتنے روپے ہوئے": "100 dollars in rupees",
        "ڈالر کا ریٹ": "dollar rate", "ٹو ڈو میں ایف وائی پی رپورٹ شامل کرو": "add task ایف وائی پی رپورٹ",
        "میرے کام دکھاؤ": "show my to do list", "ٹاسک 2 مکمل": "mark task 2 done", "کلپ بورڈ پڑھو": "read the clipboard",
        "کلپ بورڈ کا خلاصہ": "summarize the clipboard", "اس صفحے کا خلاصہ": "summarize this page", "جرنل لکھو": "journal",
        "ڈائری پڑھو": "read my journal",
    }
    def test_mapping(self):
        for ur, en in self.CASES.items():
            self.assertEqual(urdu.to_command(ur), en, ur)
    def test_end_to_end_in_urdu_mode(self):
        urdu.set_mode("ur", save=False)
        self.assertIn("empty", self.r("جارویس میرے کام دکھاؤ"))
        self.assertIn("Added", self.r("جارویس ٹو ڈو میں دودھ شامل کرو"))
        with mock.patch.object(net, "get_json", return_value=RATES):
            self.assertIn("28,000", self.r("جارویس 100 ڈالر کتنے روپے ہوئے"))


class Wiring(unittest.TestCase):
    def test_journal_catcher_is_first_and_all_registered(self):
        from jarvis import skills
        order = [fn for _, fn, _ in skills._SKILLS]
        self.assertEqual(order[0], extras2._journal_catch)
        for fn in (extras2._prayer_list, extras2._focus_start, extras2._translate, extras2._convert, extras2._todo_add,
                   extras2._clip_read, extras2._page_summary, extras2._journal_start):
            self.assertIn(fn, order)
            self.assertGreater(order.index(fn), order.index(features._briefing))
    def test_help_mentions_part_b(self):
        from jarvis import skills
        class C(Base):
            pass
        out = skills.route(Base.__new__(Base) and __import__("test_features").Ctx(), "help")
        for part in ("prayer times", "focus mode", "to-do list", "daily journal"):
            self.assertIn(part, out)


if __name__ == "__main__":
    unittest.main()
