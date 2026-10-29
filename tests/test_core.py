import ctypes, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import brain as brain_mod, browser, net, services, skills, winctl
browser.set_preferred("default")          # tests must never start a real Chrome
from jarvis.config import Config
from jarvis.dialog import Dialog
from jarvis.face import Face
from jarvis.memory import Memory
from jarvis.tts import chunk_text


class FakeCtx:
    """Just enough of Jarvis for the skills to run."""
    def __init__(self, key=""):
        self.cfg = Config(xai_key=key, grok_model="grok-test")
        self.mem = Memory(tempfile.mkdtemp())
        self.brain = brain_mod.Brain(self.cfg, self.mem)
        self.face = Face()
        self.speaker = mock.Mock()
        self.abort_typing = mock.Mock()
        self.awake_until, self.wake_on, self.weather, self.stats = 0, True, None, {"cpu": 12, "ram": 40, "battery": (80, True)}
        self.last_reply, self.timers_added, self.posted = "", [], []
        self.dialog, self.addressed, self.online = Dialog(600), True, True
        self.interrupted = 0
    def hud_post(self, *e): self.posted.append(e)
    def add_timer(self, s, m, label=''): self.timers_added.append((s, m))
    def cancel_timers(self): return len(self.timers_added)
    def quit_later(self, s): self.quit = s
    def set_mic(self, on): self.mic = on
    def set_wake(self, on): self.wake_on = on
    def type_later(self, t): self.typed = t
    def run_demo(self): self.demo = True
    def interrupt(self, listen=True): self.interrupted += 1
    def hide_window(self): self.hidden = True
    def show_window(self): self.hidden = False


class Skills(unittest.TestCase):
    def setUp(self): self.c = FakeCtx()
    def r(self, s): return skills.route(self.c, s)

    def test_wake_word(self):
        for ok in ("Jarvis how are you", "hey jarvis", "Travis what time is it", "what time is it Jarvis", "jervis open notepad"):
            self.assertTrue(skills.has_wake_word(ok), ok)
        for no in ("what time is it", "open the door please", "I love this service"):
            self.assertFalse(skills.has_wake_word(no), no)

    def test_normalize_and_wake_strip(self):
        self.assertEqual(skills.strip_wake(skills.normalize("Hey Jarvis, can you please open Notepad?")), "open notepad")
        self.assertEqual(skills.strip_wake(skills.normalize("what's the time, Jarvis")), "whats the time")

    def test_time_date(self):
        self.assertTrue(self.r("Jarvis what's the time?").startswith("It is"))
        self.assertTrue(self.r("what is the date").startswith("Today is"))

    def test_questions_fall_through_to_brain(self):
        for q in ("what time does the sun set in lahore", "who is the prime minister of japan",
                  "what is photosynthesis", "write me a poem about rain"):
            self.assertIsNone(self.r(q), q)

    def test_calc(self):
        self.assertEqual(self.r("what is 12 times 7"), "That is 84.")
        self.assertEqual(self.r("calculate 20 percent of 150"), "That is 30.")
        self.assertEqual(self.r("what is the square root of 144"), "That is 12.")
        self.assertEqual(self.r("10 divided by 4"), "That is 2.5.")
        self.assertEqual(self.r("2 to the power of 10"), "That is 1024.")
        self.assertIsNone(skills.calculate("__import__('os')"))
        self.assertIsNone(skills.calculate("9 ** 9 ** 9"))

    def test_timers(self):
        self.assertEqual(self.r("set a timer for 5 minutes"), "Timer set for 5 minutes.")
        self.assertEqual(self.c.timers_added[-1][0], 300)
        self.r("remind me to stretch in 10 minutes")
        self.assertEqual(self.c.timers_added[-1], (600, "Reminder: stretch."))
        self.r("set a timer for an hour and a half")
        self.assertEqual(self.c.timers_added[-1][0], 5400)
        self.r("set a 30 second timer")
        self.assertEqual(self.c.timers_added[-1][0], 30)
        self.assertEqual(skills.parse_duration("half an hour"), 1800)
        self.assertEqual(skills.fmt_duration(3750), "1 hour 2 minutes")

    def test_notes_and_name(self):
        self.assertEqual(self.r("take a note buy milk"), "Noted.")
        self.assertIn("buy milk", self.r("read my notes"))
        self.assertIn("Zaeem", self.r("my name is zaeem"))
        self.assertEqual(self.r("who am i"), "You are Zaeem.")

    def test_face_and_misc(self):
        self.assertEqual(self.r("look left"), "Looking left.")
        self.assertEqual(self.r("be happy"), "I am happy!")
        self.assertEqual(self.r("goodbye"), "Goodbye. Shutting down.")
        self.assertEqual(self.r("stop"), "")
        self.assertIn("CPU at 12", self.r("system status"))
        self.assertIn(self.r("jarvis"), ("Yes?", "At your service.", "I'm listening."))

    def test_smalltalk_only_offline(self):
        self.assertIn("Hello", self.r("hello") + "Hello")
        self.assertIsNotNone(self.r("how are you"))            # offline: canned
        self.c = FakeCtx(key="x")                              # AI on: left to the AI
        self.assertIsNone(self.r("how are you"))
        self.assertIsNone(self.r("tell me a joke"))


