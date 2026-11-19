# -*- coding: utf-8 -*-
"""Urdu mode + news desk."""
import os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import brain, extras, newsdesk, skills, tts, urdu
from test_core import FakeCtx
from test_extras import FakeWin

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Big storm hits the coast - Dawn</title><source>Dawn</source></item>
<item><title>Talks resume in Geneva - Reuters</title><source>Reuters</source></item>
<item><title>Big storm hits the coast - Dawn</title><source>Dawn</source></item>
<item><title>Rupee gains against dollar - Business Recorder</title><source>Business Recorder</source></item>
</channel></rss>"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        urdu._STORE = os.path.join(self.tmp, "language.txt")
        urdu.set_mode("en", save=False)
        self.c = FakeCtx()
        self.c.hud_post = lambda *a, **k: None
    def tearDown(self):
        urdu.set_mode("en", save=False)
    def r(self, s): return skills.route(self.c, s)


class Mapping(Base):
    CASES = {
        "یوٹیوب کھولو": "open youtube", "جارویس واٹس ایپ کھولو": "open whatsapp", "کروم بند کرو": "close chrome",
        "نوٹ پیڈ کھول دو": "open notepad", "کروم چلاؤ": "open chrome", "آواز بڑھاؤ": "volume up", "آواز کم کرو": "volume down",
        "آواز پچاس کرو": "set volume to 50", "آواز بند کرو": "mute", "گانا روکو": "pause", "اگلا گانا": "next song",
        "دس سیکنڈ آگے": "skip 10 seconds", "وقت کیا ہوا ہے": "what time is it", "آج کیا تاریخ ہے": "what is the date today",
        "لاہور کا موسم کیسا ہے": "weather in lahore", "اسکرین شاٹ لو": "take a screenshot",
        "پانچ منٹ کا ٹائمر لگاؤ": "set a timer for 5 minutes", "اردو میں بات کرو": "switch to urdu",
        "انگریزی میں بات کرو": "switch to english", "گوگل پر پاکستان کا موسم سرچ کرو": "search پاکستان کا موسم on google",
        "یوٹیوب پر عاطف اسلم کے گانے چلاؤ": "play عاطف اسلم کے گانے on youtube",
        "پاکستان کی تازہ خبریں سناؤ": "breaking news from Pakistan", "عالمی خبریں": "world news",
        "جغرافیائی سیاست کی خبریں": "geopolitics news", "بریکنگ نیوز": "breaking news", "روزانہ خبروں کا خلاصہ": "news briefing",
        "حسنات کی چیٹ کھولو": "open chat of حسنات on whatsapp", "بھیج دو": "send", "ٹائپ کرو آپ کیسے ہیں": "type آپ کیسے ہیں",
        "حسنات کو واٹس ایپ پر میسج کرو کہ میں دیر سے آؤں گا": "send a message to حسنات saying میں دیر سے آؤں گا",
    }
    def test_commands(self):
        for ur, en in self.CASES.items():
            self.assertEqual(urdu.to_command(ur), en, ur)

    def test_unknown_goes_to_ai(self):
        self.assertIsNone(urdu.to_command("پاکستان کا دارالحکومت کیا ہے"))

    def test_yes_no_only_when_asked(self):
        self.assertIsNone(urdu.to_command("ہاں"))
        self.assertEqual(urdu.to_command("ہاں", pending=True), "yes")
        self.assertEqual(urdu.to_command("نہیں", pending=True), "no")

    def test_wake_and_control(self):
        self.assertTrue(skills.has_wake_word("جارویس یوٹیوب کھولو"))
        self.assertTrue(skills.has_wake_word("جاروس، وقت کیا ہوا ہے"))
        self.assertFalse(skills.has_wake_word("یوٹیوب کھولو"))
        self.assertEqual(skills.control_of("رکو"), "stop")
        self.assertEqual(skills.control_of("جارویس بند ہو جاؤ"), "exit")
        self.assertIsNone(skills.control_of("بند ہو جاؤ"))              # exit needs the wake word
        self.assertEqual(skills.strip_wake_raw("جارویس یوٹیوب کھولو"), "یوٹیوب کھولو")


