"""Extra skills: WhatsApp by voice, real YouTube playback + player control, and a few handy PC helpers.

These skills are put at the FRONT of the skill list (see the bottom of this file), so they win over the older,
more generic ones ("type ...", "send", "play ...") but only when their own conditions hold - otherwise they
return None and the old skills carry on exactly as before.

WhatsApp flow (never sends without a spoken yes):
    "open whatsapp"                -> opens the desktop app if installed, else WhatsApp Web
    "open chat of Ali"             -> searches the name and opens the top result
    "type are you coming tonight"  -> types it into the open chat (does NOT send)
    "send"                         -> "Send this to Ali: ...? Say yes or no."  ->  "yes"  -> Enter
"""
from __future__ import annotations

import html
import os
import re
import sys
import threading
import time

from . import browser, net, newsdesk, urdu, winctl
from . import dialog as dlg

import importlib
S = importlib.import_module(".skills", __package__)             # the skills module (works whichever of the two is imported first)

_MINE: list = []


def xskill(pattern: str, chat: bool = False):
    rx = re.compile(pattern)

    def deco(fn):
        _MINE.append((rx, fn, chat))
        return fn
    return deco


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _need_win():
    return None if winctl.supported() else "That needs Windows."


# ============================================================================ raw text (keeps capitals & punctuation)
def _restore(ctx, norm: str, name: bool = False) -> str:
    """The skills see lower-cased text without punctuation. Find the same words in what the user really said,
    so a typed message keeps its capitals, commas and question marks."""
    raw = S.strip_wake_raw(getattr(ctx, "raw_text", "") or "")
    rt, nt = raw.split(), norm.split()
    out = None
    if rt and nt:
        keys = [S.normalize(x).split() for x in rt]
        for i in range(len(rt)):
            acc, j = [], i
            while j < len(rt) and len(acc) < len(nt):
                acc += keys[j]
                j += 1
                if acc == nt:
                    out = " ".join(rt[i:j])
                    break
                if acc != nt[:len(acc)]:
                    break
            if out:
                break
    if not out:
        out = norm.title() if name else (norm[:1].upper() + norm[1:])
    if name:
        out = re.sub(r"[\u2019']s$", "", out.strip(" .,!?;:"))     # "Ali's chat" -> "Ali"
    else:
        out = out.strip()
    return out


# ============================================================================ WhatsApp
class _WAState:
    contact = ""
    draft = ""
    ts = 0.0


WA = _WAState()
CONTEXT_SECS = 900


def _wa_windows():
    """WhatsApp windows: the desktop app, or a browser tab titled WhatsApp (never VS Code editing whatsapp.py)."""
    out = []
    for hwnd, title, exe in winctl.find_windows("whatsapp"):
        if exe in dlg.BROWSER_EXES or exe.startswith("whatsapp"):
            out.append((hwnd, title, exe))
    return out


def _wa_mode(exe: str) -> str:
    return "web" if exe in dlg.BROWSER_EXES else "desktop"


def _wa_active() -> bool:
    """Is the user talking about WhatsApp right now? Yes if it is in front, or Jarvis's own window is in front
    shortly after a WhatsApp command (the user is just speaking to the HUD)."""
    info = winctl.foreground_info() if winctl.supported() else None
    if not info:
        return False
    title, exe = (info[0] or "").lower(), (info[1] or "").lower()
    if exe.startswith("whatsapp") or (exe in dlg.BROWSER_EXES and "whatsapp" in title):
        return True
    return title.startswith("j.a.r.v.i.s") and time.time() - WA.ts < CONTEXT_SECS


def _wa_ensure(ctx):
    """Make sure WhatsApp is open and in front. Returns (window, error_message)."""
    wins = _wa_windows()
    if not wins:
        pref = _env("JARVIS_WHATSAPP", "auto").lower()
        app_path = S.APPS.find("whatsapp") if any("whatsapp" in k for k in S.APPS.index) else None
        if pref != "web" and app_path and S.launch(app_path):
            pass
        else:
            S.open_target("whatsapp", ctx)
        for _ in range(40):                                              # up to ~20 s for it to appear
            time.sleep(0.5)
            wins = _wa_windows()
            if wins:
                time.sleep(3.0)                                          # let the chat list load
                break
        if not wins:
            return None, "I could not see WhatsApp open. Is it logged in?"
    win = wins[0]
    winctl.focus_window(win[0])
    time.sleep(0.4)
    return win, None


