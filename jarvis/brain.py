"""The AI brain.

Primary : Groq, Grok (xAI) and/or OpenRouter free models - speech-sized answers, plus the command interpreter.
Fallback: key-less lookup (DuckDuckGo + Wikipedia), then opens Google results in the browser.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import browser, compat, net, services
from .config import Config
from .memory import Memory

log = logging.getLogger("jarvis.brain")

MOODS = ("neutral", "happy", "sad", "surprised", "angry")
_TAG = re.compile(r"^\s*\[(neutral|happy|sad|surprised|angry|thinking)\]\s*", re.I)


@dataclass
class Answer:
    text: str
    mood: str = "neutral"
    sources: list = field(default_factory=list)   # [(title, url)]
    engine: str = "local"
    streamed: bool = False                        # True = the text was already spoken piece by piece while it was written


def split_mood(text: str) -> tuple[str, str]:
    m = _TAG.match(text)
    if not m:
        return "neutral", text.strip()
    mood = m.group(1).lower()
    return (mood if mood in MOODS else "neutral"), text[m.end():].strip()


_ABBR = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "eg", "ie", "no", "prof", "jr", "sr", "inc", "ltd", "approx"}
_SENT_END = re.compile(r"([.!?]+[\"')\]]*)(\s+)")


def pop_sentences(buf: str, final: bool = False, min_len: int = 14, max_len: int = 170) -> tuple[list[str], str]:
    """Cut finished sentences off the front of a growing reply. Returns (sentences, unfinished rest).
    Very short sentences are held back and joined to the next one so the voice does not stutter; a very long run
    with no full stop is cut at a comma so speech can still start early."""
    out, start = [], 0
    for m in _SENT_END.finditer(buf):
        words = buf[start:m.start()].split()
        if words and words[-1].lower().strip("\"'(") .rstrip(".") in _ABBR and m.group(1) == ".":
            continue                                                # "Dr. Who" is not the end of a sentence
        if m.end() - start < min_len and not final:
            continue
        out.append(buf[start:m.end()].strip())
        start = m.end()
    rest = buf[start:]
    while len(rest) > max_len:                                       # no full stop for a long while
        cut = max(rest.rfind(", ", 0, max_len), rest.rfind("; ", 0, max_len), rest.rfind(" - ", 0, max_len))
        if cut < 40:
            break
        out.append(rest[:cut + 1].strip())
        rest = rest[cut + 2:]
    if final and rest.strip():
        out.append(rest.strip())
        rest = ""
    return out, rest


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


_FACT = re.compile(r"^(?:who|whos|what|whats|where|when|tell me|explain|define|what do you know|do you know|"
                   r"can you tell|have you heard)\b")
_STOP = set("the and you what who whos whats know about tell explain define can how are does did hey jarvis please "
            "bro there many some this that with for was were from have has your".split())


def relevant(question: str, text: str, url: str = "") -> bool:
    """Reject look-ups whose article has nothing to do with the question (e.g. 'how are you' -> a photographer)."""
    toks = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2 and w not in _STOP]
    if not toks:
        return False
    hay = (text + " " + url.replace("_", " ")).lower()
    return sum(w in hay for w in toks) / len(toks) >= 0.6


def nice_error(e: net.NetError) -> str:
    msg = str(e)
    try:
        body = json.loads(msg.split(": ", 1)[1])
        msg = body["error"]["message"]
    except Exception:
        pass
    return re.sub(r"\s+", " ", msg)[:220]


PLAN_SYSTEM = """You are the command interpreter of a voice assistant that controls the user's Windows PC.
The user's speech is transcribed by a recogniser, so words may be misheard or mangled - infer the most likely intent.
You get CONTEXT (what is open / what was just done) and what the user SAID. Resolve references such as "it", "that",
"there", "the same", and follow-ups: if YouTube is the active site and the user says "search Karan Aujla", that means
search YouTube. If an email window is active and the user says "new message", compose a new email.

Reply with ONE JSON object and nothing else: {"kind": "command" | "question" | "chat", "command": "<canonical>"}
  command  = the user wants something DONE on the computer (open, close, search, play, write an email, type, system info...)
  question = a factual / knowledge question to be answered      chat = conversation, jokes, opinions, creative writing
For "question" and "chat" leave "command" empty. For "command" use EXACTLY one of these canonical forms:
  open <app | website | folder>          close <app>              switch to <window or app>
  search <query> on <site>               play <query> on youtube   (sites: youtube google gmail wikipedia amazon github maps spotify reddit linkedin)
  compose email to <person or address> subject <subject> saying <text>   (all parts after "email" optional)
  type <text>                            press <key>               find file <name>
  volume up | volume down | mute | set volume to <0-100> | brightness up | brightness down | set brightness to <0-100>
  take a screenshot                      lock the computer         scroll down | scroll up | go back | go forward
  new tab | close tab | next tab | previous tab | refresh | zoom in | zoom out | minimize | maximize | full screen
  how many apps are installed            list installed apps       is <app> installed
  what apps are running                  what is the active window how much disk space is left
  what is my ip address                  how long has the pc been on
  set a timer for <duration>             remind me to <thing> in <duration>      take a note <text>
  what time is it | what is the date | weather in <city> | tell me the news | system status
  stop | go to standby