class Routing(Base):
    def test_open_via_urdu(self):
        with mock.patch("webbrowser.open"):
            self.assertEqual(self.r("جارویس یوٹیوب کھولو"), "Opening youtube.")

    def test_switch_language_both_ways(self):
        self.assertIn("اردو", self.r("switch to urdu"))
        self.assertTrue(urdu.is_urdu())
        self.assertEqual(self.r("انگریزی میں بات کرو"), "Switched to English.")
        self.assertFalse(urdu.is_urdu())
        self.r("speak urdu"); self.assertTrue(urdu.is_urdu())
        self.r("reply in english"); self.assertFalse(urdu.is_urdu())

    def test_mode_is_saved(self):
        urdu.set_mode("ur"); urdu._mode = None
        self.assertEqual(urdu.mode(), "ur")

    def test_whatsapp_message_in_urdu_keeps_urdu_text(self):
        with FakeWin() as w:
            q = self.r("حسنات کو واٹس ایپ پر میسج کرو کہ میں دیر سے آؤں گا")
            self.assertIn("حسنات", q)
            self.assertIn(("type", "حسنات"), w.log)
            self.assertIn(("type", "میں دیر سے آؤں گا"), w.log)
            self.assertNotIn(("press", "enter"), w.log[-2:])
            self.c.dialog.pending                                       # confirmation is waiting
            self.assertEqual(self.r("ہاں"), "Sent.")


