"""Conversation context: what Jarvis last opened, what is on screen right now, and the follow-up logic.

This is what links a new command to the previous one:
    "open youtube"        -> focus = youtube
    "search karan aujla"  -> no site named, so it is searched *on youtube* (the thing in focus)
    "close it"            -> "it" = youtube
    "do that again"       -> repeats the last real command
    "set a timer"         -> "For how long?"  ... "five minutes" -> completes the timer

Everything here is plain Python with no I/O (the foreground-window probe is injected), so it is unit-tested.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

# --------------------------------------------------------------------------- sites
SEARCH_URLS = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
    "gmail": "https://mail.google.com/mail/u/0/#search/{q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.com/s?k={q}",
    "daraz": "https://www.daraz.pk/catalog/?q={q}",
    "github": "https://github.com/search?q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "stack overflow": "https://stackoverflow.com/search?q={q}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
    "twitter": "https://x.com/search?q={q}",
    "facebook": "https://www.facebook.com/search/top?q={q}",
    "netflix": "https://www.netflix.com/search?q={q}",
    "kaggle": "https://www.kaggle.com/search?q={q}",
    "fiverr": "https://www.fiverr.com/search/gigs?query={q}",
    "drive": "https://drive.google.com/drive/search?q={q}",
    "tiktok": "https://www.tiktok.com/search?q={q}",
    "pinterest": "https://www.pinterest.com/search/pins/?q={q}",
    "twitch": "https://www.twitch.tv/search?term={q}",
    "quora": "https://www.quora.com/search?q={q}",
    "medium": "https://medium.com/search?q={q}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={q}",
    "aliexpress": "https://www.aliexpress.com/wholesale?SearchText={q}",
    "imdb": "https://www.imdb.com/find/?q={q}",
    "soundcloud": "https://soundcloud.com/search?q={q}",
    "udemy": "https://www.udemy.com/courses/search/?q={q}",
    "coursera": "https://www.coursera.org/search?query={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google images": "https://www.google.com/search?tbm=isch&q={q}",
    "google news": "https://news.google.com/search?q={q}",
    "google scholar": "https://scholar.google.com/scholar?q={q}",
    "youtube music": "https://music.youtube.com/search?q={q}",
    "olx": "https://www.olx.com.pk/items/q-{q}",
    "upwork": "https://www.upwork.com/nx/search/jobs/?q={q}",
    "leetcode": "https://leetcode.com/problemset/?search={q}",
    "huggingface": "https://huggingface.co/models?search={q}",
    "telegram": "https://web.telegram.org/k/",
}
SITE_ALIASES = {
    "you tube": "youtube", "yt": "youtube", "mail": "gmail", "email": "gmail", "e mail": "gmail", "inbox": "gmail",
    "my mail": "gmail", "google mail": "gmail", "my email": "gmail", "x": "twitter", "map": "maps",
    "google maps": "maps", "google drive": "drive", "stackoverflow": "stack overflow", "git hub": "github",
    "wiki": "wikipedia", "face book": "facebook", "google search": "google", "the browser": "google",
    "browser": "google",
    "insta": "instagram", "insta gram": "instagram", "ig": "instagram", "fb": "facebook", "meta": "facebook",
    "whats app": "whatsapp", "what's app": "whatsapp", "whatsapp web": "whatsapp", "tik tok": "tiktok",
    "tick tock": "tiktok", "snap chat": "snapchat", "linked in": "linkedin", "tweeter": "twitter", "tweet": "twitter",
    "you tube music": "youtube music", "yt music": "youtube music", "chat gpt": "chatgpt", "chat g p t": "chatgpt",
    "open ai": "chatgpt", "google calendar": "calendar", "google docs": "docs", "google sheets": "sheets",
    "google slides": "slides", "google news": "google news", "google images": "google images",
    "google scholar": "google scholar", "duck duck go": "duckduckgo", "stack over flow": "stack overflow",
    "face book messenger": "messenger", "fb messenger": "messenger", "telegram web": "telegram",
    "hugging face": "huggingface", "geeks for geeks": "geeksforgeeks", "leet code": "leetcode",
    "google gemini": "gemini", "microsoft teams": "teams", "ms teams": "teams", "twitch tv": "twitch",
    "pin interest": "pinterest", "red it": "reddit", "reddit.com": "reddit",
}
MAIL_KEYS = ("gmail", "outlook", "new email")


def canon_site(name: str) -> str:
    name = re.sub(r"^(?:the|my)\s+", "", name.strip().lower())
    if name in SITE_ALIASES:                                    # "whats app" is a name, not "whats" + "app"
        return SITE_ALIASES[name]
    name = re.sub(r"\s+(?:website|site|page|app)$", "", name)
    return SITE_ALIASES.get(name, name)


def search_url(site: str, query: str) -> str:
    return SEARCH_URLS[site].format(q=urllib.parse.quote(query, safe=""))


# --------------------------------------------------------------------------- what is on screen
BROWSER_EXES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "chromium"}
TITLE_SITES = (("youtube", "youtube"), ("gmail", "gmail"), ("outlook", "outlook"), ("google search", "google"),
               ("whatsapp", "whatsapp"), ("github", "github"), ("spotify", "spotify"), ("amazon", "amazon"),
               ("daraz", "daraz"), ("wikipedia", "wikipedia"), ("reddit", "reddit"), ("linkedin", "linkedin"),
               ("netflix", "netflix"), ("google maps", "maps"), ("stack overflow", "stack overflow"),
               ("chatgpt", "chatgpt"), ("claude", "claude"), ("kaggle", "kaggle"), ("fiverr", "fiverr"),
               ("google drive", "drive"), ("facebook", "facebook"), ("instagram", "instagram"),
               ("inbox", "gmail"), ("tiktok", "tiktok"), ("pinterest", "pinterest"), ("twitch", "twitch"),
               ("telegram", "telegram"), ("discord", "discord"), ("snapchat", "snapchat"), ("quora", "quora"),
               ("medium", "medium"), ("messenger", "messenger"), ("threads", "threads"), ("x.com", "twitter"),
               ("twitter", "twitter"), ("ebay", "ebay"), ("imdb", "imdb"),
               ("udemy", "udemy"), ("coursera", "coursera"), ("leetcode", "leetcode"), ("notion", "notion"),
               ("canva", "canva"), ("figma", "figma"), ("google docs", "docs"), ("google sheets", "sheets"),
               ("google calendar", "calendar"), ("olx", "olx"), ("upwork", "upwork"))
APP_EXES = {"notepad.exe": "notepad", "winword.exe": "word", "excel.exe": "excel", "powerpnt.exe": "powerpoint",
            "code.exe": "vs code", "calculatorapp.exe": "calculator", "calc.exe": "calculator",
            "spotify.exe": "spotify", "whatsapp.exe": "whatsapp", "explorer.exe": "file explorer",
            "mspaint.exe": "paint", "taskmgr.exe": "task manager", "cmd.exe": "command prompt",
            "windowsterminal.exe": "terminal", "powershell.exe": "powershell", "vlc.exe": "vlc",
            "telegram.exe": "telegram", "discord.exe": "discord", "zoom.exe": "zoom", "teams.exe": "teams"}


@dataclass
class Focus:
    kind: str            # "site" | "app" | "folder"
    key: str             # canonical key: "youtube", "notepad", ...
    label: str
    ts: float
    src: str = "jarvis"  # "jarvis" = something Jarvis opened, "screen" = seen in the foreground window


def infer_focus(title: str, exe: str, now: float | None = None) -> Optional[Focus]:
    """Turn (window title, process name) into what the user is looking at."""
    now = now or time.time()
    title_l, exe = (title or "").lower(), (exe or "").lower()
    if not title_l and not exe:
        return None
    if title_l.startswith("j.a.r.v.i.s"):                       # that is us - not informative
        return None
    if exe in BROWSER_EXES:
        for needle, key in TITLE_SITES:
            if needle in title_l:
                return Focus("site", key, key, now, "screen")
        return Focus("site", "browser", "the browser", now, "screen")
    if exe in APP_EXES:
        return Focus("app", APP_EXES[exe], APP_EXES[exe], now, "screen")
    if exe:
        stem = exe.rsplit(".", 1)[0]
        return Focus("app", stem, stem, now, "screen")
    return None


# --------------------------------------------------------------------------- vocabulary
CMD_VERBS = set("""open launch start run close quit exit kill search find look play watch type dictate press hit
compose write draft send create make take set remind note remember show hide minimize maximize minimise maximise
switch go scroll turn lock mute unmute volume increase decrease lower raise skip pause resume restart shutdown shut
sleep install uninstall list read check delete clear cancel save copy paste select refresh reload zoom click bring
put add call text email mail message stop resume repeat again enable disable brightness screenshot capture bookmark
download upload pull navigate visit browse view display load fire jump get""".split())
FREE_TEXT = {"type", "dictate", "note", "remind", "remember", "write", "say", "compose", "draft", "send", "text",
             "message", "add"}
_Q_START = re.compile(r"^(?:what|whats|who|whos|whom|whose|where|when|why|how|which|is|are|was|were|do|does|did|am|"
                      r"tell me|explain|define|describe|can you tell|do you know|have you|has)\b")
PC_WORDS = re.compile(r"\b(?:pc|computer|laptop|installed|apps?|applications?|programs?|software|windows?|screen|"
                      r"tabs?|browser|folders?|files?|drive|storage|disk|wifi|battery|brightness|volume)\b")


def looks_like_command(t: str) -> bool:
    words = t.split()
    if not words:
        return False
    if words[0] in CMD_VERBS:
        return True
    return bool(PC_WORDS.search(t)) and len(words) <= 14 and not t.startswith(("who ", "why "))


def is_question(t: str) -> bool:
    return bool(_Q_START.match(t)) and not PC_WORDS.search(t)


_SPLIT = re.compile(r"(\s+(?:and then|and also|then|after that|and)\s+)")


def split_compound(t: str) -> list[str]:
    """'open youtube and search karan aujla' -> ['open youtube', 'search karan aujla'].
    Only splits where the next piece starts with a command verb, and never inside free text ('type tom and jerry')."""
    words = t.split()
    if len(words) < 3 or words[0] not in CMD_VERBS or words[0] in FREE_TEXT:
        return [t]
    bits = _SPLIT.split(t)
    out = [bits[0]]
    for sep, piece in zip(bits[1::2], bits[2::2]):
        head = piece.split()[0] if piece.split() else ""
        if head in CMD_VERBS and not (len(piece.split()) == 1 and head in ("stop", "again")):
            out.append(piece)
        else:
            out[-1] += sep + piece
    return out


YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|confirmed|please do|proceed|affirmative|"
                 r"haan|han|ji|ji haan|correct)(?: please| do it| go ahead)?$")
NO = re.compile(r"^(?:no|nope|nah|cancel|dont|do not|dont do it|never ?mind|abort|negative|nahi|na|stop it|leave it)$")


# --------------------------------------------------------------------------- state
@dataclass
class Resolution:
    text: Optional[str] = None     # rewritten command to run through the skills
    reply: Optional[str] = None    # or a direct answer

    @property
    def handled(self) -> bool:
        return self.text is not None or self.reply is not None


@dataclass
class Pending:
    kind: str                      # "confirm" | "slot"
    fn: Callable
    expires: float


class Dialog:
    def __init__(self, ttl: float = 600.0, probe: Callable[[], Optional[tuple]] | None = None):
        self.ttl = ttl
        self.probe = probe                       # () -> (title, exe) of the foreground window, or None
        self.focus: Optional[Focus] = None
        self.history: deque = deque(maxlen=10)   # (ts, command, reply)
        self.last_action: Optional[str] = None
        self.pending: Optional[Pending] = None
        self.cached_list: list[str] = []         # e.g. the app list, for "read more"

    # ---- focus ---------------------------------------------------------------------
    def set_focus(self, kind: str, key: str, label: str | None = None) -> None:
        self.focus = Focus(kind, key, label or key, time.time(), "jarvis")

    def screen_focus(self) -> Optional[Focus]:
        if not self.probe:
            return None
        try:
            info = self.probe()
        except Exception:
            return None
        return infer_focus(*info) if info else None

    def referent(self) -> Optional[Focus]:
        """What 'it' / 'that' means: the last thing Jarvis touched (if recent), otherwise what is on screen."""
        f = self.focus
        if f and time.time() - f.ts < self.ttl:
            return f
        scr = self.screen_focus()
        return scr if scr and scr.key != "browser" else None

    def search_target(self) -> Optional[str]:
        """Which site a bare 'search X' should go to, or None for plain Google."""
        now, f = time.time(), self.focus
        if f and now - f.ts < 4 and f.key in SEARCH_URLS:           # we literally just opened it
            return f.key
        scr = self.screen_focus()
        if scr and scr.key in SEARCH_URLS:                          # a searchable page is in front of the user
            return scr.key
        if f and now - f.ts < self.ttl and f.key in SEARCH_URLS:
            return f.key
        for ts, cmd, _ in reversed(self.history):
            if now - ts >= self.ttl:
                break
            m = re.search(r"\bon (" + "|".join(re.escape(k) for k in SEARCH_URLS) + r")$", cmd)
            if m:
                return m.group(1)
        return None

    def on_screen_key(self) -> str:
        scr = self.screen_focus()
        return scr.key if scr else ""

    # ---- history -------------------------------------------------------------------
    NOT_REPEATABLE = re.compile(r"^(?:stop|again|repeat|yes|no|what|who|how|why|when|where|which|show|read|time|date)\b|"
                                r"^(?:do it again|do that again)")

    def record(self, command: str, reply: str | None, actionable: bool = True) -> None:
        self.history.append((time.time(), command, reply or ""))
        if actionable and not self.NOT_REPEATABLE.match(command) and looks_like_command(command):
            self.last_action = command

    def describe(self) -> str:
        """One short paragraph for the language model: what the user and Jarvis have been doing."""
        now, bits = time.time(), []
        f = self.focus
        if f and now - f.ts < self.ttl:
            bits.append("Last thing opened: %s (%s)." % (f.label, f.kind))
        scr = self.screen_focus()
        if scr:
            bits.append("Foreground window: %s." % scr.label)
        recent = [c for ts, c, _ in self.history if now - ts < self.ttl][-5:]
        if recent:
            bits.append("Recent commands: " + "; ".join(recent) + ".")
        return " ".join(bits) or "No recent computer activity."

    # ---- pending questions ---------------------------------------------------------
    def confirm(self, prompt: str, fn: Callable[[], str], secs: float = 25) -> str:
        self.pending = Pending("confirm", fn, time.time() + secs)
        return prompt

    def ask_slot(self, prompt: str, build: Callable[[str], str], secs: float = 20) -> str:
        """Ask for a missing piece ("For how long?"); the next utterance is passed to build() -> a full command."""
        self.pending = Pending("slot", build, time.time() + secs)
        return prompt

    def _take_pending(self, t: str) -> Optional[Resolution]:
        p, self.pending = self.pending, None
        if not p or time.time() > p.expires:
            return None
        if p.kind == "confirm":
            if YES.match(t):
                return Resolution(reply=p.fn())
            if NO.match(t):
                return Resolution(reply="Okay, cancelled.")
            return None
        if looks_like_command(t) and t.split()[0] in ("open", "close", "stop", "cancel", "launch", "play", "lock"):
            return None                       # the user moved on to a different command
        if NO.match(t):
            return Resolution(reply="Okay.")
        return Resolution(text=p.fn(t))

    # ---- the resolver --------------------------------------------------------------
    _CLOSE_REF = re.compile(r"^(?:close|exit|quit|kill|shut)(?: down)? (?:it|that|this|them|that one|this one|the same)$")
    _OPEN_REF = re.compile(r"^(?:open|launch|start|reopen|bring up)(?: it| that| this| that one)?(?: again| back)$|"
                           r"^(?:open|launch|start|reopen|bring up) (?:it|that|this|that one)(?: again)?$")
    _AGAIN = re.compile(r"^(?:again|do it again|do that again|one more time|once more|same again|repeat the (?:last )?command|"
                        r"repeat the last (?:thing|action))$")

    def resolve(self, t: str) -> Optional[Resolution]:
        """Rewrite follow-up phrases into full commands, or answer them directly. None = nothing to resolve."""
        if self.pending:
            r = self._take_pending(t)
            if r:
                return r
        if self._AGAIN.match(t):
            return Resolution(text=self.last_action) if self.last_action else \
                Resolution(reply="There is nothing to repeat yet.")
        if self._CLOSE_REF.match(t):
            ref = self.referent()
            if not ref:
                return Resolution(reply="Close what? Tell me which app.")
            if ref.kind == "site":
                if ref.key == self.on_screen_key():
                    return Resolution(text="close tab")                 # it is the tab in front: close just that
                return Resolution(reply="I can't see %s in front. Bring it forward and say close tab." % ref.label)
            return Resolution(text="close " + ref.key)
        if self._OPEN_REF.match(t):
            ref = self.referent()
            if ref:
                return Resolution(text="open " + ref.key)
            return Resolution(reply="Open what?")
        return None