def _wa_open_chat(ctx, name: str) -> str | None:
    win, err = _wa_ensure(ctx)
    if err:
        return err
    if _wa_mode(win[2]) == "web":
        winctl.hotkey("ctrl", "alt", "slash")                            # WhatsApp Web: search chats
    else:
        winctl.hotkey("ctrl", "f")                                       # WhatsApp desktop: search
    time.sleep(0.5)
    winctl.hotkey("ctrl", "a")
    abort = getattr(ctx, "abort_typing", None)
    if abort is not None and hasattr(abort, "clear"):
        abort.clear()
    winctl.type_text(name, abort.is_set if abort is not None else (lambda: False), delay=0.02)
    time.sleep(float(_env("JARVIS_WA_SEARCH_DELAY", "1.6") or 1.6))
    for k in [x.strip() for x in _env("JARVIS_WA_OPEN_KEYS", "enter").split(",") if x.strip()]:
        winctl.press(k)
        time.sleep(0.3)
    time.sleep(0.6)
    WA.contact, WA.draft, WA.ts = name, "", time.time()
    d = getattr(ctx, "dialog", None)
    if d:
        d.set_focus("site" if _wa_mode(win[2]) == "web" else "app", "whatsapp", "WhatsApp")
    return None


def _wa_type(ctx, text: str) -> str:
    """Type text into the open chat's message box. Never presses Enter."""
    wins = _wa_windows()
    if not wins:
        return "WhatsApp is not open. Say open WhatsApp, then open a chat."
    winctl.focus_window(wins[0][0])
    time.sleep(0.4)
    clean = re.sub(r"\s*[\r\n]+\s*", " ", text).strip()                 # a newline would SEND the message
    if WA.draft:
        clean = " " + clean
    abort = getattr(ctx, "abort_typing", None)
    if abort is not None and hasattr(abort, "clear"):
        abort.clear()
    ok = winctl.type_text(clean, abort.is_set if abort is not None else (lambda: False), delay=0.012)
    if not ok:
        return "Typing stopped."
    WA.draft += clean
    WA.ts = time.time()
    return ""


def _wa_confirm_send(ctx) -> str:
    d = getattr(ctx, "dialog", None)
    if not d:
        return "I can't ask for confirmation here, so I won't send it."
    who = WA.contact or "this chat"
    preview = WA.draft if len(WA.draft) <= 160 else WA.draft[:157] + "..."

    def do():
        wins = _wa_windows()
        if not wins or not WA.draft:
            return "Nothing to send any more."
        if not winctl.focus_window(wins[0][0]):
            return "I could not bring WhatsApp forward, so I did not send it."
        time.sleep(0.3)
        winctl.press("enter")
        WA.draft, WA.ts = "", time.time()
        return "Sent."
    return d.confirm("Send this to %s: %s. Say yes or no." % (who, preview), do, secs=40)


_JUNK_NAME = {"web", "desktop", "app", "me", "my", "chat", "whatsapp"}


def _clean_name(ctx, norm: str) -> str:
    norm = re.sub(r"\s+(?:on|in|using|via)\s+whats ?app$", "", norm.strip())
    norm = re.sub(r"^(?:the|my)\s+", "", norm)
    return _restore(ctx, norm, name=True)


@xskill(r"^(?:open|launch|start|run|go to)\s+(?:the\s+)?whats ?app(?:\s+(?:web|desktop|app|application))?$")
def _wa_open_app(ctx, m, t):
    if _need_win():
        return None                                                      # not Windows: let the normal skill open the site
    win, err = _wa_ensure(ctx)
    if err:
        return err
    WA.ts = time.time()
    d = getattr(ctx, "dialog", None)
    if d:
        d.set_focus("site" if _wa_mode(win[2]) == "web" else "app", "whatsapp", "WhatsApp")
    return "WhatsApp is open. Say open chat of, followed by the name."


_OPEN_CHAT = (r"^(?:(?:open|show|go to|find|search(?: for)?|switch to|start|begin|bring up)\s+)?(?:a\s+|the\s+)?"
              r"(?:whats ?app\s+)?(?:chat|conversation)\s+(?:of|with|for|from|to)\s+(.+)$|"
              r"^(?:open|show|go to|find|bring up)\s+(.+?)\s+(?:whats ?app\s+)?(?:chat|conversation)$|"
              r"^(?:message|msg|text|chat with|talk to|dm|whats ?app)\s+(?!me\b)(?!to\b)(\S+(?:\s+\S+){0,3})$")