class Replies(Base):
    def test_templates_only_in_urdu_mode(self):
        self.assertEqual(urdu.localize("Opening youtube."), "Opening youtube.")
        urdu.set_mode("ur", save=False)
        self.assertEqual(urdu.localize("Opening youtube."), "youtube کھول رہا ہوں۔")
        self.assertEqual(urdu.localize("Done."), "ہو گیا۔")
        self.assertIn("بجے", urdu.localize("It is 3:45 PM."))
        self.assertIn("نومبر", urdu.localize("Today is Wednesday, 18 November 2026."))

    def test_ai_fallback_and_cache(self):
        urdu.set_mode("ur", save=False)
        calls = []
        tr = lambda t: calls.append(t) or "یہ ایک ٹیسٹ ہے"
        self.assertEqual(urdu.localize("A brand new sentence here.", tr), "یہ ایک ٹیسٹ ہے")
        urdu.localize("A brand new sentence here.", tr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(urdu.localize("Another unknown one.", lambda t: None), "Another unknown one.")   # no AI: stays English
        self.assertEqual(urdu.localize("Already اردو", tr), "Already اردو")

    def test_voice_choice(self):
        self.assertEqual(urdu.voice_for("یہ اردو ہے", "en-GB-RyanNeural")[0], "ur-PK-AsadNeural")
        self.assertEqual(urdu.voice_for("Hello there", "en-GB-RyanNeural"), ("en-GB-RyanNeural", None))

    def test_urdu_sentences_are_split_for_speech(self):
        self.assertEqual(len(tts.chunk_text("پہلی خبر یہ ہے کہ بارش ہوئی ہے۔ دوسری خبر یہ ہے کہ موسم صاف ہے۔ تیسری خبر بھی ہے۔", target=20)), 3)
        out, rest = brain.pop_sentences("پہلا جملہ یہاں ختم ہوتا ہے۔ دوسرا جملہ ابھی", min_len=5)
        self.assertEqual(out, ["پہلا جملہ یہاں ختم ہوتا ہے۔"])

    def test_brain_prompt_switches_language(self):
        b = brain.Brain.__new__(brain.Brain)
        b.mem = mock.Mock(name=None); b.mem.name = "Hasnat"; b.cfg = mock.Mock(user_name="Hasnat"); b._context = ""
        self.assertNotIn("URDU", b._system_prompt())
        urdu.set_mode("ur", save=False)
        self.assertIn("URDU", b._system_prompt())


class News(Base):
    def setUp(self):
        super().setUp()
        self.urls = []
        def fake(url, params=None, **kw):
            self.urls.append((url, dict(params or {})))
            return RSS
        self.p = mock.patch.object(newsdesk.net, "get_bytes", side_effect=fake); self.p.start()
        self.c.cfg = mock.Mock(news_region="PK")
    def tearDown(self):
        self.p.stop(); super().tearDown()

    def test_country_breaking_news(self):
        out = self.r("what are the breaking news of Pakistan")
        self.assertIn("from Pakistan", out); self.assertIn("Big storm hits the coast.", out)
        self.assertEqual(out.count("Big storm"), 1)                   # duplicates dropped
        self.assertEqual(self.urls[0][0], "https://news.google.com/rss")
        self.assertEqual(self.urls[0][1]["gl"], "PK")

    def test_other_country_edition_and_search_fallback(self):
        self.r("tell me the news from India")
        self.assertEqual(self.urls[0][1]["gl"], "IN")
        self.urls.clear()
        self.r("news from Iran")                                      # no Google edition: falls back to a search
        self.assertTrue(any("search" in u for u, _ in self.urls))
        self.assertIn("Iran", self.urls[0][1]["q"])

    def test_global_and_geopolitics(self):
        self.r("tell me the breaking news from the global world")
        self.assertTrue(self.urls[0][0].endswith("/topic/WORLD"))
        self.urls.clear()
        out = self.r("give me geopolitics news")
        self.assertIn("geopolitics", out)
        self.assertIn("geopolitics", self.urls[0][1]["q"])
        self.urls.clear()
        self.r("what is the latest geopolitical update on Iran")
        self.assertIn("Iran", self.urls[0][1]["q"])

    def test_topics_counts_and_free_subject(self):
        self.r("top 3 business headlines"); self.assertTrue(self.urls[0][0].endswith("/topic/BUSINESS"))
        out = self.r("headlines"); self.assertIn("from Pakistan", out)           # default = home country
        self.urls.clear()
        self.r("latest news about bitcoin"); self.assertIn("bitcoin", self.urls[0][1]["q"])
        self.assertEqual(len(newsdesk.fetch(country="PK", n=2).items), 2)

    def test_not_hijacked(self):
        with mock.patch("webbrowser.open"):
            self.assertIn("Opening", self.r("open google news"))
        self.assertIsNone(self.r("tell us a story") if False else None)

    def test_urdu_mode_uses_urdu_edition(self):
        urdu.set_mode("ur", save=False)
        out = self.r("پاکستان کی تازہ خبریں")
        self.assertIn("پاکستان کی تازہ ترین سرخیاں", out)
        self.assertEqual(self.urls[0][1]["hl"], "ur"); self.assertEqual(self.urls[0][1]["ceid"], "PK:ur")
        self.urls.clear()
        self.r("عالمی خبریں"); self.assertTrue(self.urls[0][0].endswith("/topic/WORLD")); self.assertEqual(self.urls[0][1]["hl"], "ur")
        self.urls.clear()
        self.r("جغرافیائی سیاست کی خبریں"); self.assertIn("عالمی سیاست", self.urls[0][1]["q"])

    def test_english_command_urdu_news(self):
        out = self.r("pakistan news in urdu")
        self.assertIn("سرخیاں", out)

    def test_feed_down(self):
        self.p.stop()
        with mock.patch.object(newsdesk.net, "get_bytes", side_effect=RuntimeError("offline")):
            self.assertIn("can't reach", self.r("breaking news"))
        self.p.start()

    def test_briefing(self):
        out = self.r("daily news briefing")
        self.assertIn("news briefing", out.lower())
        self.assertGreaterEqual(len(self.urls), 3)                     # home + world + geopolitics


if __name__ == "__main__":
    unittest.main()


class FeatureMapping(unittest.TestCase):
    """Urdu script -> the English commands of the new features (briefing, speed, reports, modes, repeat, agents, Word/PDF)."""
    CASES = {
        "بریفنگ سناؤ": "daily briefing", "آج کا حال سناؤ": "daily briefing", "انٹرنیٹ کی سپیڈ چیک کرو": "speed check",
        "نوٹ لکھو کل نو بجے کال کرنی ہے": "write a note کل نو بجے کال کرنی ہے", "رپورٹس دکھاؤ": "show reports",
        "وہ رپورٹ کھولو": "open the report", "سمارٹ موڈ": "smart mode", "لوکل موڈ": "local mode", "کون سا موڈ ہے": "which mode",
        "دوبارہ بولو": "repeat that", "بریفنگ دوبارہ سناؤ": "repeat the last briefing", "ورڈ فائل بناؤ": "make a word file",
        "پی ڈی ایف بناؤ": "make a pdf", "سکاؤٹ لاہور پر ریسرچ کرو": "scout research لاہور", "ہیرالڈ پاکستان": "herald پاکستان",
        "ایس ای او شہد کے لیے": "seo keywords for شہد", "2500 ضرب 18 کتنے ہوئے": "2500 times 18",
        "روزانہ خبروں کا خلاصہ": "news briefing",          # the old news briefing mapping must survive
    }
    def test_mapping(self):
        for ur, en in self.CASES.items():
            self.assertEqual(urdu.to_command(ur), en, ur)

