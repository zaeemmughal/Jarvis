"""Groq, streaming answers, speech/typing sync, Chrome launching, social-media commands, Groq speech-to-text."""
import os, sys, tempfile, threading, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import brain as brain_mod, browser, net, skills
from jarvis.config import Config
from jarvis.memory import Memory
from jarvis.tts import Speaker
from test_core import FakeCtx


def sse(*pieces):
    return iter([{"choices": [{"delta": {"content": p}}]} for p in pieces])


class GroqProvider(unittest.TestCase):
    def test_groq_key_in_the_xai_slot_is_recognised(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "gsk_abc", "GROQ_API_KEY": ""}), mock.patch("jarvis.config.load_env"):
            c = Config.load()
        self.assertEqual((c.groq_key, c.xai_key), ("gsk_abc", ""))

    def test_request_goes_to_groq(self):
        b = brain_mod.Brain(Config(groq_key="gsk_x", groq_model="llama-3.3-70b-versatile"), Memory(tempfile.mkdtemp()))
        ok = {"choices": [{"message": {"content": "[happy] Hello."}}]}
        with mock.patch.object(net, "post_json", return_value=ok) as p:
            a = b.ask("hi there")
        self.assertEqual(p.call_args[0][0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual((a.engine, a.text), ("groq", "Hello."))

    def test_model_discovery_skips_speech_and_guard_models(self):
        b = brain_mod.Brain(Config(groq_key="gsk_x"), Memory(tempfile.mkdtemp()))
        ids = ["whisper-large-v3", "llama-3.1-8b-instant", "llama-3.3-70b-versatile", "meta-llama/llama-guard-4-12b",
               "playai-tts", "openai/gpt-oss-20b", "groq/compound"]
        with mock.patch.object(net, "get_json", return_value={"data": [{"id": i} for i in ids]}):
            ranked = b.providers[0].discover()
        self.assertEqual(ranked[0], "llama-3.3-70b-versatile")
        for bad in ("whisper-large-v3", "meta-llama/llama-guard-4-12b", "playai-tts", "groq/compound"):
            self.assertNotIn(bad, ranked)

    def test_groq_is_tried_before_grok(self):
        b = brain_mod.Brain(Config(groq_key="g", xai_key="x"), Memory(tempfile.mkdtemp()))
        self.assertEqual([p.name for p in b._ready()], ["groq", "grok"])


class Streaming(unittest.TestCase):
    def brain(self):
        return brain_mod.Brain(Config(groq_key="g", groq_model="m"), Memory(tempfile.mkdtemp()))

    def test_sentences_are_delivered_while_the_model_is_still_writing(self):
        b, got, order = self.brain(), [], []

        def stream(*a, **k):
            for piece in ("[hap", "py] Sure thing, sir. I have ", "opened it for you. And ", "one more thing"):
                order.append("net:" + piece)
                yield {"choices": [{"delta": {"content": piece}}]}
        with mock.patch.object(net, "post_stream", lambda *a, **k: stream()):
            moods = []
            a = b.ask("hello", on_sentence=lambda s: (got.append(s), order.append("say")), on_mood=moods.append)
        self.assertEqual(moods, ["happy"])
        self.assertEqual(got[:2], ["Sure thing, sir.", "I have opened it for you."])    # first clip goes out at once
        self.assertEqual(got[-1], "And one more thing")
        self.assertLess(order.index("say"), order.index("net:one more thing"))     # first sentence spoken before the end
        self.assertTrue(a.streamed)
        self.assertEqual(a.mood, "happy")
        self.assertEqual(a.text, "Sure thing, sir. I have opened it for you. And one more thing")

    def test_busy_model_before_any_text_moves_on(self):
        b = self.brain()
        b.providers[0].ranked = ["m1", "m2"]
        calls = []

        def stream(url, payload, *a, **k):
            calls.append(payload["model"])
            if payload["model"] == "m1":
                raise net.NetError("HTTP 429", 429)
            return sse("[neutral] Second model here.")
        with mock.patch.object(net, "post_stream", stream):
            said = []
            a = b.ask("hello", on_sentence=said.append)
        self.assertEqual(calls, ["m1", "m2"])
        self.assertEqual(said, ["Second model here."])

    def test_stop_ends_the_stream(self):
        b, said, stop = self.brain(), [], threading.Event()
        def gen(*a, **k):
            yield {"choices": [{"delta": {"content": "[neutral] First sentence is here. "}}]}
            stop.set()
            yield {"choices": [{"delta": {"content": "Second sentence that must not be spoken. "}}]}
        with mock.patch.object(net, "post_stream", lambda *a, **k: gen()):
            b.ask("x", on_sentence=said.append, should_stop=stop.is_set)
        self.assertEqual(said, ["First sentence is here."])

    def test_splitter(self):
        s, rest = brain_mod.pop_sentences("Yes. Dr. Who is a show about a time lord. Next")
        self.assertEqual((s, rest), (["Yes. Dr. Who is a show about a time lord."], "Next"))
        self.assertEqual(brain_mod.pop_sentences("no stop", final=True), (["no stop"], ""))
        self.assertEqual(brain_mod.pop_sentences("Pi is 3.14159 roughly, sir. Okay")[0], ["Pi is 3.14159 roughly, sir."])


class SpeechSync(unittest.TestCase):
    def test_every_clip_is_announced_in_order_and_idle_fires_once(self):
        got, idle = [], []
        sp = Speaker(Config(tts_engine="off"), on_idle=lambda: idle.append(1), on_chunk=lambda t, s: got.append((t, s)))
        sp.say("First sentence of the answer is right here.")
        sp.say("Second sentence follows straight after it, with a few more words in it.")
        t0 = time.time()
        while (sp.speaking.is_set() or not idle) and time.time() - t0 < 10:
            time.sleep(0.05)
        self.assertEqual([t[:5] for t, _ in got], ["First", "Secon"])
        self.assertTrue(all(s > 0 for _, s in got))
        self.assertEqual(len(idle), 1)

    def test_stop_silences_the_queue(self):
        got = []
        sp = Speaker(Config(tts_engine="off"), on_chunk=lambda t, s: got.append(t))
        sp.say("One long sentence that goes on for quite a while so it is still playing when stop arrives.")
        sp.say("Another that must never be heard at all because we stopped before it started playing.")
        time.sleep(0.2)
        sp.stop()
        time.sleep(0.6)
        self.assertEqual(len(got), 1)
        self.assertFalse(sp.speaking.is_set())


class Chrome(unittest.TestCase):
    def setUp(self):
        browser.set_preferred("chrome")
        self.addCleanup(browser.set_preferred, "default")

    def test_chrome_is_used_when_installed(self):
        with mock.patch.object(browser, "find", return_value="/x/chrome"), mock.patch("subprocess.Popen") as po:
            self.assertTrue(browser.open_url("https://www.instagram.com"))
        self.assertEqual(po.call_args[0][0], ["/x/chrome", "https://www.instagram.com"])

    def test_incognito_flag(self):
        with mock.patch.object(browser, "find", return_value="/x/chrome"), mock.patch("subprocess.Popen") as po:
            browser.open_url("https://x.com", incognito=True)
        self.assertEqual(po.call_args[0][0], ["/x/chrome", "--incognito", "https://x.com"])

    def test_falls_back_to_the_default_browser(self):
        with mock.patch.object(browser, "find", return_value=None), mock.patch("webbrowser.open") as wb:
            self.assertFalse(browser.open_url("https://x.com"))
        wb.assert_called_once_with("https://x.com")


class SocialMedia(unittest.TestCase):
    def run_cmds(self, *phrases):
        c, urls = FakeCtx(), []
        with mock.patch.object(browser, "open_url", side_effect=lambda u, **k: urls.append((u, k))), \
             mock.patch.object(skills.time, "sleep"):
            out = [skills.route(c, p) for p in phrases]
        return out, urls

    def test_every_social_site_opens(self):
        for name, host in (("facebook", "facebook.com"), ("instagram", "instagram.com"), ("tiktok", "tiktok.com"),
                           ("snapchat", "snapchat.com"), ("pinterest", "pinterest.com"), ("telegram", "telegram.org"),
                           ("discord", "discord.com"), ("reddit", "reddit.com"), ("twitter", "x.com"),
                           ("whatsapp", "whatsapp.com"), ("linkedin", "linkedin.com"), ("threads", "threads.net")):
            _, urls = self.run_cmds("open " + name)
            self.assertIn(host, urls[0][0], name)

    def test_spoken_variants(self):
        for said, host in (("open insta gram", "instagram"), ("open tik tok", "tiktok"), ("open fb", "facebook"),
                           ("open whats app", "whatsapp"), ("go to facebook", "facebook"), ("open instagrm", "instagram"),
                           ("open the facebook website", "facebook")):
            _, urls = self.run_cmds(said)
            self.assertTrue(urls and host in urls[0][0], said)

    def test_several_at_once(self):
        out, urls = self.run_cmds("open facebook, instagram and youtube")
        self.assertEqual(len(urls), 3)
        self.assertEqual(out[0], "Opening facebook, instagram and youtube.")

    def test_all_social_media(self):
        out, urls = self.run_cmds("open all social media")
        self.assertEqual(len(urls), 6)
        self.assertTrue(any("instagram" in u for u, _ in urls))
        _, urls = self.run_cmds("open social media")
        self.assertEqual(len(urls), 6)

    def test_social_list_is_configurable(self):
        c = FakeCtx(); c.cfg.social = "tiktok, snapchat"
        with mock.patch.object(browser, "open_url") as op, mock.patch.object(skills.time, "sleep"):
            skills.route(c, "open all social media")
        self.assertEqual(op.call_count, 2)

    def test_incognito(self):
        out, urls = self.run_cmds("open instagram in incognito")
        self.assertEqual(urls[0][1], {"incognito": True})
        self.assertIn("private", out[0])

    def test_apps_still_open_as_apps(self):
        with mock.patch.object(skills, "launch") as la, mock.patch.object(browser, "open_url") as op:
            skills.route(FakeCtx(), "open notepad")
        la.assert_called()
        op.assert_not_called()

    def test_search_a_social_site(self):
        _, urls = self.run_cmds("search cats on tiktok")
        self.assertIn("tiktok.com/search?q=cats", urls[0][0])


class GroqSpeechToText(unittest.TestCase):
    def listener(self, **kw):
        from jarvis.audio import Listener
        return Listener(Config(groq_key="gsk_x", **kw), lambda t: None, lambda m: None, lambda: False)

    class Audio:
        def get_wav_data(self, **k): return b"RIFFwav"

    def test_request_and_text(self):
        l = self.listener()
        with mock.patch.object(net, "post_multipart", return_value={"text": " open instagram. "}) as pm:
            self.assertEqual(l._groq_stt(self.Audio()), "open instagram.")
        url, fields, files = pm.call_args[0][:3]
        self.assertTrue(url.endswith("/audio/transcriptions"))
        self.assertEqual((fields["model"], fields["language"]), ("whisper-large-v3-turbo", "en"))
        self.assertEqual(files["file"][1], b"RIFFwav")

    def test_silence_hallucinations_are_dropped(self):
        l = self.listener()
        with mock.patch.object(net, "post_multipart", return_value={"text": "Thank you."}):
            self.assertEqual(l._groq_stt(self.Audio()), "")

    def test_failure_falls_back_to_google_and_backs_off(self):
        l = self.listener()
        with mock.patch.object(net, "post_multipart", side_effect=net.NetError("HTTP 429", 429)) as pm:
            self.assertIsNone(l._groq_stt(self.Audio()))
            self.assertIsNone(l._groq_stt(self.Audio()))
        self.assertEqual(pm.call_count, 1)                       # not hammered while it is rate limited

    def test_can_be_switched_off(self):
        self.assertIsNone(self.listener(stt="google")._groq_stt(self.Audio()))


if __name__ == "__main__":
    unittest.main()