@xskill(_OPEN_CHAT)
def _wa_chat(ctx, m, t):
    if _need_win():
        return None
    name = next((g for g in m.groups() if g), "")
    if not name or name.split()[0] in _JUNK_NAME:
        return None
    d = getattr(ctx, "dialog", None)
    explicit = "whatsapp" in t or "whats app" in t
    if not (explicit or _wa_active() or (d and d.on_screen_key() == "whatsapp") or t.startswith(("message ", "msg ", "text ", "dm "))):
        return None                                                      # "open chat with ..." means nothing outside WhatsApp
    if (d and d.referent() and d.referent().key in dlg.MAIL_KEYS) and not explicit:
        return None
    name = _clean_name(ctx, name)
    err = _wa_open_chat(ctx, name)
    if err:
        return err
    return "Opened the chat of %s. Say type, then your message. If that is the wrong person, say the full name." % name


_ONE_SHOT = (
    r"^(?:send|write|drop|shoot)\s+(?:a\s+)?(?:whats ?app\s+)?(?:message|msg|text)\s+(?:on whats ?app\s+)?to\s+(.+?)\s+"
    r"(?:saying|say|that says|which says|that)\s+(.+)$|"
    r"^send\s+(.+?)\s+a\s+(?:whats ?app\s+)?(?:message|msg|text)\s+(?:saying|that says|that)\s+(.+)$|"
    r"^(?:message|msg|text|whats ?app|dm)\s+(.+?)\s+(?:saying|that says)\s+(.+)$|"
    r"^tell\s+(.+?)\s+on\s+whats ?app\s+(?:that\s+)?(.+)$")


@xskill(_ONE_SHOT)
def _wa_one_shot(ctx, m, t):
    if _need_win():
        return None
    g = [x for x in m.groups() if x]
    name_n, msg_n = g[0], g[1]
    if name_n.split()[0] in _JUNK_NAME or len(name_n.split()) > 4:
        return None
    d = getattr(ctx, "dialog", None)
    if (d and d.referent() and d.referent().key in dlg.MAIL_KEYS) and "whatsapp" not in t and "whats app" not in t:
        return None
    name = _clean_name(ctx, name_n)
    err = _wa_open_chat(ctx, name)
    if err:
        return err
    WA.draft = ""
    msg = _restore(ctx, msg_n)
    err = _wa_type(ctx, msg)
    if err:
        return err
    return _wa_confirm_send(ctx)


@xskill(r"^(?:type|write|say|enter|put|draft|compose|add)\s+(?:a\s+|the\s+)?(?:message\s+|msg\s+|text\s+)?"
        r"(?:saying\s+|that says\s+)?(?!down\b)(?!note\b)(.+)$")
def _wa_type_skill(ctx, m, t):
    if _need_win() or not _wa_active():
        return None
    msg = _restore(ctx, m.group(1))
    err = _wa_type(ctx, msg)
    if err:
        return err
    return "Typed. Say send when you want it sent, or type more."


@xskill(r"^(?:send|send it|send now|send that|send this|send it now|send message|send the message|send the whats ?app message|"
        r"hit send|press send|go ahead and send|yes send|ok send|okay send)$")
def _wa_send(ctx, m, t):
    if _need_win() or not _wa_active():
        return None                                                      # not WhatsApp: the e-mail "send" skill gets a turn
    if not WA.draft:
        return "There is nothing typed in WhatsApp yet. Say type, then your message."
    return _wa_confirm_send(ctx)


@xskill(r"^(?:clear|delete|discard|erase|remove|cancel|scrap)\s+(?:the\s+|this\s+|my\s+)?(?:whats ?app\s+)?(?:message|draft|typed text|text)$")
def _wa_clear(ctx, m, t):
    if _need_win() or not _wa_active() or not WA.draft:
        return None
    wins = _wa_windows()
    if wins:
        winctl.focus_window(wins[0][0])
        time.sleep(0.3)
        winctl.hotkey("ctrl", "a")
        winctl.press("backspace")
    WA.draft = ""
    return "Cleared the message."


