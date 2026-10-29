"""Voice / text command skills.

`route(ctx, text)` normalises the sentence, strips the wake word, and runs the first matching skill.
A skill returns the sentence to speak ("" = handled silently) or None to say "not mine, keep looking".
If nothing matches, the caller hands the sentence to the AI brain.
"""
from __future__ import annotations

import ast
import difflib
import math
import operator
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from . import dialog as dlg
from . import browser, net, pcinfo, services, winctl
from .dialog import SEARCH_URLS, canon_site, search_url

IS_WIN = os.name == "nt"
WAKE_WORDS = ("jarvis", "jarvas", "jervis", "jarves", "jarvice", "jarvus", "gervais", "travis", "jarvi")

ALIASES = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe", "paint": "mspaint.exe",
    "wordpad": "write.exe", "command prompt": "cmd.exe", "cmd": "cmd.exe", "terminal": "cmd.exe",
    "task manager": "taskmgr.exe", "file explorer": "explorer.exe", "explorer": "explorer.exe",
    "my computer": "shell:MyComputerFolder", "this pc": "shell:MyComputerFolder",
    "computer": "shell:MyComputerFolder", "pc": "shell:MyComputerFolder", "this computer": "shell:MyComputerFolder",
    "my pc": "shell:MyComputerFolder", "control panel": "control.exe", "settings": "ms-settings:",
    "snipping tool": "snippingtool.exe", "word": "winword", "microsoft word": "winword", "ms word": "winword",
    "excel": "excel", "microsoft excel": "excel", "powerpoint": "powerpnt", "chrome": "chrome",
    "google chrome": "chrome", "edge": "msedge", "firefox": "firefox", "vs code": "code",
    "visual studio code": "code", "vscode": "code",
}
PROCESS = {"winword": "winword.exe", "excel": "excel.exe", "powerpnt": "powerpnt.exe", "chrome": "chrome.exe",
           "msedge": "msedge.exe", "firefox": "firefox.exe", "code": "code.exe",
           "ms-settings:": "systemsettings.exe"}
SITES = {
    # search / google
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "maps": "https://maps.google.com", "drive": "https://drive.google.com", "translate": "https://translate.google.com",
    "calendar": "https://calendar.google.com", "docs": "https://docs.google.com/document",
    "sheets": "https://docs.google.com/spreadsheets", "slides": "https://docs.google.com/presentation",
    "google photos": "https://photos.google.com", "google news": "https://news.google.com", "meet": "https://meet.google.com",
    "google images": "https://images.google.com", "google scholar": "https://scholar.google.com",
    "youtube music": "https://music.youtube.com", "bing": "https://www.bing.com", "duckduckgo": "https://duckduckgo.com",
    # social media
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com", "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com", "whatsapp": "https://web.whatsapp.com", "tiktok": "https://www.tiktok.com",
    "snapchat": "https://web.snapchat.com", "reddit": "https://www.reddit.com", "pinterest": "https://www.pinterest.com",
    "telegram": "https://web.telegram.org", "discord": "https://discord.com/app", "messenger": "https://www.messenger.com",
    "threads": "https://www.threads.net", "twitch": "https://www.twitch.tv", "quora": "https://www.quora.com",
    "medium": "https://medium.com", "tumblr": "https://www.tumblr.com", "snapchat web": "https://web.snapchat.com",
    # AI
    "chatgpt": "https://chat.openai.com", "claude": "https://claude.ai", "gemini": "https://gemini.google.com",
    "groq": "https://console.groq.com", "perplexity": "https://www.perplexity.ai", "huggingface": "https://huggingface.co",
    "copilot": "https://copilot.microsoft.com", "deepseek": "https://chat.deepseek.com",
    # media / shopping
    "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com", "soundcloud": "https://soundcloud.com",
    "imdb": "https://www.imdb.com", "amazon": "https://www.amazon.com", "daraz": "https://www.daraz.pk",
    "olx": "https://www.olx.com.pk", "ebay": "https://www.ebay.com", "aliexpress": "https://www.aliexpress.com",
    # work / learning / dev
    "github": "https://github.com", "stack overflow": "https://stackoverflow.com", "kaggle": "https://www.kaggle.com",
    "fiverr": "https://www.fiverr.com", "upwork": "https://www.upwork.com", "outlook": "https://outlook.office.com/mail",
    "teams": "https://teams.microsoft.com", "zoom": "https://zoom.us/join", "slack": "https://app.slack.com",
    "notion": "https://www.notion.so", "canva": "https://www.canva.com", "figma": "https://www.figma.com",
    "trello": "https://trello.com", "leetcode": "https://leetcode.com", "geeksforgeeks": "https://www.geeksforgeeks.org",
    "w3schools": "https://www.w3schools.com", "udemy": "https://www.udemy.com", "coursera": "https://www.coursera.org",
    "colab": "https://colab.research.google.com", "wikipedia": "https://www.wikipedia.org",
    "paypal": "https://www.paypal.com", "binance": "https://www.binance.com",
}
SOCIAL_DEFAULT = ("facebook", "instagram", "whatsapp", "twitter", "linkedin", "youtube")
SHORTCUTS = {
    "select all": ("ctrl", "a"), "copy": ("ctrl", "c"), "paste": ("ctrl", "v"), "cut": ("ctrl", "x"),
    "save": ("ctrl", "s"), "undo": ("ctrl", "z"), "redo": ("ctrl", "y"), "new tab": ("ctrl", "t"),
    "close tab": ("ctrl", "w"), "close window": ("alt", "f4"), "show desktop": ("win", "d"),
    "minimize all": ("win", "d"), "switch window": ("alt", "tab"), "refresh": ("f5",),
    "new line": ("enter",), "next line": ("enter",),
    # browser / window navigation
    "go back": ("alt", "left"), "go forward": ("alt", "right"), "scroll down": ("pagedown",),
    "scroll up": ("pageup",), "page down": ("pagedown",), "page up": ("pageup",),
    "scroll to top": ("ctrl", "home"), "scroll to the top": ("ctrl", "home"),
    "scroll to bottom": ("ctrl", "end"), "scroll to the bottom": ("ctrl", "end"),
    "next tab": ("ctrl", "tab"), "previous tab": ("ctrl", "shift", "tab"), "reopen tab": ("ctrl", "shift", "t"),
    "zoom in": ("ctrl", "plus"), "zoom out": ("ctrl", "minus"), "reset zoom": ("ctrl", "0"),
    "new window": ("ctrl", "n"), "print": ("ctrl", "p"), "reload": ("f5",),
    "minimize": ("win", "down"), "minimise": ("win", "down"), "minimize window": ("win", "down"),
    "minimize this window": ("win", "down"), "maximize": ("win", "up"), "maximise": ("win", "up"),
    "maximize window": ("win", "up"), "maximize this window": ("win", "up"), "restore window": ("win", "down"),
    "task view": ("win", "tab"), "show all windows": ("win", "tab"),
}
KEYS = {"enter", "tab", "escape", "esc", "space", "backspace", "delete", "up", "down", "left", "right", "home",
        "end", "pageup", "pagedown"} | {chr(c) for c in range(97, 123)} | {str(n) for n in range(10)} | \
       {"f%d" % n for n in range(1, 13)}
JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are ten kinds of people: those who understand binary and those who do not.",
    "A SQL query walks into a bar, walks up to two tables and asks: may I join you?",
    "I told my computer I needed a break. Now it won't stop sending me Kit Kat ads.",
    "Why was the function sad? It never got a return.",
    "There is no place like 127.0.0.1.",
    "I'd tell you a joke about recursion, but first I'd have to tell you a joke about recursion.",
]

_SKILLS: list = []


def skill(pattern: str, chat: bool = False):
    rx = re.compile(pattern)

    def deco(fn):
        _SKILLS.append((rx, fn, chat))
        return fn
    return deco