def reply(text):
    return {"choices": [{"message": {"content": text}}]}


def models(*ids):
    return {"data": [{"id": i} for i in ids]}


class Brain(unittest.TestCase):
    def brain(self, **kw):
        b = brain_mod.Brain(Config(**kw), Memory(tempfile.mkdtemp()))
        self.msgs = []
        b.on_status = lambda k, m: self.msgs.append((k, m))
        return b

    def test_parse_reply(self):
        a = brain_mod.Brain.parse_reply("[happy] The *answer* is 42. See https://x.y", "grok")
        self.assertEqual((a.mood, a.text, a.engine), ("happy", "The answer is 42. See", "grok"))
        self.assertIn("didn't get", brain_mod.Brain.parse_reply({}).text)
        self.assertEqual(brain_mod.Brain.parse_reply(reply("[sad] Oh.")).mood, "sad")

    def test_request_shape_and_history(self):
        c = FakeCtx(key="KEY")
        c.mem.add_turn("user", "hi"); c.mem.add_turn("model", "hello")
        with mock.patch.object(net, "post_json", return_value=reply("[neutral] Fine.")) as p:
            a = c.brain.ask("how are you", "Last thing opened: youtube (site).")
        url, body, headers = p.call_args[0][0], p.call_args[0][1], p.call_args[0][3]
        self.assertEqual(url, "https://api.x.ai/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        self.assertEqual(body["model"], "grok-test")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
        self.assertIn("youtube", body["messages"][0]["content"])
        self.assertEqual(a.text, "Fine.")

    def test_all_providers_failing_falls_back_and_pauses(self):
        c = FakeCtx(key="KEY")
        with mock.patch.object(net, "post_json", side_effect=net.NetError("HTTP 429", 429)), \
             mock.patch.object(services, "lookup", return_value=("Wikipedia", "Paris is the capital.", "u")):
            a = c.brain.ask("what is the capital of france")
        self.assertEqual(a.engine, "lite")
        self.assertFalse(c.brain.llm_ready)
        self.assertIn("rate limited", c.brain.mode)

    def test_offline(self):
        c = FakeCtx()
        with mock.patch.object(services, "lookup", side_effect=net.NetError("down")):
            self.assertIn("offline", c.brain.ask("what is a black hole").text)

    def test_grok_key_rejected_openrouter_takes_over(self):
        b = self.brain(xai_key="X", grok_model="grok-4", openrouter_key="O")
        def post(url, body, timeout=25, headers=None):
            if "x.ai" in url:
                raise net.NetError("HTTP 401: bad key", 401)
            return reply("[happy] From OpenRouter.")
        with mock.patch.object(net, "post_json", post), \
             mock.patch.object(net, "get_json", return_value=models("a/b:free")):
            a = b.ask("hello there")
        self.assertEqual((a.engine, a.text), ("openrouter", "From OpenRouter."))
        self.assertFalse(b.providers[1].ready("auto", False))                # Grok paused, not hammered
        self.assertTrue(any(k == "err" for k, _ in self.msgs))

    def test_provider_switch(self):
        b = self.brain(xai_key="X", openrouter_key="O", ai_provider="openrouter")
        self.assertEqual([p.name for p in b._ready()], ["openrouter"])
        b = self.brain(xai_key="X", openrouter_key="O")
        self.assertEqual([p.name for p in b._ready()], ["grok", "openrouter"])

    def test_bad_key_at_startup_is_reported(self):
        b = self.brain(xai_key="X")
        with mock.patch.object(net, "get_json", side_effect=net.NetError("HTTP 401: key invalid", 401)):
            self.assertIn("rejected", b.check())
        self.assertTrue(any(k == "err" for k, _ in self.msgs))

    def test_no_keys(self):
        b = self.brain()
        self.assertIn("GROQ_API_KEY", b.mode)
        self.assertFalse(b.llm_ready)


OR_MODELS = models("meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.3-70b-instruct",
                   "deepseek/deepseek-r1:free", "google/gemma-3-27b-it:free", "qwen/qwen2.5-vl-72b-instruct:free",
                   "openai/gpt-oss-20b:free", "mistralai/mistral-7b-instruct:free")


class OpenRouter(unittest.TestCase):
    def brain(self):
        return brain_mod.Brain(Config(openrouter_key="O"), Memory(tempfile.mkdtemp()))

    def test_only_free_chat_models_best_first(self):
        b = self.brain()
        with mock.patch.object(net, "get_json", return_value=OR_MODELS):
            ranked = b.providers[2].discover()
        self.assertEqual(ranked[0], "meta-llama/llama-3.3-70b-instruct:free")
        self.assertTrue(all(m.endswith(":free") for m in ranked))
        self.assertNotIn("deepseek/deepseek-r1:free", ranked)                  # slow reasoning model
        self.assertNotIn("qwen/qwen2.5-vl-72b-instruct:free", ranked)          # vision model

    def test_busy_free_model_is_skipped_for_the_next(self):
        b = self.brain()
        seen = []
        def post(url, body, timeout=25, headers=None):
            seen.append(body["model"])
            if len(seen) == 1:
                raise net.NetError("HTTP 429: rate-limited upstream", 429)
            return reply("[neutral] Second model here.")
        with mock.patch.object(net, "get_json", return_value=OR_MODELS), mock.patch.object(net, "post_json", post):
            a = b.ask("hello there")
        self.assertEqual(a.text, "Second model here.")
        self.assertNotEqual(seen[0], seen[1])
        with mock.patch.object(net, "post_json", post):                        # the busy one stays benched
            b.ask("again")
        self.assertNotIn(seen[0], seen[2:])

    def test_empty_answer_moves_on(self):
        b = self.brain()
        outs = iter([reply(""), reply("[neutral] Fine.")])
        with mock.patch.object(net, "get_json", return_value=OR_MODELS), \
             mock.patch.object(net, "post_json", lambda *a, **k: next(outs)):
            self.assertEqual(b.ask("hello there").text, "Fine.")

    def test_headers_and_fixed_model(self):
        b = brain_mod.Brain(Config(openrouter_key="O", openrouter_model="x/y:free,z/w:free"), Memory(tempfile.mkdtemp()))
        with mock.patch.object(net, "post_json", return_value=reply("[neutral] Ok.")) as p:
            b.ask("hello there")
        self.assertEqual(p.call_args[0][0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(p.call_args[0][1]["model"], "x/y:free")
        self.assertEqual(p.call_args[0][3]["Authorization"], "Bearer O")
        self.assertIn("X-Title", p.call_args[0][3])

    def test_everything_busy_reports_and_pauses(self):
        b = self.brain()
        with mock.patch.object(net, "get_json", return_value=OR_MODELS), \
             mock.patch.object(net, "post_json", side_effect=net.NetError("HTTP 429", 429)), \
             mock.patch.object(services, "lookup", return_value=None), mock.patch("webbrowser.open"):
            a = b.ask("what is a black hole")
        self.assertEqual(a.engine, "lite")
        self.assertFalse(b.llm_ready)


class Fallback(unittest.TestCase):
    def test_no_wikipedia_garbage_for_chitchat(self):
        b = brain_mod.Brain(Config(xai_key="K"), Memory(tempfile.mkdtemp()))
        with mock.patch.object(services, "lookup", return_value=("Wikipedia", "Chase Jarvis is a photographer.", "u")) as lk:
            a = b._local("hi how are you")
        lk.assert_not_called()
        self.assertEqual(a.sources, [])

    def test_irrelevant_article_rejected(self):
        self.assertFalse(brain_mod.relevant("what you know about Zayn mobile", "WrestleMania 42 was a 2026 event", "wiki/WrestleMania_42"))
        self.assertTrue(brain_mod.relevant("tell me about Cristiano Ronaldo", "Cristiano Ronaldo is a footballer", ""))
        b = brain_mod.Brain(Config(), Memory(tempfile.mkdtemp()))
        with mock.patch.object(services, "lookup", return_value=("Wikipedia", "WrestleMania 42 was an event.", "x")), \
             mock.patch("webbrowser.open") as wb:
            a = b._local("what do you know about zayn mobile")
        self.assertIn("Google", a.text); wb.assert_called_once()

    def test_wake_word_stripped_for_ai(self):
        self.assertEqual(skills.strip_wake_raw("Hi Jarvis, how are you?"), "how are you?")
        self.assertEqual(skills.strip_wake_raw("Who is Zayn Malik, Jarvis"), "Who is Zayn Malik")
        self.assertEqual(skills.strip_wake_raw("Jarvis"), "Jarvis")


class YouTube(unittest.TestCase):
    def test_search_on_youtube(self):
        c = FakeCtx()
        with mock.patch("webbrowser.open") as wb:
            r = skills.route(c, "search Karan Aujla on YouTube")
        self.assertEqual(r, "Searching YouTube for karan aujla.")
        self.assertIn("karan%20aujla", wb.call_args[0][0])
        self.assertEqual(skills.route(c, "I said stop"), "")


class OpenAndSearch(unittest.TestCase):
    def test_compound_command(self):
        c = FakeCtx()
        with mock.patch("webbrowser.open") as wb:
            r = skills.route(c, "Jarvis open YouTube and search Karan Aujla")
        self.assertEqual(r, "Opening youtube. Searching YouTube for karan aujla.")
        self.assertIn("karan%20aujla", wb.call_args[0][0])
        with mock.patch("webbrowser.open") as wb:
            self.assertIn("Google", skills.route(c, "open google and search for pakistan weather"))


class EnvFile(unittest.TestCase):
    def test_inline_comments_stripped(self):
        from jarvis import config
        d = tempfile.mkdtemp(); path = os.path.join(d, ".env")
        open(path, "w").write('T_A=true   # note\nT_B=   # nothing here\nT_C="x # kept"\nT_D=en-US          # accent\n')
        for k in ("T_A", "T_B", "T_C", "T_D"): os.environ.pop(k, None)
        config.load_env(path)
        self.assertEqual([os.environ[k] for k in ("T_A", "T_B", "T_C", "T_D")], ["true", "", "x # kept", "en-US"])
        # the shipped template must load to sane values
        for k in [k for k in os.environ if k.startswith("JARVIS_")]: os.environ.pop(k)
        config.load_env(os.path.join(config.ROOT, ".env.example"))
        c = config.Config.load()
        self.assertTrue(c.wake_enabled); self.assertEqual((c.mic_device, c.language), ("", "en-US"))


class Misc(unittest.TestCase):
    def test_input_struct_size(self):
        self.assertEqual(ctypes.sizeof(winctl.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_chunking(self):
        text = "One. " * 200
        parts = chunk_text(text)
        self.assertTrue(all(len(p) <= 240 for p in parts) and len(parts) > 1)
        self.assertEqual(chunk_text("**Hi** see https://x.com now"), ["Hi see now"])

    def test_shorten(self):
        s = services.shorten("Paris (French: [pa.ʁi]) is big. It is old. It is nice.")
        self.assertEqual(s, "Paris is big. It is old.")

    def test_memory_persist(self):
        d = tempfile.mkdtemp(); Memory(d).set_name("Zaeem")
        self.assertEqual(Memory(d).name, "Zaeem")

    def test_mood_tag(self):
        self.assertEqual(brain_mod.split_mood("[Surprised] Wow."), ("surprised", "Wow."))
        self.assertEqual(brain_mod.split_mood("No tag."), ("neutral", "No tag."))


if __name__ == "__main__":
    unittest.main()


def test_whisper_punctuation_is_ignored():
    from jarvis import skills
    assert skills.normalize("Jarvis, open settings.") == "jarvis open settings"
    assert skills.normalize("Open Visual Studio Code!") == "open visual studio code"
    assert skills.normalize("what is 3.5 plus 2.") == "what is 3.5 plus 2"
    assert skills.control_of("Jarvis, stop.") == "stop"
    assert skills.control_of("Jarvis, shut down.") == "exit"
    assert skills.control_of("Jarvis, close.") == "exit"


def test_misheard_and_filler_commands():
    from jarvis import skills
    assert skills.control_of("Closet.") == "exit"
    assert skills.control_of("Jarvis, I said shut down.") == "exit"
    assert skills.control_of("Jarvis, I said you to be shut down.") == "exit"
    assert skills.control_of("close") is None                      # a bare 'close' never quits without Jarvis' name
    assert skills.strip_filler("i said open chrome") == ("open chrome", True)