If the user asks for an action that is NOT in this list, still use kind "command" and put your best canonical guess;
never answer a command with facts.

Examples
CONTEXT: Last thing opened: youtube (site). | SAID: search karan ojla -> {"kind":"command","command":"search karan aujla on youtube"}
CONTEXT: Last thing opened: gmail (site). | SAID: compose a new mail -> {"kind":"command","command":"compose email"}
CONTEXT: none | SAID: how many programs do i have on this laptop -> {"kind":"command","command":"how many apps are installed"}
CONTEXT: Last thing opened: notepad (app). | SAID: close it -> {"kind":"command","command":"close notepad"}
CONTEXT: none | SAID: who is the president of france -> {"kind":"question","command":""}
CONTEXT: none | SAID: write me a poem about rain -> {"kind":"chat","command":""}"""


class Brain:
    def __init__(self, cfg: Config, mem: Memory):
        self.cfg, self.mem = cfg, mem
        self.on_status = None                 # callback(kind, message) -> shown in the transcript
        self._context = ""                    # what the user has been doing on the PC (from dialog.Dialog)
        rep_ = lambda k, m: self._report(k, m)
        self.providers = [compat.groq(cfg, rep_), compat.grok(cfg, rep_), compat.openrouter(cfg, rep_)]
        self._plan_off_until = 0.0

    def _report(self, kind: str, msg: str) -> None:
        (log.error if kind == "err" else log.info)(msg)
        if self.on_status:
            self.on_status(kind, msg)

    # ---- state ----------------------------------------------------------------------
    @property
    def has_keys(self) -> bool:
        return any(p.key and self.cfg.ai_provider in ("auto", p.name) for p in self.providers)

    def _ready(self) -> list:
        return [p for p in self.providers if p.ready(self.cfg.ai_provider, self.cfg.force_offline)]

    @property
    def llm_ready(self) -> bool:
        return bool(self._ready())

    @property
    def off_reason(self) -> str:
        paused = [p for p in self.providers if p.key and p.off_until > time.time()]
        return paused[0].reason if paused else ""

    @property
    def mode(self) -> str:
        if not self.has_keys:
            return "LITE - add GROQ_API_KEY to .env"
        ready = self._ready()
        if not ready:
            return "LITE - %s" % (self.off_reason or "AI paused")
        p = ready[0]
        return "%s %s" % (p.name.upper(), (p.model or "(auto)").split("/")[-1].upper())

    def check(self) -> str:
        """Called at start-up so problems (bad key, no credit) show immediately."""
        if self.cfg.force_offline:
            return self.mode
        for p in self.providers:
            if p.key and self.cfg.ai_provider in ("auto", p.name):
                try:
                    p.discover()
                except net.NetError as e:
                    p.error(e)
                    self._report("err", "%s check failed: %s" % (p.name.title(), nice_error(e)))
        return self.mode

    # ---- public ---------------------------------------------------------------------
    def ask(self, question: str, context: str = "", on_sentence=None, on_mood=None, should_stop=None) -> Answer:
        """on_sentence(text) is called for every finished sentence WHILE the model is still writing, so the voice can
        start after the first sentence. on_mood(mood) is called as soon as the mood tag has arrived."""
        self._context = context
        for p in self._ready():                              # Groq first, then Grok, OpenRouter as the last backup
            try:
                if on_sentence and self.cfg.stream_reply:
                    return self._answer_stream(p, question, on_sentence, on_mood, should_stop)
                return self._answer(p, question)
            except net.NetError as e:
                p.error(e)
                self._report("err", "%s error: %s" % (p.name.title(), nice_error(e)))
            except Exception as e:
                log.exception("%s failure", p.name)
                p.pause(60, "AI reply error")
                self._report("err", "%s reply error: %s" % (p.name.title(), e))
        return self._local(question)

    def _messages(self, question: str) -> list:
        msgs = [{"role": "system", "content": self._system_prompt()}]
        msgs += [{"role": "user" if r == "user" else "assistant", "content": t} for r, t in self.mem.turns(8)]
        msgs.append({"role": "user", "content": question})
        return msgs

    def _answer(self, p, question: str) -> Answer:
        return self.parse_reply(p.chat(self._messages(question)), p.name)

    def _answer_stream(self, p, question: str, on_sentence, on_mood=None, should_stop=None) -> Answer:
        raw, buf, tag_done, said = "", "", False, 0

        def emit(sentences):
            nonlocal said
            for sent in sentences:
                sent = clean_for_speech(sent)
                if re.search(r"\w", sent):
                    said += 1
                    on_sentence(sent)

        try:
            for piece in p.stream(self._messages(question), should_stop=should_stop):
                raw += piece
                buf += piece
                if not tag_done:                                   # the first thing is the "[happy]" mood tag
                    head = buf.lstrip()
                    if not head:
                        continue
                    if head.startswith("[") and "]" not in head and len(head) < 16:
                        continue
                    mood = split_mood(buf)[0]
                    buf = _TAG.sub("", buf, count=1).lstrip()          # (keep trailing spaces: they end a sentence)
                    tag_done = True
                    if on_mood:
                        on_mood(mood)
                sentences, buf = pop_sentences(buf)
                emit(sentences)
            if not (should_stop and should_stop()):
                emit(pop_sentences(buf, final=True)[0])
        except Exception:
            if not said:
                raise                                             # nothing spoken yet: the caller can try another model
            log.exception("stream ended early")
        if not said:
            return Answer("I didn't get an answer back.", "sad", engine=p.name)
        mood, text = split_mood(raw)
        return Answer(clean_for_speech(text), mood, engine=p.name, streamed=True)

    @staticmethod
    def parse_reply(raw, engine: str = "grok") -> Answer:
        if isinstance(raw, dict):                              # a raw API reply
            try:
                raw = raw["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raw = ""
        if not raw.strip():
            return Answer("I didn't get an answer back.", "sad", engine=engine)
        mood, text = split_mood(raw)
        return Answer(clean_for_speech(text) or "I came back empty handed.", mood, engine=engine)

    def _system_prompt(self) -> str:
        who = self.mem.name or self.cfg.user_name
        return (
            "You are J.A.R.V.I.S., a composed, witty, slightly dry British AI butler living on %s's desktop, in the "
            "spirit of Tony Stark's assistant. Your words are spoken aloud by a text-to-speech voice, so: answer in one "
            "to three short sentences unless asked for detail, in plain spoken English with no markdown, lists, emoji "
            "or URLs. The user speaks to you through speech recognition, so words may be misheard; infer the most "
            "likely meaning. You cannot browse the web: for anything recent (news, prices, scores, who currently holds "
            "a role) answer from what you know and say briefly that it may be out of date. Be warm and a little "
            "playful; address the user as %s now and then, not in every reply. Never claim to have done something on "
            "the computer that you did not do. If the user is asking you to DO something on the computer (open, close, "
            "search a site, write an email, play, type...) that you cannot do yourself, say so in one short sentence - "
            "never answer such a request with encyclopedia facts or 'according to Wikipedia'. Begin every reply with "
            "exactly one mood tag from: [neutral] [happy] [sad] [surprised] [angry]. The current date and time is %s.%s"
            % (who or "the user", who or "sir", datetime.now().strftime("%A %d %B %Y, %I:%M %p"),
               (" What the user has been doing on the PC: " + self._context) if self._context else ""))

    # ---- command planner ------------------------------------------------------------
    def plan(self, utterance: str, context: str = "") -> dict | None:
        """Turn a spoken sentence no rule understood into {"kind", "command"} using the conversation context.
        Returns None when no model is available (the caller then falls back to rules only)."""
        if time.time() < self._plan_off_until:
            return None
        for p in self._ready():
            try:
                raw = p.chat([{"role": "system", "content": PLAN_SYSTEM},
                              {"role": "user", "content": "CONTEXT: %s\nSAID: %s" % (context or "none", utterance)}],
                             0, 160, 15)
                plan = self.parse_plan({"candidates": [{"content": {"parts": [{"text": raw}]}}]})
                if plan:
                    return plan
            except net.NetError as e:
                p.error(e)
            except Exception:
                log.exception("planner failure")
        self._plan_off_until = time.time() + 15
        return None

    @staticmethod
    def parse_plan(data: dict) -> dict | None:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            raw = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
            raw = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip()).strip()
            m = re.search(r"\{.*\}", raw, re.S)                    # free models sometimes add chatter around the JSON
            obj = json.loads(m.group(0) if m else raw)
        except Exception:
            return None
        if not isinstance(obj, dict) or obj.get("kind") not in ("command", "question", "chat"):
            return None
        return {"kind": obj["kind"], "command": str(obj.get("command") or "").strip()}

    # ---- key-less fallback ----------------------------------------------------
    def _local(self, question: str) -> Answer:
        words = re.findall(r"\w+", question)
        down = self.has_keys and not self.cfg.force_offline
        if len(words) < 2:
            return Answer("Sorry, I did not catch that.", "neutral")
        if not _FACT.match(question.lower().strip()):
            why = (" My AI brain is unavailable: %s." % self.off_reason) if down and self.off_reason else ""
            return Answer("I can only run commands and look up facts right now.%s" % why, "sad", engine="lite")
        try:
            hit = services.lookup(question)
        except net.NetError:
            return Answer("I'm offline right now, so I can only run local commands.", "sad")
        if hit and relevant(question, hit[1], hit[2]):
            src, text, url = hit
            return Answer(text, "neutral", [(src, url)] if url else [(src, "")], "lite")
        browser.open_url(services.google_url(question))
        return Answer("I couldn't find a reliable answer, so I've opened Google for you.", "neutral", engine="lite")