# ============================================================================ text helpers
def normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "").replace("'", "")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"[^\w\s\.%\+\-\*/\^]", " ", t)
    t = re.sub(r"\.+(?=\s|$)", " ", t)                 # sentence-ending full stops ("open settings.") - Whisper adds them
    t = re.sub(r"\s+", " ", t).strip()
    return t


_WAKE = "|".join(WAKE_WORDS)
_WAKE_HEAD = re.compile(r"^(?:(?:hey|ok|okay|hi|hello|yo)\s+)?(?:%s)\b[\s,]*" % _WAKE)
_WAKE_TAIL = re.compile(r"[\s,]*\b(?:%s)$" % _WAKE)


def strip_wake(t: str) -> str:
    t = _WAKE_HEAD.sub("", t)
    t = _WAKE_TAIL.sub("", t)
    t = re.sub(r"\b(please|can you|could you|would you|will you|kindly)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_RAW_HEAD = re.compile(r"^\W*(?:(?:hey|ok|okay|hi|hello|yo)\W+)?(?:%s)\b[\s,.:;!?-]*" % _WAKE, re.I)
_RAW_TAIL = re.compile(r"[\s,.:;!?-]*\b(?:%s)\W*$" % _WAKE, re.I)


def strip_wake_raw(text: str) -> str:
    """Remove the wake word but keep the user's capitalisation and punctuation (for the AI)."""
    t = _RAW_TAIL.sub("", _RAW_HEAD.sub("", text.strip())).strip()
    return t or text.strip()


def has_wake_word(text: str) -> bool:
    toks = re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))
    for i, tok in enumerate(toks):
        if tok in WAKE_WORDS:
            return True
        if i < 3 and len(tok) >= 5 and difflib.SequenceMatcher(None, tok, "jarvis").ratio() >= 0.8:
            return True
    return False


_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
         "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90}
_UNIT = {"h": 3600, "m": 60, "s": 1}


def parse_duration(s: str):
    """'5 minutes', 'an hour and a half', 'half an hour', '1 hour 30 minutes' -> seconds (or None)."""
    s = s.lower()
    if re.search(r"half an hour", s):
        return 1800
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?|%s)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)" %
                                "|".join(_NUMS), s):
        n = float(num) if num[0].isdigit() else _NUMS[num]
        total += n * _UNIT[unit[0]]
        found = True
    if found and re.search(r"and a half", s):
        total += {"h": 1800, "m": 30, "s": 0}[re.search(r"(hour|hr|minute|min|second|sec)", s).group(1)[0]]
    return int(total) if found and total > 0 else None


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append("%d hour%s" % (h, "" if h == 1 else "s"))
    if m:
        parts.append("%d minute%s" % (m, "" if m == 1 else "s"))
    if s and not h:
        parts.append("%d second%s" % (s, "" if s == 1 else "s"))
    return " ".join(parts) or "0 seconds"


# ---- safe calculator -----------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "sin": lambda x: math.sin(math.radians(x)),
          "cos": lambda x: math.cos(math.radians(x)), "tan": lambda x: math.tan(math.radians(x)),
          "log": math.log10, "ln": math.log}
_CONST = {"pi": math.pi, "e": math.e}