@xskill(r"^(?:read|repeat|show)(?: me)?(?: back)?(?: the| my)?(?: whats ?app)? (?:draft|message)(?: back)?$|^what did i (?:type|write|say)$")
def _wa_read(ctx, m, t):
    if not WA.draft or time.time() - WA.ts > CONTEXT_SECS:
        return None
    return "You wrote: %s" % WA.draft


@xskill(r"^(?:close|leave|exit)\s+(?:this\s+|the\s+)?chat$")
def _wa_close_chat(ctx, m, t):
    if _need_win() or not _wa_active():
        return None
    wins = _wa_windows()
    if wins:
        winctl.focus_window(wins[0][0])
        winctl.press("esc")
    WA.draft = ""
    return "Closed the chat."


# ============================================================================ YouTube: real playback
_GENERIC = {"music", "song", "songs", "video", "videos", "it", "something", "media", "the music", "the song",
            "the video", "next", "previous", "again", "that", "this", "some music", "some songs", "a song", "a video"}
_EXPLICIT_SITE = re.compile(r"\s+(?:on|in|from|using|via|at)\s+(?:the\s+)?(you ?tube|spotify|netflix|soundcloud|youtube music|"
                            r"you tube music|twitch|facebook|tiktok|instagram|google)(?:\s+(?:website|site|app))?$")
_LEAD = re.compile(r"^(?:me\s+)?(?:the\s+|a\s+|some\s+)?(?:song|songs|video|videos|track|music video|clip)?\s*(?:called|named|by)?\s*")