def _ev(n):
    if isinstance(n, ast.Expression):
        return _ev(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 1000:
            raise ValueError("exponent too large")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        return -_ev(n.operand) if isinstance(n.op, ast.USub) else _ev(n.operand)
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1:
        return _FUNCS[n.func.id](_ev(n.args[0]))
    raise ValueError("unsupported")


def spoken_to_expr(s: str) -> str:
    s = s.lower()
    num = r"(\d+(?:\.\d+)?)"
    s = re.sub(num + r"\s*(?:percent|%)\s*of\s*" + num, r"(\1/100*\2)", s)
    s = re.sub(r"(?:square root of|root of)\s*" + num, r"sqrt(\1)", s)
    for a, b in (("multiplied by", "*"), ("times", "*"), ("divided by", "/"), ("over", "/"), ("plus", "+"),
                 ("minus", "-"), ("to the power of", "**"), ("power", "**"), ("squared", "**2"),
                 ("cubed", "**3"), ("modulo", "%"), ("mod", "%"), ("equals", ""), ("what is", ""), ("whats", ""), ("the", ""), ("is", "")):
        s = re.sub(r"\b%s\b" % re.escape(a), " %s " % b, s)
    s = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", s)
    s = s.replace("^", "**")
    return re.sub(r"\s+", " ", s).strip()


def calculate(spoken: str):
    expr = spoken_to_expr(spoken)
    if not re.search(r"\d", expr) or not re.fullmatch(r"[\d\s\.\+\-\*/%\(\)a-z]+", expr):
        return None
    if not re.search(r"[\+\-\*/%]|sqrt|sin|cos|tan|log|ln|abs|round", expr):
        return None
    try:
        val = _ev(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    if isinstance(val, float):
        val = int(val) if val.is_integer() and abs(val) < 1e15 else float("%.8g" % val)
    return val


# ============================================================================ app launching
def launch(target: str, fallback: bool = False) -> bool:
    try:
        if IS_WIN:
            os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        if fallback and IS_WIN:
            subprocess.Popen('start "" "%s"' % target, shell=True)
            return True
        return False


class AppIndex:
    """Index of every launchable app: Start-menu apps (classic + Microsoft Store) and Start-Menu/Desktop shortcuts,
    plus the 'installed programs' registry list, so ANY installed app can be opened, counted or looked up by name."""

    def __init__(self):
        self.index: dict[str, str] = {}
        self.start_names: list[str] = []          # what the Start menu shows (what people call "apps")
        self.programs: list[str] = []             # Control-Panel style installed programs
        self.ready = False

    def build(self):
        idx = {}
        roots = [os.path.join(os.environ.get("ProgramData", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
                 os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
                 os.path.join(os.path.expanduser("~"), "Desktop")]
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for fn in files:
                    if fn.lower().endswith((".lnk", ".url")):
                        name = os.path.splitext(fn)[0].lower()
                        if "uninstall" not in name:
                            idx.setdefault(name, os.path.join(dp, fn))
        self.index = dict(idx)                      # shortcuts are usable immediately
        start = pcinfo.start_apps() if IS_WIN else {}
        for name, appid in start.items():
            if "uninstall" not in name and appid:
                idx[name] = "shell:AppsFolder\\" + appid
        self.index = idx
        self.start_names = sorted(start, key=str.lower) if start else sorted(idx, key=str.lower)
        self.programs = pcinfo.registry_programs()
        self.ready = True

    def find(self, name: str):
        idx = self.index
        if name in idx:
            return idx[name]
        cands = [k for k in idx if name in k]
        if cands:
            return idx[min(cands, key=len)]
        m = difflib.get_close_matches(name, list(idx), n=1, cutoff=0.6)
        return idx[m[0]] if m else None

    def installed(self, name: str) -> str | None:
        """Display name of an installed app/program matching `name`, or None."""
        name = name.lower().strip()
        pool = [n for n in self.start_names] + [n.lower() for n in self.programs]
        hit = next((n for n in pool if name == n), None) or next((n for n in pool if name in n), None)
        if hit:
            return hit
        m = difflib.get_close_matches(name, pool, n=1, cutoff=0.75)
        return m[0] if m else None


APPS = AppIndex()


def _focus(ctx, kind: str, key: str, label: str | None = None):
    d = getattr(ctx, "dialog", None)
    if d:
        d.set_focus(kind, key, label)


_INCOG = re.compile(r"\s+(?:in|on|with)\s+(?:an?\s+)?(?:incognito|private|inprivate)(?:\s+(?:mode|window|tab))?$|"
                   r"\s+(?:incognito|privately)$")
_IN_BROWSER = re.compile(r"\s+(?:in|on|with|using)\s+(?:google\s+)?(?:chrome|the browser|browser)$")
_SPLIT_NAMES = re.compile(r"\s*(?:,|\band\b|&|\bplus\b)\s*")
_SOCIAL_WORDS = re.compile(r"^(?:all\s+)?(?:my\s+|the\s+|of\s+my\s+)?(?:all\s+)?social(?:\s+media)?(?:\s+(?:sites|apps|accounts|websites|platforms|networks|medias))?$|"
                           r"^(?:all\s+)?(?:my\s+)?social medias?$")


def site_key(name: str) -> str | None:
    """The SITES key a spoken name refers to (exact, alias, or a close mis-hearing like 'instagrm'), else None."""
    key = canon_site(re.sub(r"^(?:the |my )", "", name.strip()))
    if key in SITES:
        return key
    if len(key) >= 5 and " " not in key:
        m = difflib.get_close_matches(key, [k for k in SITES if " " not in k], n=1, cutoff=0.84)
        if m:
            return m[0]
    return None


def site_list(text: str) -> list[str]:
    """'facebook instagram and youtube' -> ['facebook', 'instagram', 'youtube'] - only if EVERY word is a known site
    (speech recognition drops the commas). Anything else returns [] so 'open my resume' is never mistaken for sites."""
    keys: list[str] = []
    for part in (x for x in _SPLIT_NAMES.split(text) if x.strip()):
        words, i = part.split(), 0
        while i < len(words):
            for j in range(len(words), i, -1):                      # longest known name first ("stack overflow")
                k = site_key(" ".join(words[i:j]))
                if k:
                    keys.append(k)
                    i = j
                    break
            else:
                return []
    return list(dict.fromkeys(keys))


def social_list(ctx=None) -> list[str]:
    raw = getattr(getattr(ctx, "cfg", None), "social", "") or ""
    keys = [site_key(x) for x in re.split(r"[,;]", raw) if x.strip()]
    return [k for k in dict.fromkeys(keys) if k] or list(SOCIAL_DEFAULT)


def open_sites(keys: list[str], ctx=None, incognito: bool = False) -> str:
    """Open several websites, one browser tab each, with a short pause so they open in order."""
    for i, k in enumerate(keys):
        browser.open_url(SITES[k], incognito=incognito)
        if i + 1 < len(keys):
            time.sleep(0.35)
    _focus(ctx, "site", keys[-1], keys[-1])
    names = keys
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return "Opening %s%s." % (listed, " in a private window" if incognito else "")


def open_target(name: str, ctx=None) -> str:
    name = re.sub(r"\s+again$", "", name.strip())                   # "open chrome again"
    name = re.sub(r"^(the |my )", "", name.strip())
    incognito = bool(_INCOG.search(name))
    name = _INCOG.sub("", name)
    name = _IN_BROWSER.sub("", name)
    if not site_key(name):                                          # "whats app" is a site name, "calculator app" is not
        name = re.sub(r"( app| application| software| program| website| site| page| tab)$", "", name).strip()
        if name not in ("browser", "web browser") and name.endswith(" browser"):      # "chrome browser" -> chrome
            name = name[:-len(" browser")].strip()
    name = name.replace(" dot ", ".")
    if _SOCIAL_WORDS.match(name):                                   # "open all social media"
        return open_sites(social_list(ctx), ctx, incognito)
    keys = site_list(name)                                          # "open facebook, instagram and youtube"
    if len(keys) > 1:
        return open_sites(keys, ctx, incognito)
    key = canon_site(name)
    if key == "gmail" and ctx is not None and getattr(ctx.cfg, "mail", "gmail") == "outlook":
        key = "outlook"
    if key in SITES:
        return open_sites([key], ctx, incognito)
    folder = re.sub(r"( folder| directory)$", "", name)
    if folder in pcinfo.FOLDERS and os.path.isdir(pcinfo.FOLDERS[folder]):
        launch(pcinfo.FOLDERS[folder])
        _focus(ctx, "folder", folder, folder)
        return "Opening your %s folder." % folder
    if re.fullmatch(r"[\w\-]+(\.[\w\-]+)+", name):
        browser.open_url("https://" + name, incognito=incognito)
        _focus(ctx, "site", name, name)
        return "Opening %s." % name
    if name in ALIASES:
        launch(ALIASES[name], fallback=True)
        _focus(ctx, "app", name, name)
        return "Opening %s." % name
    fuzzy = site_key(name) if name not in APPS.index else None       # a misheard site name, e.g. "instagrm"
    if fuzzy and not any(name in k for k in APPS.index):
        return open_sites([fuzzy], ctx, incognito)
    path = APPS.find(name)
    if path and launch(path):
        shown = os.path.splitext(os.path.basename(path))[0] if not path.startswith("shell:") else name
        _focus(ctx, "app", name, shown)
        return "Opening %s." % shown
    return "Sorry, I could not find an app called %s." % name


def close_app(name: str, ctx=None, force: bool = False) -> str:
    name = re.sub(r"( app| application| software| program| website| site)$", "", name.strip()).strip()
    key = canon_site(name)
    if key in SITES or key in SEARCH_URLS:                      # a website lives in a browser tab, not a process
        d = getattr(ctx, "dialog", None)
        if d and d.on_screen_key() == key and winctl.supported():
            winctl.hotkey("ctrl", "w")
            return "Closed the %s tab." % key
        return "%s is a website. Bring its tab to the front and say close tab." % key.title()
    target = ALIASES.get(name)
    if target and ":" in target and target not in PROCESS:
        return "I cannot close that one."
    if target in PROCESS and ":" in target:
        force = True                                                # Store/UWP apps ignore a polite close
    if not IS_WIN:
        return "Closing apps is only supported on Windows."
    exe = PROCESS.get(target, target) if target else name.replace(" ", "") + ".exe"
    if not exe.endswith(".exe"):
        exe += ".exe"
    cmd = ["taskkill", "/im", exe] + (["/f"] if force else [])      # without /f the app may ask to save first
    res = subprocess.run(cmd, capture_output=True, creationflags=0x08000000)
    if res.returncode == 0:
        return ("Force closed %s." if force else "Closing %s.") % name
    return "I could not find %s running." % name


# ============================================================================ skills
def _need_win(ctx):
    return None if winctl.supported() else "That needs Windows."


# ---- session / meta -----------------------------------------------------------
# Control words are special: the app also calls control_intent() directly from the microphone thread, so
# "stop" and "Jarvis closed" work even while Jarvis is talking or busy thinking.
_STOP_RX = re.compile(
    r"^(?:(?:i said|just|ok|okay|hey|please|jarvis)\s+)*"
    r"(?:stop|stop it|stop that|stop talking|stop speaking|stop now|enough|enough now|thats enough|be quiet|quiet|"
    r"silence|shut up|shush|hush|cancel|cancel that|hold on|wait|wait a second|wait a moment|never ?mind|"
    r"that will do|thats ok|thats okay)(?:\s+(?:it|that|now|please|jarvis|stop|talking|speaking))*$")
# phrases that can only mean "end Jarvis" ...
_EXIT_RX = re.compile(
    r"^(?:exit|quit|closet|bye|bye bye|goodbye|good bye|see you|see you later|shut ?down jarvis|close jarvis|closed jarvis|"
    r"close yourself|close down jarvis|terminate jarvis|power off|go offline|end (?:the )?session|close (?:the )?session|"
    r"closed (?:the )?session|turn yourself off|turn off jarvis|exit jarvis|quit jarvis|jarvis (?:exit|quit|close|closed)|"
    r"exit (?:the )?session|quit (?:the )?session)$")
# ... and words that mean it only when the sentence was addressed to him ("Jarvis, closed")
_EXIT_ADDRESSED_RX = re.compile(r"^(?:be )?(?:close|closed|closet|close down|closed down|shut ?down|shut down now|shut off|"
                                r"terminate|turn off|power down|finish|end|shut yourself down|close yourself down)$")


_FILLER = re.compile(r"^(?:(?:i said|i told you to|i want you to|i need you to|i asked you to|i wanna|i want to|can you|"
                     r"could you|would you|will you|please|just|go ahead and|you to|to|ok|okay|so|yeah|yes|well|now|"
                     r"hey|yo|then|also)\s+)+")
_POLITE_TAIL = re.compile(r"(?:\s+(?:please|pls|for me|now|right now|quickly|real quick|thanks|thank you|sir|buddy|bro|man|"
                          r"mate|if you can|will you|would you|can you|could you))+$")
_PHRASAL = re.compile(r"^(open|start|launch|run|bring|pull|fire|turn) (?:up|on) (?=\S)")


def strip_filler(t: str) -> tuple[str, bool]:
    """'i said open chrome please' -> ('open chrome', True). The flag says a filler lead-in was removed."""
    had = False
    m = _FILLER.match(t)
    if m and m.end() < len(t):
        t, had = t[m.end():], True
    t = _POLITE_TAIL.sub("", t) or t
    if t.startswith("turn on "):                       # "turn on wifi" must stay as it is
        return t, had
    t = _PHRASAL.sub(r"\1 ", t)                         # "open up chrome" -> "open chrome"
    return t, had


def control_intent(t: str, addressed: bool = True):
    """'stop' | 'exit' | None for an already-normalised, wake-word-stripped sentence."""
    t, had_filler = strip_filler(t)
    addressed = addressed or had_filler
    if _STOP_RX.match(t):
        return "stop"
    if _EXIT_RX.match(t) or (addressed and _EXIT_ADDRESSED_RX.match(t)):
        return "exit"
    return None


def control_of(text: str, addressed: bool | None = None):
    """Same as control_intent() but starting from the raw heard sentence."""
    return control_intent(strip_wake(normalize(text)), has_wake_word(text) if addressed is None else addressed)


@skill(r"^[\w ]+$")
def _exit(ctx, m, t):
    if control_intent(t, getattr(ctx, "addressed", True)) != "exit":
        return None
    ctx.quit_later(2.2)
    return "Goodbye. Shutting down."


@skill(r"^[\w ]+$")
def _stop(ctx, m, t):
    if control_intent(t) != "stop":
        return None
    interrupt = getattr(ctx, "interrupt", None)
    if interrupt:
        interrupt(listen=True)
    else:                                       # minimal context (tests / old callers)
        ctx.speaker.stop()
        ctx.abort_typing.set()
    return ""


@skill(r"^(?:stop|pause|end|kill) (?:the )?(?:music|song|songs|video|videos|playback|media|player)$")
def _stop_media(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.press("playpause")
    return "Done."


@skill(r"^(?:hide|minimi[sz]e)(?: yourself| jarvis| the hud| your window| the jarvis window)$|^hide(?: the)? hud$|"
       r"^(?:go|run|work|stay|continue|move)(?: to| in| into)?(?: the)? background(?: mode)?$|^background mode$|"
       r"^(?:hide|close) (?:the )?(?:hud|jarvis window)$")
def _hide(ctx, m, t):
    hide = getattr(ctx, "hide_window", None)
    if not hide:
        return None
    hide()
    return "Going to the background. I'm still listening. Say Jarvis, show yourself, when you want me back."


@skill(r"^(?:show|unhide|restore|bring up|open)(?: yourself| jarvis| the hud| your window| the jarvis window)$|"
       r"^(?:show|open) (?:the )?hud$|^come (?:back|out)$|^(?:leave|exit) (?:the )?background(?: mode)?$")
def _show(ctx, m, t):
    show = getattr(ctx, "show_window", None)
    if not show:
        return None
    show()
    return "Here I am."


@skill(r"^(?:repeat that|say that again|repeat|what did you say)$")
def _repeat(ctx, m, t):
    return ctx.last_reply or "I have not said anything yet."


@skill(r"^(?:go to |go on )?(?:standby|stand by|sleep mode)$|^that is all$|^thats all$")
def _standby(ctx, m, t):
    ctx.awake_until = 0
    return "Standing by."


@skill(r"^(?:stop listening|mute (?:the )?(?:mic|microphone)|turn off (?:the )?(?:mic|microphone))$")
def _mic_off(ctx, m, t):
    ctx.set_mic(False)
    return "Microphone muted. Use the button to bring me back."


@skill(r"^(?:turn |switch )?(?:the )?wake ?word (on|off)$")
def _wake(ctx, m, t):
    ctx.set_wake(m.group(1) == "on")
    return "Wake word is on. Say my name first." if ctx.wake_on else "I will listen continuously."


@skill(r"^(?:always listen|listen all the time)$")
def _always(ctx, m, t):
    ctx.set_wake(False)
    return "I will listen continuously."


@skill(r"^(?:clear|wipe) (?:the )?(?:chat|log|screen|transcript|history)$")
def _clear(ctx, m, t):
    ctx.hud_post("clear")
    ctx.mem.forget_conversation()
    return "Cleared."


@skill(r"^(?:go |enter |switch to |make it |make this )?full ?screen(?: mode| video)?$|^(?:exit|leave) full ?screen$")
def _fullscreen(ctx, m, t):
    leaving = t.startswith(("exit", "leave"))
    d = getattr(ctx, "dialog", None)
    front = d.on_screen_key() if d else ""
    if front and winctl.supported():                            # something else is in front: act on that
        if front == "youtube":
            winctl.press("f")
        else:
            winctl.press("f11")
        return "Done."
    ctx.hud_post("fullscreen", not leaving)
    return "Done."


@skill(r"^(?:run |start |begin )?(?:the )?(?:demo|demonstration|showcase)(?: mode)?$|^introduce yourself to (?:the )?(?:audience|everyone|crowd)$")
def _demo(ctx, m, t):
    ctx.run_demo()
    return ""


@skill(r"^(?:what can you do|help|commands|what are your commands|show help|what are your features)$")
def _help(ctx, m, t):
    return ("I can chat and answer questions, open and close apps and websites, search the site you are on, "
            "compose emails, count and list your installed apps, show what is running, check disk space, "
            "set timers and reminders, take notes, do maths, type for you, control volume, brightness and media, "
            "take screenshots, and switch windows. Say stop and I go quiet and listen. Say Jarvis closed to end me.")


@skill(r"^my name is (.+)$|^call me (.+)$|^i am called (.+)$")
def _setname(ctx, m, t):
    name = next(g for g in m.groups() if g).strip().title()
    ctx.mem.set_name(name)
    return "Pleasure to meet you, %s. I'll remember that." % name


@skill(r"^(?:what is my name|whats my name|who am i|do you know my name)$")
def _getname(ctx, m, t):
    n = ctx.mem.name or ctx.cfg.user_name
    return "You are %s." % n if n else "You haven't told me yet. Say: my name is, followed by your name."


# ---- web searches: one skill, and the *context* decides where ("search X" after "open youtube" = on YouTube) ------
_SITE_WORDS = "|".join(sorted((re.escape(k) for k in list(SEARCH_URLS) + list(dlg.SITE_ALIASES)), key=len, reverse=True))
_ON_SITE = re.compile(r"\s+(?:on|in|at|from|using|with|via)\s+(?:the\s+|my\s+)?(%s)(?:\s+(?:website|site|app))?$" % _SITE_WORDS)
_ON_WEB = re.compile(r"\s+(?:on|in|over)\s+(?:the\s+)?(?:browser|web|internet)$|\s+online$")
_GENERIC_MEDIA = {"music", "song", "songs", "video", "videos", "it", "something", "media", "the music", "the song",
                  "the video", "playing", "some music", "a song", "that"}


def web_search(ctx, query: str, site: str) -> str:
    site = canon_site(site)
    if site not in SEARCH_URLS:
        site = "google"
    browser.open_url(search_url(site, query))
    _focus(ctx, "site", site, site)
    return "Showing Google results for %s." % query if site == "google" else "Searching %s for %s." % (
        {"youtube": "YouTube", "github": "GitHub", "linkedin": "LinkedIn"}.get(site, site.title()), query)


@skill(r"^(?:search|find|look up|lookup|look for|google|play|watch|youtube)\b(?:\s+for)?(?:\s+(.+))?$")
def _search(ctx, m, t):
    verb, rest = t.split()[0], (m.group(1) or "").strip()
    if verb == "find" and re.match(r"out\b", rest):               # "find out who won" is a question, not a search
        return None
    rest = re.sub(r"^(?:for|about)\s+", "", rest)
    d = getattr(ctx, "dialog", None)
    if not rest:
        if verb in ("youtube",):
            return open_target("youtube", ctx)
        if verb in ("play", "watch"):
            return None                                            # plain play/pause handled below
        return d.ask_slot("What should I search for?", lambda q: "search " + q) if d else "What should I search for?"
    site = None
    ex = _ON_SITE.search(rest)
    if ex:
        site, rest = canon_site(ex.group(1)), rest[:ex.start()].strip()
    elif _ON_WEB.search(rest):
        site, rest = "google", _ON_WEB.sub("", rest).strip()
    elif verb == "google":
        site = "google"
    elif verb == "youtube":
        site = "youtube"
    if not rest:
        return None
    if verb in ("play", "watch") and rest in _GENERIC_MEDIA:
        return None
    if site is None:
        site = d.search_target() if d else None                   # <- the link to the previous command
        if site is None or (verb in ("play", "watch") and site not in ("youtube", "spotify", "netflix")):
            site = "youtube" if verb in ("play", "watch") else "google"
    return web_search(ctx, rest, site)


# ---- email -------------------------------------------------------------------------------------------------
def _spoken_address(s: str) -> str:
    s = re.sub(r"\s+at\s+(?:the\s+rate\s+)?", "@", s.strip())
    s = re.sub(r"\s+dot\s+", ".", s)
    return s.replace(" ", "") if "@" in s else s


def mail_url(cfg, to: str = "", subject: str = "", body: str = "") -> str:
    q = urllib.parse.quote
    kind = getattr(cfg, "mail", "gmail")
    if kind == "outlook":
        return "https://outlook.office.com/mail/deeplink/compose?to=%s&subject=%s&body=%s" % (q(to), q(subject), q(body))
    if kind == "default":
        return "mailto:%s?subject=%s&body=%s" % (q(to), q(subject), q(body))
    return "https://mail.google.com/mail/?view=cm&fs=1&to=%s&su=%s&body=%s" % (q(to), q(subject), q(body))


@skill(r"^(?:send|send it|send this|send the (?:mail|email|message)|send that)$")
def _send_mail(ctx, m, t):
    d = getattr(ctx, "dialog", None)
    ref = d.referent() if d else None
    front = d.on_screen_key() if d else ""
    if not ((ref and ref.key in dlg.MAIL_KEYS) or front in dlg.MAIL_KEYS):
        return None
    if _need_win(ctx):
        return _need_win(ctx)
    return d.confirm("Send the email now? Say yes or no.", lambda: (winctl.hotkey("ctrl", "enter"), "Sent.")[1])


@skill(r"^(?:(?:compose|write|draft|create|make|start|begin|send|prepare)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|another\s+)?"
       r"(?:new\s+|fresh\s+|blank\s+)?|(?:open|launch)\s+(?:a\s+|an\s+)(?:new\s+|blank\s+)(?:\w+\s+)?|new\s+)"
       r"(?:e ?mail|mail|gmail|(?<=new )message)(?:\s+(.*))?$|^compose$")
def _compose_mail(ctx, m, t):
    rest = (m.group(1) or "") if m.re.groups else ""
    if t == "compose":
        d = getattr(ctx, "dialog", None)
        ref = d.referent() if d else None
        if not (ref and ref.key in dlg.MAIL_KEYS):
            return None
    to = re.search(r"\bto\s+(.+?)(?=\s+(?:subject|about|regarding|saying|says|body|message|that says|with)\b|$)", rest)
    subj = re.search(r"\b(?:subject|about|regarding)\s+(.+?)(?=\s+(?:body|saying|says|message|that says)\b|$)", rest)
    body = re.search(r"\b(?:body|saying|says|message|that says|with message)\s+(.+)$", rest)
    addr = ""
    if to:
        raw = to.group(1).strip()
        addr = _spoken_address(raw)
        if "@" not in addr:
            addr = ctx.mem.contact(raw) if hasattr(ctx, "mem") else ""
    browser.open_url(mail_url(ctx.cfg, addr, subj.group(1) if subj else "", body.group(1) if body else ""))
    _focus(ctx, "site", "new email", "your new email")
    if to and not addr:
        return ("Opening a new email. I don't have an address for %s yet. Say: save contact %s as, followed by the "
                "address." % (to.group(1), to.group(1)))
    return "Opening a new email%s." % (" to " + to.group(1) if to else "")


@skill(r"^(?:save|add|remember) (?:a )?contact (.+?) (?:as|at|email|with email|is)\s+(.+)$")
def _save_contact(ctx, m, t):
    addr = _spoken_address(m.group(2))
    if "@" not in addr:
        return "That doesn't sound like an email address. Say it like: ali at gmail dot com."
    ctx.mem.set_contact(m.group(1), addr)
    return "Saved %s." % m.group(1)


# ---- keyboard ------------------------------------------------------------------
@skill(r"^(?:type|dictate)(?: out)?\s+(.+)$")
def _type(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    ctx.type_later(m.group(1))
    return "Typing in two seconds. Click where you want the text."


@skill(r"^(?:press|hit|push)\s+(?:the\s+)?(\w+)(?: key| button)?$")
def _press(ctx, m, t):
    key = m.group(1)
    if key in KEYS and winctl.supported():
        winctl.press(key)
        return "Pressed %s." % key
    return "Which key?" if key not in KEYS else _need_win(ctx)


@skill(r"^(?:open|create|make|start|give me|show)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?(?:new|another)\s+(tab|window)$")
def _new_tab(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.hotkey("ctrl", "t" if m.group(1) == "tab" else "n")
    return "Done."


@skill(r"^(?:%s)$" % "|".join(re.escape(k) for k in SHORTCUTS))
def _shortcut(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.hotkey(*SHORTCUTS[t])
    return "Done."


@skill(r"^(?:pause|resume|play|toggle)(?: the)?(?: music| song| video| media| playback)?$")
def _playpause(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.press("playpause")
    return "Done."


@skill(r"^(?:next|skip)(?: the)?(?: song| track| video)?$|^(?:play )?(?:the )?next (?:video|one)$")
def _next(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    d = getattr(ctx, "dialog", None)
    if "video" in t or (d and d.on_screen_key() == "youtube"):
        winctl.hotkey("shift", "n")                            # YouTube: next video
        return "Next video."
    winctl.press("nexttrack")
    return "Next track."


@skill(r"^(?:previous|go back)(?: song| track)$")
def _prev(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.press("prevtrack")
    return "Previous track."


# ---- eyes and emotions -----------------------------------------------------------
@skill(r"close (?:your )?eyes|go to sleep|^sleep$")
def _sleep(ctx, m, t):
    ctx.face.sleep(True)
    return "Going to sleep. Say wake up when you need me."


@skill(r"^wake(?: up)?$|^open (?:your )?eyes$")
def _wakeup(ctx, m, t):
    ctx.face.sleep(False)
    ctx.awake_until = time.time() + ctx.cfg.follow_up_secs
    return "I am awake."


@skill(r"^wink$|^wink at me$")
def _wink(ctx, m, t):
    ctx.face.blink("right")
    return "Wink."


@skill(r"^blink(?: .*)?$")
def _blink(ctx, m, t):
    n = 3 if re.search(r"three|thrice|\b3\b", t) else (2 if re.search(r"twice|two|\b2\b", t) else 1)
    for i in range(n):
        threading.Timer(i * 0.38, ctx.face.blink).start()
    return "Blinking."


@skill(r"roll (?:your )?eyes|^look around$|spin (?:your )?eyes")
def _roll(ctx, m, t):
    ctx.face.roll(2.8)
    return "Looking around."


@skill(r"^(?:look|glance|turn|move)\b[\w\s]*\b(left|right|up|down|center|centre|straight|forward|front|ahead)$")
def _look(ctx, m, t):
    d = m.group(1)
    vec = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}.get(d, (0, 0))
    ctx.face.look(vec[0], vec[1], 6.0)
    return "Looking %s." % ("straight" if vec == (0, 0) else d)


@skill(r"^(?:be |look |feel |act |get |go |show me |make a )?(?:a |an )?(happy|smile|smiling|angry|mad|sad|cry|surprised|shocked)(?: face)?$")
def _mood(ctx, m, t):
    w = m.group(1)
    mood = {"smile": "happy", "smiling": "happy", "mad": "angry", "cry": "sad", "shocked": "surprised"}.get(w, w)
    ctx.face.mood(mood)
    return {"happy": "I am happy!", "angry": "Grrr. I am angry.", "sad": "I feel sad.",
            "surprised": "Oh! That is surprising."}[mood]


@skill(r"^(?:normal|calm|neutral|reset|relax)(?: down)?$")
def _calm(ctx, m, t):
    ctx.face.reset_mood()
    return "Back to normal."


# ---- timers / reminders / notes --------------------------------------------------
@skill(r"^(?:set |start |create )?(?:a |an )?(?:timer|alarm)(?: for| of)?\s+(.+)$|^(?:set |start )?(?:a |an )?(.+?) timer$")
def _timer(ctx, m, t):
    secs = parse_duration(m.group(1) or m.group(2) or "")
    if not secs:
        d = getattr(ctx, "dialog", None)
        return d.ask_slot("For how long?", lambda s: "set a timer for " + s) if d else "For how long?"
    ctx.add_timer(secs, "Your %s timer is up." % fmt_duration(secs), "timer")
    return "Timer set for %s." % fmt_duration(secs)


@skill(r"^remind me (?:to |about |that )?(.+?) (?:in|after) (.+)$")
def _remind(ctx, m, t):
    secs = parse_duration(m.group(2))
    if not secs:
        return None
    ctx.add_timer(secs, "Reminder: %s." % m.group(1), m.group(1))
    return "I will remind you in %s." % fmt_duration(secs)


@skill(r"^remind me in (.+?) (?:to|about|that) (.+)$")
def _remind2(ctx, m, t):
    secs = parse_duration(m.group(1))
    if not secs:
        return None
    ctx.add_timer(secs, "Reminder: %s." % m.group(2), m.group(2))
    return "I will remind you in %s." % fmt_duration(secs)


@skill(r"^(?:cancel|clear|stop|delete) (?:all |my |the )*(?:timers?|alarms?|reminders?)$")
def _cancel_timers(ctx, m, t):
    n = ctx.cancel_timers()
    return "Cancelled %d timer%s." % (n, "" if n == 1 else "s") if n else "You have no active timers."


@skill(r"^(?:take a note|make a note|note down|note that|note|write down|remember that|add a note)(?: that| to)?\s+(.+)$")
def _note(ctx, m, t):
    ctx.mem.add_note(m.group(1))
    return "Noted."


@skill(r"^(?:read|show|what are)(?: me)?(?: my| the)? notes$|^my notes$")
def _read_notes(ctx, m, t):
    notes = ctx.mem.read_notes(4)
    if not notes:
        return "You have no notes yet."
    for n in notes:
        ctx.hud_post("log", "sys", "note  " + n)
    return "Your latest notes: " + ". ".join(n[18:] for n in notes)


@skill(r"^(?:clear|delete) (?:all )?(?:my |the )?notes$")
def _clear_notes(ctx, m, t):
    ctx.mem.clear_notes()
    return "All notes deleted."


# ---- information -----------------------------------------------------------------
@skill(r"^(?:what(?:s| is)? (?:the )?(?:current )?time(?: is it)?|what time is it|tell me the time|current time|time)(?: now| right now)?$")
def _time(ctx, m, t):
    return "It is " + time.strftime("%I:%M %p").lstrip("0") + "."


@skill(r"^(?:what(?:s| is)? (?:the )?(?:date|day)(?: is it)?(?: today)?|what day is it|todays date|tell me the date|date today|what is today)$")
def _date(ctx, m, t):
    return "Today is " + time.strftime("%A, %d %B %Y") + "."


@skill(r"\bweather\b|how (?:hot|cold) is it|is it (?:raining|sunny|cold|hot)")
def _weather(ctx, m, t):
    mm = re.search(r"\b(?:in|at|for)\s+(.+?)(?:\s+(?:today|tonight|now|right now|tomorrow))?$", t)
    city = re.sub(r"^the ", "", mm.group(1)) if mm else ctx.cfg.home_city
    try:
        w = services.weather(city)
    except net.NetError:
        return "I can't reach the weather service right now."
    if not w:
        return "I couldn't find a place called %s." % city
    if city.lower() == ctx.cfg.home_city.lower():
        ctx.weather = w
    return ("In %s it is %d degrees with %s, feeling like %d. Today's high is %d, low %d, with a %d percent "
            "chance of rain." % (w["city"], w["temp"], w["desc"], w["feels"], w["high"], w["low"], w["rain"]))


@skill(r"^(?:what(?:s| is) |tell me |give me |read |read me |show me )?(?:the |todays |latest |top )*(?:news|headlines)(?: today| please| now)?$")
def _news(ctx, m, t):
    try:
        items = services.news(3, ctx.cfg.news_region)
    except Exception:
        return "I can't reach the news feed right now."
    if not items:
        return "There are no headlines at the moment."
    for it in items:
        ctx.hud_post("log", "src", "news  " + it)
    return "Top headlines. " + " ... ".join(items)


@skill(r"(?:system|pc|computer) (?:status|stats|health|report)|\b(?:battery|cpu|ram)\b|memory usage")
def _status(ctx, m, t):
    s = ctx.stats or {}
    bits = []
    if s.get("cpu") is not None:
        bits.append("CPU at %d percent" % s["cpu"])
    if s.get("ram") is not None:
        bits.append("memory at %d percent" % s["ram"])
    if s.get("battery"):
        pct, plugged = s["battery"]
        bits.append("battery at %d percent%s" % (pct, " and charging" if plugged else ""))
    return ("All systems nominal. " + ", ".join(bits) + ".") if bits else "I can't read the system sensors here."


@skill(r"^(?:calculate|compute|what(?:s| is)|how much is|solve|evaluate)\s+(.+)$|^(\d[\d\s\.\+\-\*/%\(\)x^]+|.*\b(?:plus|minus|times|divided by|squared|cubed|power of|percent of|square root of)\b.*)$")
def _calc(ctx, m, t):
    val = calculate(next(g for g in m.groups() if g))
    return None if val is None else "That is %s." % val


# ---- system ----------------------------------------------------------------------
@skill(r"^(?:set |turn |change |put |make )?(?:the )?(?:volume|sound)(?: (?:to|at))? (\d{1,3})(?: ?percent| ?%)?$|"
       r"^(?:max|maximum|full) volume$|^volume (?:to )?(max|maximum|full|half|zero|min|minimum)$")
def _vol_set(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    word = m.group(2)
    target = int(m.group(1)) if m.group(1) else {"half": 50, "zero": 0, "min": 0, "minimum": 0}.get(word or "", 100)
    target = max(0, min(100, target))
    for _ in range(50):                       # each volume key press moves 2 percent: go to 0, then up
        winctl.press("volumedown")
    for _ in range(target // 2):
        winctl.press("volumeup")
    return "Volume set to %d percent." % target


@skill(r"\bbrightness\b")
def _brightness(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    n = re.search(r"\b(\d{1,3})\b", t)
    cur = pcinfo.get_brightness()
    if cur is None:
        return "I can't control the brightness on this display."
    if n:
        target = int(n.group(1))
    elif re.search(r"\b(?:up|increase|raise|higher|more|brighter)\b", t):
        target = cur + 20
    elif re.search(r"\b(?:down|decrease|lower|less|dim|dimmer|reduce)\b", t):
        target = cur - 20
    else:
        return "Brightness is at %d percent." % cur
    target = max(5, min(100, target))
    return "Brightness set to %d percent." % target if pcinfo.set_brightness(target) else \
        "I can't control the brightness on this display."


@skill(r"volume up|louder|increase (?:the )?volume|turn it up")
def _vol_up(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    for _ in range(5):
        winctl.press("volumeup")
    return "Volume up."


@skill(r"volume down|quieter|decrease (?:the )?volume|turn it down")
def _vol_down(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    for _ in range(5):
        winctl.press("volumedown")
    return "Volume down."


@skill(r"^(?:mute|unmute)(?: the)?(?: sound| volume| audio)?$")
def _mute(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.press("volumemute")
    return "Toggled mute."


@skill(r"screenshot|screen shot|capture (?:the )?screen")
def _shot(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    folder = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "jarvis_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
    return "Screenshot saved in your Pictures folder." if winctl.screenshot(path) else "The screenshot failed."


@skill(r"^lock (?:the )?(?:pc|computer|screen|laptop)$|^lock$")
def _lock(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    winctl.lock_screen()
    return "Locking the computer."


# ---- your PC: apps, windows, disk, network, files, power ---------------------------------------------------
def _say_list(ctx, title: str, items: list[str], speak: int = 8) -> str:
    for i in range(0, len(items), 12):                           # the full list goes to the transcript panel
        ctx.hud_post("log", "sys", (title + "\n" if i == 0 else "") + ", ".join(items[i:i + 12]))
    more = len(items) - speak
    return "%s: %s%s." % (title, ", ".join(items[:speak]), " and %d more, shown on screen" % more if more > 0 else "")


def _list_apps(ctx) -> str:
    names = APPS.start_names or APPS.programs
    return _say_list(ctx, "Your apps", [n.title() if n.islower() else n for n in names]) if names else \
        "I can't read your app list yet."


@skill(r"^(?!.*\b(?:open|running|active|using|opened)\b).*\b(?:how many|number of|count|total)\b.*\b(?:apps?|applications?|programs?|software)\b")
def _count_apps(ctx, m, t):
    if not APPS.ready:
        return "I'm still scanning your apps. Ask me again in a few seconds."
    n, p = len(APPS.start_names), len(APPS.programs)
    if not n and not p:
        return "I can't read the installed app list on this computer."
    msg = "I can see %d apps in your Start menu" % n
    if p:
        msg += ", and %d installed programs in the Control Panel list" % p
    d = getattr(ctx, "dialog", None)
    msg += ". Want me to list them?"
    return d.confirm(msg, lambda: _list_apps(ctx)) if d else msg


@skill(r"^(?!.*\b(?:running|open|opened|active)\b)(?:list|show|read|name|tell me|give me|what are)\b.*\b(?:installed|all)\b.*\b(?:apps?|applications?|programs?)\b|"
       r"^(?!.*\b(?:running|open|opened|active)\b)(?:list|show|read|name)(?: me)?(?: all)?(?: my| the)?(?: installed)? (?:apps|applications|programs)$")
def _list_installed(ctx, m, t):
    return _list_apps(ctx)


@skill(r"^(?:is|are|do i have|have i got|did i install)\s+(?:the\s+)?(.+?)\s+(?:installed|on (?:my |this )?(?:pc|computer|laptop|system))$")
def _is_installed(ctx, m, t):
    name = re.sub(r"\s+installed$", "", re.sub(r"^(?:an?|any)\s+", "", m.group(1)))
    if not APPS.ready:
        return "I'm still scanning your apps. Ask me again in a few seconds."
    hit = APPS.installed(name)
    d = getattr(ctx, "dialog", None)
    if not hit:
        return "No, I can't find %s on this computer." % name
    msg = "Yes, %s is installed." % hit
    return d.confirm(msg + " Shall I open it?", lambda: open_target(name, ctx)) if d else msg


@skill(r"\b(?:open|running|opened)\s+(?:apps?|programs?|windows?|applications?)\b|\b(?:apps?|programs?|windows?|applications?)\s+(?:are |is )?(?:currently |now )?(?:open|running|opened)\b|^what(?:s| is) open$|^what(?:s| is) running$")
def _running(ctx, m, t):
    if _need_win(ctx):
        return _need_win(ctx)
    wins = [(p, ti) for p, ti in pcinfo.running_windows() if not ti.upper().startswith("J.A.R.V.I.S")]
    if not wins:
        return "I can't see any open windows right now."
    names = sorted({p.lower() for p, _ in wins})
    for p, ti in wins[:25]:
        ctx.hud_post("log", "sys", "%s  -  %s" % (p, ti[:70]))
    return "You have %d apps open: %s." % (len(names), ", ".join(names[:8]) + (" and more" if len(names) > 8 else ""))


@skill(r"^what(?:s| is)(?: the)?(?: active| current| this| front| foreground)? (?:window|app|program|page|tab)(?: is this| is open| am i on)?$|"
       r"^what am i (?:looking at|on|using)$|^which (?:window|app|program) is (?:open|active|in front)$")
def _active_window(ctx, m, t):
    info = winctl.foreground_info()
    if not info:
        return "I can't see the active window here."
    title, exe = info
    if title.upper().startswith("J.A.R.V.I.S"):
        return "You are looking at me."
    return "You're in %s%s." % (exe.rsplit(".", 1)[0] or "an app", ", on %s" % title[:80] if title else "")


@skill(r"\b(?:disk|storage|hard ?drive|hard ?disk|ssd|free space|space left|drive space|space is left)\b")
def _disk(ctx, m, t):
    info = pcinfo.disk_info()
    if not info:
        return "I can't read the disk."
    total, used, free = info
    return "Your system drive has %d gigabytes free out of %d, so it is %d percent full." % (
        round(free), round(total), round(100 * used / total))


@skill(r"\b(?:ip address|my ip)\b")
def _ip(ctx, m, t):
    ip = pcinfo.local_ip()
    return "Your local IP address is %s." % ip.replace(".", " dot ") if ip else "I can't find a network connection."


@skill(r"\bwi ?fi\b.*\b(?:name|network|connected|using)\b|\b(?:which|what)\b.*\bwi ?fi\b|\bam i connected\b")
def _wifi(ctx, m, t):
    name = pcinfo.wifi_name()
    if name:
        return "You are connected to %s." % name
    return "You are online, but I can't read a Wi-Fi name." if getattr(ctx, "online", True) else "You don't seem to be connected."


@skill(r"\b(?:uptime|how long has (?:my |the |this )?(?:pc|computer|laptop) been (?:on|running))\b|^how long (?:have i|has it) been (?:on|running)$")
def _uptime(ctx, m, t):
    up = pcinfo.uptime_secs()
    return "The computer has been on for %s." % pcinfo.fmt_uptime(up) if up else "I can't read the uptime."


@skill(r"\b(?:pc|computer|laptop) (?:name|specs|specifications|info|information|details)\b|\bwhat (?:pc|computer|laptop|os|operating system) (?:is this|do i have|am i using)\b")
def _pc_info(ctx, m, t):
    s = ctx.stats or {}
    extra = ", with memory at %d percent" % s["ram"] if s.get("ram") is not None else ""
    return "This is %s%s." % (pcinfo.os_summary(), extra)


# -- power: always ask first
def _power_ask(ctx, action: str, what: str):
    d = getattr(ctx, "dialog", None)
    if not d:
        return None
    return d.confirm("Are you sure you want me to %s? Say yes or no." % what, lambda: pcinfo.power(action))


@skill(r"^(?:shut ?down|turn off|power off|power down)\s+(?:the |my |this )?(?:pc|computer|laptop|machine|system|windows)$")
def _p_shutdown(ctx, m, t):
    return _power_ask(ctx, "shutdown", "shut down the computer")


@skill(r"^(?:restart|reboot)\s+(?:the |my |this )?(?:pc|computer|laptop|machine|system|windows)$|^(?:restart|reboot) windows$")
def _p_restart(ctx, m, t):
    return _power_ask(ctx, "restart", "restart the computer")


@skill(r"^(?:put|send|set)\s+(?:the |my |this )?(?:pc|computer|laptop|machine|system)\s+(?:to\s+)?sleep$|^sleep (?:the )?(?:pc|computer|laptop)$")
def _p_sleep(ctx, m, t):
    return _power_ask(ctx, "sleep", "put the computer to sleep")


@skill(r"^hibernate(?: the (?:pc|computer|laptop))?$")
def _p_hibernate(ctx, m, t):
    return _power_ask(ctx, "hibernate", "hibernate the computer")


@skill(r"^(?:sign|log) ?(?:me |us )?out$|^sign out of (?:windows|the pc|the computer)$")
def _p_signout(ctx, m, t):
    return _power_ask(ctx, "signout", "sign you out")


@skill(r"^(?:cancel|abort|stop) (?:the )?(?:shutdown|restart|reboot)$")
def _p_abort(ctx, m, t):
    return "Shutdown cancelled." if pcinfo.abort_shutdown() else "There is no shutdown in progress."


# -- files
@skill(r"^(?:find|search for|look for|locate|open)\s+(?:the\s+|my\s+|a\s+)?(?:file|files|document|documents|pdf|presentation|"
       r"photo|picture|image|video|song|spreadsheet|folder)s?\s+(?:named\s+|called\s+)?(.+)$")
def _find_file(ctx, m, t):
    query, opening = m.group(1), t.startswith("open")
    if "folder" in t.split()[:4]:
        return None
    if re.sub(r"\s+again$", "", re.sub(r"^open\s+(?:the\s+|my\s+)?", "", t)) in ALIASES:        # "open file explorer" is an app, not a file search
        return None
    hits = pcinfo.find_files(query)
    if not hits:
        return "I couldn't find a file called %s in your Desktop, Documents, Downloads, Pictures, Music or Videos." % query
    for h in hits:
        ctx.hud_post("log", "sys", "file  " + h)
    best, name = hits[0], os.path.basename(hits[0])
    if opening or len(hits) == 1:
        launch(best)
        _focus(ctx, "app", name, name)
        return "Opening %s." % name
    d = getattr(ctx, "dialog", None)
    msg = "I found %d files. The newest is %s. Want me to open it?" % (len(hits), name)
    return d.confirm(msg, lambda: (launch(best), "Opening %s." % name)[1]) if d else msg


# -- windows
@skill(r"^(?:switch to|focus on|focus|bring up|go to|alt tab to)\s+(.+)$")
def _switch(ctx, m, t):
    name = m.group(1).strip()
    if canon_site(re.sub(r"^(?:the |my )", "", name)) in SITES:
        return open_target(name, ctx)
    if winctl.supported() and pcinfo.focus_window(name):
        _focus(ctx, "app", name, name)
        return "Switching to %s." % name
    return open_target(name, ctx)


# ---- web / apps ------------------------------------------------------------------
@skill(r"^(?:open|launch|start|run)\s+(.+)$")
def _open(ctx, m, t):
    return open_target(m.group(1), ctx)


@skill(r"^(?:force close|force quit|force kill|kill)\s+(.+)$")
def _force_close(ctx, m, t):
    return close_app(m.group(1), ctx, force=True)


@skill(r"^(?:close|terminate|quit)\s+(.+)$")
def _close(ctx, m, t):
    return close_app(m.group(1), ctx)


# ---- small talk (only when there is no AI brain; otherwise the AI answers naturally) --------------
def _pick(options):
    return lambda ctx, m, t: random.choice(options)


skill(r"^(?:hello|hi|hey|salam|assalam o alaikum|assalamualaikum|good (?:morning|afternoon|evening))$", chat=True)(
    _pick(["Hello! How can I help you?", "At your service.", "Hello there. What shall we do?"]))
skill(r"how are you|how do you do|hows it going", chat=True)(
    _pick(["All systems are running perfectly. Thank you for asking.", "Operating at peak efficiency, as always."]))
skill(r"who are you|your name|introduce yourself|what are you", chat=True)(
    _pick(["I am Jarvis, a voice controlled assistant. I can see, blink, open apps and type for you."]))
skill(r"^(?:thanks|thank you|thank you so much|thanks a lot|cheers)$", chat=True)(
    lambda ctx, m, t: (ctx.face.mood("happy", 4), "You are welcome.")[1])
skill(r"\bjoke\b", chat=True)(lambda ctx, m, t: (ctx.face.mood("happy", 5), random.choice(JOKES))[1])


# ============================================================================ router
COMPOUND_DELAY = 1.5          # seconds to let a freshly opened app/page appear before the next part of "X and then Y"
_CANT = ("Sorry, I understood that as a command, but I don't know how to do it yet.",
         "I'm afraid I can't do that one yet.")
_NO_PLAN_VERBS = {"open", "close", "launch", "quit", "exit", "kill", "type", "press", "compose", "minimize", "minimise",
                  "maximize", "maximise", "switch", "scroll", "lock", "mute", "unmute", "restart", "shutdown",
                  "install", "uninstall", "send", "bring"}


def _run_skills(ctx, t: str):
    ai = ctx.brain.llm_ready
    for rx, fn, chat in _SKILLS:
        if chat and ai:
            continue
        m = rx.search(t)
        if m:
            r = fn(ctx, m, t)
            if r is not None:
                return r
    return None


def _route_one(ctx, t: str, depth: int = 0):
    d = getattr(ctx, "dialog", None)
    if d:
        res = d.resolve(t)                         # follow-ups: "it", "again", yes/no, a missing slot ...
        if res:
            if res.reply is not None:
                d.record(t, res.reply, actionable=False)
                return res.reply
            if res.text and depth < 3:
                return _route_one(ctx, res.text, depth + 1)
    r = _run_skills(ctx, t)
    if r is not None:
        if d and r != "":
            d.record(t, r)
        elif d:
            d.record(t, r, actionable=False)
        return r
    if not dlg.looks_like_command(t):
        return None                                # an ordinary question or chat: the AI brain answers
    # It looks like a command that no rule matched. Let the language model translate it using the context ...
    plan = ctx.brain.plan(t, d.describe() if d else "") if (ctx.brain.llm_ready and depth == 0) else None
    if plan:
        if plan.get("kind") == "command" and plan.get("command"):
            cmd = normalize(plan["command"])
            if cmd and cmd != t:
                ctx.hud_post("log", "sys", "understood as: " + cmd)
                r = _route_one(ctx, cmd, depth + 1)
                if r is not None:
                    return r
            return random.choice(_CANT)
        return None                                # planner says it is a question / chat
    # ... and never answer an unrecognised command with an encyclopedia article.
    if t.split()[0] in _NO_PLAN_VERBS:
        return random.choice(_CANT)
    return None


def route(ctx, text: str):
    """Return the reply for a local skill, or None when the AI brain should answer."""
    ctx.addressed = has_wake_word(text)
    t = strip_wake(normalize(text))
    if not t:
        return random.choice(["Yes?", "At your service.", "I'm listening."])
    t2, had_filler = strip_filler(t)
    if had_filler:
        ctx.addressed = True
    t = t2 or t
    parts = dlg.split_compound(t)
    if len(parts) == 1:
        return _route_one(ctx, t)
    replies = []
    for i, part in enumerate(parts):
        r = _route_one(ctx, part)
        replies.append(r if r is not None else "I didn't understand: %s." % part)
        if i + 1 < len(parts) and COMPOUND_DELAY and parts[i + 1].split()[0] in ("type", "press", "dictate", "hit"):
            time.sleep(COMPOUND_DELAY)
    return " ".join(x for x in replies if x)