def youtube_first_video(query: str):
    """(video_id, title) of the first real video result for a search, or None. No API key needed."""
    try:
        page = net.get_bytes("https://www.youtube.com/results",
                             {"search_query": query, "sp": "EgIQAQ=="},       # sp = "type: video" (no channels / shorts shelves)
                             timeout=7, headers={"Accept-Language": "en-US,en;q=0.9"}).decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', page)
    if not m:
        return None
    title = ""
    t = re.search(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', page[m.end():m.end() + 1500])
    if t:
        try:
            title = html.unescape(t.group(1).encode("utf-8").decode("unicode_escape").encode("latin-1", "ignore").decode("utf-8", "ignore"))
        except Exception:
            title = html.unescape(t.group(1))
    return m.group(1), title.strip()


@xskill(r"^(?:play|watch|put on|stream)\s+(.+)$")
def _play_youtube(ctx, m, t):
    rest = m.group(1).strip()
    d = getattr(ctx, "dialog", None)
    site = _EXPLICIT_SITE.search(rest)
    if site:
        if "youtube" not in site.group(1).replace(" ", "") or "music" in site.group(1):
            return None                                                  # spotify / netflix ...: the old skill handles it
        rest = rest[:site.start()].strip()
    else:
        target = d.search_target() if d else None
        if target not in (None, "youtube"):
            return None
    rest = _LEAD.sub("", rest, count=1).strip() or rest
    if not rest or rest in _GENERIC or re.fullmatch(r"(?:the )?(?:next|previous|last)(?: one| song| video| track)?|again|it", rest):
        return None
    hit = youtube_first_video(rest)
    query = rest
    if hit:
        vid, title = hit
        browser.open_url("https://www.youtube.com/watch?v=" + vid)
        if d:
            d.set_focus("site", "youtube", "YouTube")
        return "Playing %s." % (title[:90] if title else query)
    S.web_search(ctx, query, "youtube")                                  # no internet / page changed: show the results page
    return "I could not pick one automatically, so here are the YouTube results for %s." % query


# ============================================================================ YouTube: player control
def _yt_windows():
    return [w for w in winctl.find_windows("youtube") if w[2] in dlg.BROWSER_EXES and "youtube music" not in w[1].lower()]


def _yt_front(ctx):
    """Bring the YouTube tab/window forward. Returns None when it is ready, or a sentence to say instead."""
    if _need_win():
        return _need_win()
    info = winctl.foreground_info()
    if info and info[1].lower() in dlg.BROWSER_EXES and "youtube" in (info[0] or "").lower():
        return None
    wins = _yt_windows()
    if not wins:
        return "YouTube is not open. Say play, then a song name."
    winctl.focus_window(wins[0][0])
    time.sleep(0.3)
    return None


def _yt_keys(ctx, *combos, reply="Done."):
    err = _yt_front(ctx)
    if err:
        return err
    for c in combos:
        winctl.hotkey(*c) if len(c) > 1 else winctl.press(c[0])
        time.sleep(0.05)
    return reply


@xskill(r"^(?:skip|forward|fast forward|go forward|jump(?: ahead| forward)?|seek|move forward)(?: by| for| ahead)?\s+(.+)$")
def _yt_forward(ctx, m, t):
    secs = S.parse_duration(m.group(1))
    if not secs:
        return None
    return _yt_seek(ctx, secs)


@xskill(r"^(?:rewind|go back|back|backward|backwards|jump back|move back|skip back)(?: by| for)?\s+(.+)$")
def _yt_back(ctx, m, t):
    secs = S.parse_duration(m.group(1))
    if not secs:
        return None
    return _yt_seek(ctx, -secs)


def _yt_seek(ctx, secs: int):
    n = abs(int(secs))
    key10, key5 = ("l", "right") if secs > 0 else ("j", "left")
    presses = [(key10,)] * min(n // 10, 90) + [(key5,)] * ((n % 10) // 5)
    if not presses:
        presses = [(key5,)]
    return _yt_keys(ctx, *presses, reply=("Skipped ahead %s." if secs > 0 else "Went back %s.") % S.fmt_duration(n))


@xskill(r"^(?:speed up|faster|play faster|increase (?:the )?speed|speed up (?:the )?video)$")
def _yt_faster(ctx, m, t):
    return _yt_keys(ctx, ("shift", "period"), reply="Faster.") if _yt_windows() else None


@xskill(r"^(?:slow down|slower|play slower|decrease (?:the )?speed|slow (?:the )?video(?: down)?)$")
def _yt_slower(ctx, m, t):
    return _yt_keys(ctx, ("shift", "comma"), reply="Slower.") if _yt_windows() else None


@xskill(r"^(?:turn |switch )?(?:on |off )?(?:the )?(?:subtitles|captions|cc|closed captions)(?: on| off)?$|^(?:toggle) (?:subtitles|captions)$")
def _yt_captions(ctx, m, t):
    return _yt_keys(ctx, ("c",), reply="Toggled the subtitles.") if _yt_windows() else None


@xskill(r"^(?:theat(?:er|re) mode)$|^(?:turn )?(?:on |off )?theat(?:er|re) mode$")
def _yt_theater(ctx, m, t):
    return _yt_keys(ctx, ("t",), reply="Theater mode toggled.") if _yt_windows() else None


@xskill(r"^(?:mini ?player|miniplayer)$|^(?:open|close) (?:the )?mini ?player$")
def _yt_mini(ctx, m, t):
    return _yt_keys(ctx, ("i",), reply="Done.") if _yt_windows() else None


@xskill(r"^(?:restart|replay|start over|play from (?:the )?(?:start|beginning)|go to (?:the )?(?:start|beginning))(?: the)?(?: video| song)?$")
def _yt_restart(ctx, m, t):
    return _yt_keys(ctx, ("0",), reply="Back to the start.") if _yt_windows() else None


@xskill(r"^(?:mute|unmute) (?:the )?(?:video|youtube)$")
def _yt_mute(ctx, m, t):
    return _yt_keys(ctx, ("m",), reply="Done.") if _yt_windows() else None


@xskill(r"^(?:previous|last|play previous|go to (?:the )?previous) video$")
def _yt_prev(ctx, m, t):
    return _yt_keys(ctx, ("shift", "p"), reply="Previous video.") if _yt_windows() else None


@xskill(r"^(?:what(?:s| is) (?:this|that|the) (?:song|video|track)|what(?:s| is) (?:playing|on)(?: right now| now)?|"
        r"what am i (?:watching|listening to)|which (?:song|video) is (?:this|playing))$")
def _yt_now(ctx, m, t):
    if _need_win():
        return None
    for _, title, _ in _yt_windows():
        name = re.sub(r"^\(\d+\)\s*", "", title)
        name = re.sub(r"\s+-\s+(?:YouTube|Google Chrome|Microsoft.? Edge|Brave|Mozilla Firefox).*$", "", name, flags=re.I).strip()
        if name and name.lower() != "youtube":
            return "You are watching %s." % name
    return None


# ============================================================================ small PC helpers
@xskill(r"^(?:snap|move|put|dock)(?: this| the)?(?: window)? (?:to the |to |on the )?(left|right)(?: side| half)?$")
def _snap(ctx, m, t):
    if _need_win():
        return _need_win()
    winctl.hotkey("win", m.group(1))
    return "Snapped %s." % m.group(1)


_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}


@xskill(r"^(?:go to |switch to |open |show )?tab (\d|one|two|three|four|five|six|seven|eight)$")
def _tab_n(ctx, m, t):
    if _need_win():
        return _need_win()
    g = m.group(1)
    winctl.hotkey("ctrl", str(_WORD_NUM.get(g, g)))
    return "Tab %s." % _WORD_NUM.get(g, g)


@xskill(r"^(?:bookmark|favou?rite)(?: this| the)?(?: page| tab| site)?$|^add (?:this )?(?:page |tab |site )?to (?:my )?bookmarks$")
def _bookmark(ctx, m, t):
    if _need_win():
        return _need_win()
    winctl.hotkey("ctrl", "d")
    time.sleep(0.6)
    winctl.press("enter")
    return "Bookmarked."


@xskill(r"^(?:find|search) (?:on|in) (?:this |the )?page\s+(?:for\s+)?(.+)$|^find on page\s+(.+)$")
def _find_page(ctx, m, t):
    if _need_win():
        return _need_win()
    q = next(g for g in m.groups() if g)
    winctl.hotkey("ctrl", "f")
    time.sleep(0.3)
    winctl.type_text(q, lambda: False, delay=0.01)
    winctl.press("enter")
    return "Looking for %s on this page." % q


# ============================================================================ language: English <-> Urdu
@xskill(r"^(?:please )?(?:switch|change|set|go|talk|speak|reply|respond|answer|use|turn|start|begin)\b.*\b(urdu|english)\b(?: mode| language)?$|"
        r"^(urdu|english)(?: mode| language)$|^(?:urdu|english) (?:please|bolo)$")
def _lang(ctx, m, t):
    want = next(g for g in m.groups() if g)
    urdu.set_mode("ur" if want == "urdu" else "en")
    if hasattr(ctx, "hud_post"):
        ctx.hud_post("log", "sys", "Language: %s" % ("Urdu" if want == "urdu" else "English"))
    return "ٹھیک ہے، اب میں اردو میں بات کروں گا۔" if want == "urdu" else "Switched to English."


# ============================================================================ news desk
_NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NEWS_LEAD = (r"(?:(?:what(?:s| is| are)|tell me|tell us|give me|give us|read(?: me| us)?|show me|get me|bring me|any|"
              r"can you (?:tell|give|read)(?: me)?|i want|i need|let me hear|let me know|play)\s+)?(?:the\s+)?")
_NEWS_WORD = r"(?:todays?|latest|top|breaking|daily|live|current|recent|global|world|international|fresh|morning|evening|major|big|main)"


def _news_reply(ctx, t: str) -> str:
    want_ur = urdu.is_urdu()
    if re.search(r"\bin urdu\b", t):
        want_ur = True
    elif re.search(r"\bin english\b", t):
        want_ur = False
    n = 5
    mm = re.search(r"\b(\d{1,2}|%s)\b" % "|".join(_NUMW), t)
    if mm and not re.search(r"\b(?:last|past|in)\s+%s\b" % re.escape(mm.group(1)), t):
        n = _NUMW.get(mm.group(1)) or int(mm.group(1))
    breaking = bool(re.search(r"\b(?:breaking|latest|live|urgent|just in)\b", t))
    code, topic = newsdesk.country_of(t), newsdesk.topic_of(t)
    extra = ""
    if not code and not topic:
        about = re.search(r"\b(?:about|on|regarding)\s+(.+)$", t)
        if about:
            extra = re.sub(r"\b(?:today|please|now|in urdu|in english|latest|breaking)\b", " ", about.group(1)).strip()
            extra = re.sub(r"^(?:the|a)\s+", "", re.sub(r"\s+", " ", extra))
    if not (code or topic or extra):
        code = (getattr(getattr(ctx, "cfg", None), "news_region", None) or "PK").upper()
    try:
        res = newsdesk.fetch(country=code, topic=topic, extra=extra, urdu=want_ur, n=n,
                             home=(getattr(getattr(ctx, "cfg", None), "news_region", None) or "PK").upper())
    except Exception:
        return "ابھی خبروں کی فیڈ نہیں مل رہی۔" if want_ur else "I can't reach the news feed right now."
    for it in res.items:
        ctx.hud_post("log", "src", "news  %s%s" % (it.title, ("  \u2014 " + it.source) if it.source else ""))
    return newsdesk.spoken(res, want_ur, breaking)


@xskill(r"^(?:give me |tell me |read me |read |start |play |what s |whats |let me hear )?(?:my |the |our )?(?:daily |morning |evening )?"
        r"(?:news )?(?:briefing|brief|bulletin|summary|roundup)(?: please| in urdu)?$|^(?:my |the )?(?:daily|morning) news$")
def _briefing(ctx, m, t):
    want_ur = urdu.is_urdu() or bool(re.search(r"\bin urdu\b", t))
    try:
        text, items = newsdesk.briefing((getattr(getattr(ctx, "cfg", None), "news_region", None) or "PK").upper(), want_ur)
    except Exception:
        return "ابھی خبروں کی فیڈ نہیں مل رہی۔" if want_ur else "I can't reach the news feed right now."
    for it in items:
        ctx.hud_post("log", "src", "news  " + it.title)
    return text


_NEWS_OK = set("what whats is are the a an me us you i we to of from in on about for regarding with and or any please now today "
               "todays right tell give read show get bring let hear know want need can could would play top latest breaking daily "
               "live current recent global world international fresh morning evening major big main news headline headlines update "
               "updates bulletin briefing urdu english happening going new".split())


def _news_ok(t: str) -> bool:
    """True when every word before an 'about ...' tail is news vocabulary, a country or a topic - so that
    'fake news detector' or 'open google news' are never mistaken for a news request."""
    head = re.split(r"\b(?:about|regarding)\b", t, 1)[0]
    for w in re.findall(r"[a-z]+|\d+", head):
        if w in _NEWS_OK or w.isdigit() or w in _NUMW or w in newsdesk.ALIAS_TOKENS or newsdesk.topic_of(w):
            continue
        return False
    return True


@xskill(r"^.*\b(?:news|headlines?|bulletin)\b.*$|^[a-z ]{2,40}\bupdates?\b$")
def _news_main(ctx, m, t):
    if not _news_ok(t):
        return None
    if re.search(r"\bupdates?\b", t) and not re.search(r"\b(?:news|headlines?|bulletin)\b", t) and not (
            newsdesk.country_of(t) or newsdesk.topic_of(t)):
        return None
    return _news_reply(ctx, t)


@xskill(r"^(?:.*\b)?(?:geo ?politic\w*)\b.*$")
def _news_geo(ctx, m, t):
    if not re.search(r"\b(?:news|updates?|headlines?|latest|today|briefing|happening|going on|current|breaking)\b", t):
        return None
    return _news_reply(ctx, t + " geopolitics")


@xskill(r"^(?:what(?:s| is) (?:happening|going on|new|up)|whats the situation|how is the situation)(?: right now| today| now)?"
        r"(?: (?:in|around|with|at))?\s*(.*)$")
def _news_happening(ctx, m, t):
    place = (m.group(1) or "").strip()
    if place and not (newsdesk.country_of(place) or newsdesk.topic_of(place)):
        return None                                                  # "what's happening with my code" is not news
    if not place:
        return None                                                  # "what's happening" alone: leave it to the AI
    return _news_reply(ctx, "news " + place)


@xskill(r"^(?:what can you do|help|commands|what are your commands|show help|what are your features)$")
def _help2(ctx, m, t):
    return ("I can chat and answer questions in English or Urdu, read breaking news for any country, the world or "
            "geopolitics, open and close apps and websites, play any song or video on YouTube and control it, message "
            "people on WhatsApp after your confirmation, compose emails, set timers and reminders, take notes, do maths, "
            "type for you, control volume, brightness and media, take screenshots, and manage windows and tabs. "
            "Say speak Urdu or speak English to switch language. Say stop and I go quiet. Say Jarvis closed to end me.")


# ---- install: our skills go in front of the old ones --------------------------------------------------
_names = {id(fn) for _, fn, _ in S._SKILLS}
S._SKILLS[:0] = [e for e in _MINE if id(e[1]) not in _names]
