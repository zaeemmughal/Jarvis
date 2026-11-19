"""Part B features S1 to S8 (additive; installed in front of the older skills by features.py).

    S1 prayer times       "prayer times", "next namaz kab hai", "maghrib ka time", "namaz se pehle yaad dilao"
    S2 focus timer        "start focus mode", "pomodoro 50 minutes", "stop focus mode", "focus status"
    S3 translate          "translate good morning into urdu", "how do you say thank you in urdu"
    S4 converters         "100 dollars in rupees", "100 dollar kitne rupees", "convert 5 km to miles", "dollar rate"
    S5 to-do list         "add task finish report", "to-do mein add karo FYP report", "my to-do list", "mark task 2 done"
    S6 clipboard          "read the clipboard", "summarize the clipboard", "save clipboard to notes"
    S7 page summary       "summarize this page", "is page ka summary do", "summarize <link>"
    S8 journal            "journal likho" (three questions, saved as a Word file in reports/)

Rules as everywhere: slow work on a worker thread (or inside the request worker, which respects ctx.epoch), 12 s network
timeouts, a short spoken failure sentence, details in logs/jarvis.log, free services only, a no-AI fallback.
Free services used: Aladhan (prayer times), MyMemory (translation fallback), open.er-api.com (currency rates).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from . import agents, docs, net, services, urdu
from .config import DATA_DIR

log = logging.getLogger("jarvis.extras2")

_MINE: list = []          # ordinary skills, installed after features.py's own
_FIRST: list = []         # skills that must see every sentence first (the journal answer catcher)


def x2skill(pattern: str, chat: bool = False, first: bool = False):
    rx = re.compile(pattern)

    def deco(fn):
        (_FIRST if first else _MINE).append((rx, fn, chat))
        return fn
    return deco


def _S():
    import importlib
    return importlib.import_module(".skills", __package__)


def _say(ctx, text: str) -> None:
    """Speak something that was not asked for this second (timers, reminders): like a timer, it is allowed to interrupt."""
    fn = getattr(ctx, "say_async", None) or getattr(ctx, "respond", None)
    if fn:
        fn(text)


def _bg(ctx, ack: str, work, fail: str = "Sorry, that did not work. The details are in the log.") -> str:
    epoch = getattr(ctx, "epoch", 0)

    def job():
        try:
            out = work()
        except Exception:
            log.exception("background job failed")
            out = fail
        if out:
            agents.speak_if_current(ctx, epoch, out)
    threading.Thread(target=job, daemon=True, name="extras2-job").start()
    return ack


def _num(s: str) -> float:
    return float(s)


def _fmt_num(v: float) -> str:
    if abs(v) >= 1000:
        return "{:,.0f}".format(v) if abs(v - round(v)) < 0.005 else "{:,.2f}".format(v)
    return ("%.2f" % v).rstrip("0").rstrip(".")


# ============================================================================ S1  prayer times
_PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")
_PNAME = {"fajr": "fajr", "fajar": "fajr", "zuhr": "dhuhr", "zohar": "dhuhr", "zuhar": "dhuhr", "dhuhr": "dhuhr", "dhuhur": "dhuhr",
          "asr": "asr", "asar": "asr", "maghrib": "maghrib", "magrib": "maghrib", "isha": "isha", "esha": "isha"}
_PNAMES = "|".join(sorted(_PNAME, key=len, reverse=True))
_pcache: dict = {"day": "", "city": "", "t": None}


def prayer_times(city: str, country: str = "PK") -> dict:
    """{'fajr': '04:58', ...} for today. Cached for the day; raises NetError when offline and nothing is cached."""
    day = time.strftime("%Y-%m-%d")
    if _pcache["t"] and _pcache["day"] == day and _pcache["city"] == city:
        return _pcache["t"]
    d = net.get_json("https://api.aladhan.com/v1/timingsByCity",
                     {"city": city, "country": country, "method": 1, "school": 1}, timeout=12)
    raw = d["data"]["timings"]
    t = {k.lower(): re.search(r"\d{1,2}:\d{2}", str(v)).group(0) for k, v in raw.items() if k.lower() in _PRAYERS + ("sunrise",)}
    if not all(p in t for p in _PRAYERS):
        raise net.NetError("prayer times incomplete")
    _pcache.update(day=day, city=city, t=t)
    return t


def _clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def next_prayer(t: dict, now: datetime | None = None):
    """(name, datetime) of the next of the five prayers; after Isha it is tomorrow's Fajr."""
    now = now or datetime.now()
    for p in _PRAYERS:
        h, m = (int(x) for x in t[p].split(":"))
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if when > now:
            return p, when
    h, m = (int(x) for x in t["fajr"].split(":"))
    return "fajr", (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)


def _in(delta: timedelta) -> str:
    mins = max(int(delta.total_seconds() // 60), 0)
    h, m = divmod(mins, 60)
    return ("%d hour%s and %d minute%s" % (h, "" if h == 1 else "s", m, "" if m == 1 else "s")) if h else "%d minute%s" % (m, "" if m == 1 else "s")


def _times_or_none(ctx):
    cfg = getattr(ctx, "cfg", None)
    city = getattr(cfg, "home_city", "") or "Sargodha"
    try:
        return city, prayer_times(city, getattr(cfg, "news_region", "") or "PK")
    except Exception as e:
        log.info("prayer times failed: %s", e)
        return city, None


_OFFLINE_PRAYER = "I could not get the prayer times right now. Check the internet connection."


@x2skill(r"^(?:prayer|namaz|namaaz|salah|salat) (?:times?|timings?|ke auqaat|ke awqat|ka time|ka waqt|ki timing|ki timings)(?: batao| dikhao| kya hain| kya hai| today)?$|"
         r"^(?:what are |tell me |show |whats )?(?:the )?(?:todays |today s )?prayer (?:times|timings)(?: today)?$|"
         r"^(?:aaj ki |aaj ke )?(?:namaz|namaaz) (?:ke )?(?:auqaat|awqat|timings?)(?: batao)?$")
def _prayer_list(ctx, m, t):
    city, tm = _times_or_none(ctx)
    if not tm:
        return _OFFLINE_PRAYER
    names = {"fajr": "Fajr", "dhuhr": "Dhuhr", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
    line = ", ".join("%s %s" % (names[p], _clock(tm[p])) for p in _PRAYERS)
    agents.show(ctx, "PRAYER TIMES - " + city, "\n".join("%s  %s" % (names[p], _clock(tm[p])) for p in _PRAYERS))
    return "Prayer times for %s today: %s." % (city, line)


@x2skill(r"^(?:next|agli|agla) (?:prayer|namaz|namaaz|salah)(?: kab hai| kab hogi| kab| time| ka time| kitni der mein)?$|"
         r"^(?:when is|whens) (?:the )?next (?:prayer|namaz|salah)$|^namaz kab hai$|^(?:how long|kitni der) (?:until|till|for|baad|mein) (?:the )?(?:next )?(?:prayer|namaz)$|"
         r"^(?:how long|kitni der) (?:is it |hai )?(?:until|till) (?:the )?(?:next )?(?:prayer|namaz)$")
def _prayer_next(ctx, m, t):
    city, tm = _times_or_none(ctx)
    if not tm:
        return _OFFLINE_PRAYER
    name, when = next_prayer(tm)
    return "The next prayer is %s at %s, in %s." % (name.capitalize(), _clock(when.strftime("%H:%M")), _in(when - datetime.now()))


@x2skill(r"^(?:(?:when is|whens|what time is|what is|whats|tell me)(?: the)? )?(%s)(?: prayer| namaz| ka time| ka waqt| time| waqt)?"
         r"(?: kab hai| kab hoti hai| kab hogi| kab| kya hai| batao| kitne baje hai| ka time kya hai| time kya hai)?$" % _PNAMES)
def _prayer_one(ctx, m, t):
    if t == m.group(1):                                     # a bare "asr" is not a question
        return None
    city, tm = _times_or_none(ctx)
    if not tm:
        return _OFFLINE_PRAYER
    p = _PNAME[m.group(1)]
    return "%s is at %s today in %s." % (p.capitalize(), _clock(tm[p]), city)


@x2skill(r"^(?:remind me|alert me|yaad dilao|yaad dila do)(?: me)?(?: (\d+) (?:minutes?|mins?|minute))? (?:before|pehle)(?: the)? (?:next )?(?:prayer|namaz|namaaz)$|"
         r"^(?:namaz|prayer) se (?:(\d+) (?:minute|minutes|min) )?pehle (?:yaad dilao|yaad dila do|remind kar do|alert karo)$|"
         r"^(?:remind me|alert me) (?:(\d+) (?:minutes?|mins?) )?before (?:the )?next (?:prayer|namaz)$")
def _prayer_remind(ctx, m, t):
    lead = int(next((g for g in m.groups() if g), 10))
    city, tm = _times_or_none(ctx)
    if not tm:
        return _OFFLINE_PRAYER
    name, when = next_prayer(tm)
    secs = (when - datetime.now()).total_seconds() - lead * 60
    if secs < 5:
        return "%s is less than %d minutes away already." % (name.capitalize(), lead)
    ctx.add_timer(int(secs), "%s is in %d minutes." % (name.capitalize(), lead), "namaz")
    return "Done. I will remind you %d minutes before %s, at %s." % (lead, name.capitalize(), _clock((when - timedelta(minutes=lead)).strftime("%H:%M")))


# ============================================================================ S2  focus / pomodoro
_POMO: dict = {"stop": None, "info": None}


class _Handle:
    """Shows up in ctx.timers so the HUD counts down, and 'cancel timers' ends the focus session too."""
    def __init__(self, stop: threading.Event):
        self.stop = stop

    def cancel(self):
        self.stop.set()


def pomodoro_running() -> bool:
    ev = _POMO["stop"]
    return bool(ev and not ev.is_set())


def _pomo_loop(ctx, work_min: int, break_min: int, stop: threading.Event):
    rounds = 0
    while not stop.is_set() and getattr(ctx, "running", True):
        rounds += 1
        for phase, mins in (("focus", work_min), ("break", (15 if rounds % 4 == 0 else break_min))):
            if stop.is_set():
                return
            _POMO["info"] = {"phase": phase, "round": rounds, "end": time.time() + mins * 60}
            entry = {"due": time.time() + mins * 60, "label": phase, "timer": _Handle(stop)}
            timers = getattr(ctx, "timers", None)
            if isinstance(timers, list):
                timers.append(entry)
            if phase == "focus":
                _say(ctx, "Focus round %d. %d minutes, starting now." % (rounds, mins))
            else:
                _say(ctx, "Round %d done. Take a %d minute break." % (rounds, mins))
            stop.wait(mins * 60)
            if isinstance(timers, list) and entry in timers:
                timers.remove(entry)
    _POMO["info"] = None


@x2skill(r"^(?:start|begin|turn on|enable) (?:a |the |my )?(?:focus|pomodoro|study|work)(?: mode| timer| session)?(?: for (\d+) (?:minutes?|mins?))?$|"
         r"^(?:focus|pomodoro)(?: mode| timer)? (?:start|on|shuru|chalao|lagao)(?: karo| kar do)?$|"
         r"^(?:focus|pomodoro)(?: mode)? (?:shuru karo|start karo|chalao|on karo|lagao)$|"
         r"^(\d+) minute (?:ka )?(?:focus|pomodoro)(?: mode| timer)?(?: start karo| shuru karo| lagao| chalao)?$|^pomodoro (\d+)(?: minutes?| mins?)?$")
def _focus_start(ctx, m, t):
    if pomodoro_running():
        return "Focus mode is already running. Say focus status to see the time left."
    n = next((g for g in m.groups() if g), None)
    work = min(max(int(n), 5), 120) if n else 25
    brk = 5 if work <= 50 else 10
    stop = threading.Event()
    _POMO["stop"] = stop
    threading.Thread(target=_pomo_loop, args=(ctx, work, brk, stop), daemon=True, name="pomodoro").start()
    return "Focus mode on: %d minutes of work, then a %d minute break, repeating. Say stop focus mode when you are done." % (work, brk)


@x2skill(r"^(?:stop|end|cancel|turn off|disable|quit) (?:the |my )?(?:focus|pomodoro)(?: mode| timer| session)?$|"
         r"^(?:focus|pomodoro)(?: mode| timer)? (?:stop|off|band|cancel)(?: karo| kar do)?$|^(?:focus|pomodoro) (?:mode )?band (?:karo|kar do)$")
def _focus_stop(ctx, m, t):
    if not pomodoro_running():
        return "Focus mode is not running."
    _POMO["stop"].set()
    return "Focus mode is off. Well done."


@x2skill(r"^(?:focus|pomodoro)(?: mode| timer)? (?:status|kitna time bacha hai|kitna bacha hai)$|^how much (?:focus|pomodoro) time (?:is )?left$|^focus kitna (?:time )?bacha hai$")
def _focus_status(ctx, m, t):
    info = _POMO["info"]
    if not pomodoro_running() or not info:
        return "Focus mode is not running."
    left = max(int(info["end"] - time.time()), 0)
    return "Round %d, %s: %d minutes and %d seconds left." % (info["round"], "focus time" if info["phase"] == "focus" else "break", left // 60, left % 60)


# ============================================================================ S3  translate
_TARGET = {"urdu": "urdu", "english": "english", "angrezi": "english", "roman urdu": "roman urdu", "roman": "roman urdu"}
_LANGNAME = {"urdu": "Urdu (Urdu script)", "english": "English", "roman urdu": "Roman Urdu (Urdu written in English letters)"}
_MM_BAD = ("MYMEMORY WARNING", "PLEASE SELECT TWO DISTINCT", "INVALID", "QUERY LENGTH LIMIT")


def translate(ctx, text: str, target: str) -> str | None:
    """Translation or None. Uses the AI when one is ready (Smart mode), then MyMemory (free, no key)."""
    text = text.strip()
    brain = getattr(ctx, "brain", None)
    if brain is not None and hasattr(brain, "complete"):
        out = brain.complete("Translate this into %s. Reply with the translation only, no quotes, no notes:\n\n%s" % (_LANGNAME[target], text),
                             "You are a precise translator for a voice assistant.", 300, 20)
        if out:
            return out.strip().strip('"\u201c\u201d')
    if target == "roman urdu":
        return None
    src = "ur" if urdu.has_urdu(text) else "en"
    dst = {"urdu": "ur", "english": "en"}[target]
    if src == dst:
        return text
    try:
        d = net.get_json("https://api.mymemory.translated.net/get", {"q": text[:450], "langpair": "%s|%s" % (src, dst)}, timeout=12)
        out = html.unescape(str(d.get("responseData", {}).get("translatedText") or "")).strip()
    except Exception as e:
        log.info("mymemory failed: %s", e)
        return None
    if not out or any(b in out.upper() for b in _MM_BAD):
        return None
    return out


def _do_translate(ctx, text: str, target_word: str):
    target = _TARGET.get(target_word.strip())
    text = text.strip(" ,")
    if not target or not text:
        return None
    out = translate(ctx, text, target)
    if not out:
        if target == "roman urdu" or (not urdu.has_urdu(text) and target == "english" and re.search(r"\b(?:hai|hain|kya|nahi|main|mein|aap|tum|ko|ka|ki)\b", text)):
            return "I need Smart mode with an AI key to translate that."
        return "I could not translate that right now."
    ctx.hud_post("log", "sys", "%s  ->  %s" % (text, out))
    return out if target == "urdu" else ("In %s: %s" % (target.title(), out))


_T = r"(urdu|english|roman urdu|angrezi|roman)"


@x2skill(r"^translate (?:this |that |the sentence |the word |the phrase )?(.+?) (?:in|into|to) (?:the )?%s$|"
         r"^(?:how do you say|how do i say|how to say|how would you say) (.+?) in %s$|^what is (.+?) in (urdu|roman urdu)$|"
         r"^(.+?) (?:ko |ka |ki |ke )?%s (?:mein|me) (?:translate karo|translate kar do|batao|bolo|kaho|likho|translate)$|"
         r"^(.+?) ka %s (?:mein )?(?:translation|tarjuma|matlab|tarjuma karo)(?: batao| karo)?$" % (_T, _T, _T, _T))
def _translate(ctx, m, t):
    g = [x for x in m.groups() if x]
    return _do_translate(ctx, g[0], g[1]) if len(g) >= 2 else None


@x2skill(r"^%s (?:mein|me) (?:batao|bolo|translate karo|kaho) (.+)$" % _T)
def _translate2(ctx, m, t):
    return _do_translate(ctx, m.group(2), m.group(1))


# ============================================================================ S4  currency and unit converter
_CUR = {"usd": "USD", "dollar": "USD", "dollars": "USD", "rupee": "PKR", "rupees": "PKR", "rupay": "PKR", "rupaye": "PKR", "rupe": "PKR",
        "pkr": "PKR", "rs": "PKR", "euro": "EUR", "euros": "EUR", "eur": "EUR", "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "riyal": "SAR",
        "riyals": "SAR", "sar": "SAR", "dirham": "AED", "dirhams": "AED", "aed": "AED", "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY",
        "inr": "INR", "indian rupee": "INR", "indian rupees": "INR", "cad": "CAD", "aud": "AUD", "lira": "TRY", "try": "TRY"}
_CURNAME = {"USD": "US dollars", "PKR": "Pakistani rupees", "EUR": "euros", "GBP": "pounds", "SAR": "Saudi riyals", "AED": "dirhams",
            "JPY": "yen", "CNY": "yuan", "INR": "Indian rupees", "CAD": "Canadian dollars", "AUD": "Australian dollars", "TRY": "Turkish lira"}
_UNITS = {  # name -> (kind, factor to the base unit)
    "km": ("len", 1000), "kms": ("len", 1000), "kilometer": ("len", 1000), "kilometers": ("len", 1000), "kilometre": ("len", 1000), "kilometres": ("len", 1000),
    "m": ("len", 1), "meter": ("len", 1), "meters": ("len", 1), "metre": ("len", 1), "metres": ("len", 1), "cm": ("len", 0.01), "centimeter": ("len", 0.01),
    "centimeters": ("len", 0.01), "mm": ("len", 0.001), "mile": ("len", 1609.344), "miles": ("len", 1609.344), "mi": ("len", 1609.344),
    "foot": ("len", 0.3048), "feet": ("len", 0.3048), "ft": ("len", 0.3048), "inch": ("len", 0.0254), "inches": ("len", 0.0254),
    "yard": ("len", 0.9144), "yards": ("len", 0.9144),
    "kg": ("mass", 1), "kgs": ("mass", 1), "kilo": ("mass", 1), "kilos": ("mass", 1), "kilogram": ("mass", 1), "kilograms": ("mass", 1),
    "g": ("mass", 0.001), "gram": ("mass", 0.001), "grams": ("mass", 0.001), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237),
    "pound": ("mass", 0.45359237), "pounds": ("mass", 0.45359237), "oz": ("mass", 0.028349523), "ounce": ("mass", 0.028349523), "ounces": ("mass", 0.028349523),
    "liter": ("vol", 1), "liters": ("vol", 1), "litre": ("vol", 1), "litres": ("vol", 1), "l": ("vol", 1), "ml": ("vol", 0.001),
    "gallon": ("vol", 3.785411784), "gallons": ("vol", 3.785411784),
    "celsius": ("temp", "c"), "centigrade": ("temp", "c"), "c": ("temp", "c"), "fahrenheit": ("temp", "f"), "f": ("temp", "f"), "kelvin": ("temp", "k"),
}
_rates: dict = {"t": 0.0, "r": None}


def get_rates() -> dict:
    if _rates["r"] and time.time() - _rates["t"] < 6 * 3600:
        return _rates["r"]
    d = net.get_json("https://open.er-api.com/v6/latest/USD", timeout=12)
    r = d.get("rates") or {}
    if "PKR" not in r:
        raise net.NetError("no rates")
    _rates.update(t=time.time(), r=r)
    return r


def _temp(v: float, a: str, b: str) -> float:
    c = v if a == "c" else ((v - 32) * 5 / 9 if a == "f" else v - 273.15)
    return c if b == "c" else (c * 9 / 5 + 32 if b == "f" else c + 273.15)


def convert(value: float, a: str, b: str):
    """-> (result, label of b) or None when the two names are not convertible. May raise NetError for currencies."""
    a, b = a.strip().lower(), b.strip().lower()
    ua, ub = _UNITS.get(a), _UNITS.get(b)
    if ua and ub and ua[0] == ub[0]:                                       # "pounds to kg" is a weight, not money
        if ua[0] == "temp":
            return _temp(value, ua[1], ub[1]), b
        return value * ua[1] / ub[1], b
    ca, cb = _CUR.get(a), _CUR.get(b)
    if ca and cb:
        r = get_rates()
        if ca not in r or cb not in r:
            return None
        return value / r[ca] * r[cb], _CURNAME.get(cb, cb)
    return None


def _convert_reply(value: float, a: str, b: str):
    try:
        res = convert(value, a, b)
    except Exception as e:
        log.info("convert failed: %s", e)
        return "I could not get the exchange rate right now."
    if res is None:
        return None
    out, label = res
    return "%s %s is about %s %s." % (_fmt_num(value), _CURNAME.get(_CUR.get(a.lower().strip(), ""), a.strip()), _fmt_num(out), label)


_U = r"([a-z]+(?: [a-z]+)??)"                               # lazy: "rupay hue" is a unit plus the closing words


@x2skill(r"^(?:convert |how much is |whats |what is )?(\d+(?:\.\d+)?) %s (?:in|to|into|equals in) %s$|"
         r"^(\d+(?:\.\d+)?) %s (?:ke |ki |ka )?kitne %s(?: hue| hote hain| hain| ka hai| bante hain| banenge| ke barabar hote hain)?$|"
         r"^(\d+(?:\.\d+)?) %s (?:ko )?%s (?:mein|me) (?:convert karo|convert kar do|badlo|batao)$" % (_U, _U, _U, _U, _U, _U))
def _convert(ctx, m, t):
    g = [x for x in m.groups() if x]
    if len(g) < 3:
        return None
    return _convert_reply(float(g[0]), g[1], g[2])


@x2skill(r"^(?:what is |whats |current |todays |today s |aaj ka |aaj ki )?(dollar|euro|pound|riyal|dirham|usd|yen|yuan) (?:rate|ka rate|ki rate|price|ka bhao)(?: today| aaj)?(?: kya hai| batao)?$")
def _rate(ctx, m, t):
    return _convert_reply(1.0, m.group(1), "pkr")


# ============================================================================ S5  to-do list
_TODO_PATH = os.path.join(DATA_DIR, "todo.json")
_tlock = threading.Lock()


def _load_todo() -> list:
    try:
        with open(_TODO_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save_todo(items: list) -> None:
    os.makedirs(os.path.dirname(_TODO_PATH), exist_ok=True)
    tmp = _TODO_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _TODO_PATH)


def pending() -> list[str]:
    """Texts of the open tasks (used by the briefing)."""
    return [x["text"] for x in _load_todo() if not x.get("done")]


def add_task(text: str) -> int:
    with _tlock:
        items = _load_todo()
        items.append({"text": text.strip(), "done": False, "added": time.strftime("%Y-%m-%d %H:%M")})
        _save_todo(items)
        return sum(1 for x in items if not x["done"])


_TD = r"(?:to[ -]?do|todo|task|tasks|(?:to )?do(?= (?:list|mein|me)\b))"      # strip_filler drops a leading "to", so "to do list" arrives as "do list"
_TD_LEAD = re.compile(r"^(?:to |for |called |named |ki |ka )+")


@x2skill(r"^(?:add|put|save|create|make)(?: a| an| new| another)* (?:task|todo|to[ -]?do|item)(?: called| named| for| to|:)? (.+)$|"
         r"^(?:add|put|save|include) (.+?) (?:to|in|into|on) (?:my |the |our )?%s(?: list)?$|"
         r"^(?:%s|kaam)(?: list)? (?:mein|me) (?:add karo|add kar do|likho|daalo|dalo|shamil karo|add) (.+)$|"
         r"^(?:task|kaam) add karo (.+)$|^(.+?) (?:%s)(?: list)? (?:mein|me) (?:add karo|add kar do|likho|daalo|dalo|shamil karo)$" % (_TD, _TD, _TD))
def _todo_add(ctx, m, t):
    text = _TD_LEAD.sub("", next(g for g in m.groups() if g)).strip()
    if not text:
        return None
    n = add_task(text)
    return "Added to your to-do list: %s. You have %d open task%s." % (text, n, "" if n == 1 else "s")


def _todo_list_text() -> str:
    items = pending()
    return "\n".join("%d. %s" % (i, x) for i, x in enumerate(items, 1))


@x2skill(r"^(?:what is|whats|show|read|list|tell me)(?: me)?(?: on)? (?:my |the )?(?:to[ -]?do|todo|tasks?)(?: list| items)?$|^(?:my |the )?(?:to[ -]?do|todo)(?: list)?$|^do list$|^(?:my )?tasks$|"
         r"^(?:what is|whats) on my (?:list|plate)$|^%s(?: list)? (?:dikhao|dikha do|batao|sunao|padho)$|^(?:aaj ke|mere) (?:kaam|tasks?)(?: batao| dikhao| sunao)?$|"
         r"^(?:mera|meri) (?:to[ -]?do|todo)(?: list)?(?: dikhao| batao| sunao)?$" % _TD)
def _todo_list(ctx, m, t):
    items = pending()
    if not items:
        return "Your to-do list is empty."
    agents.show(ctx, "TO-DO LIST", _todo_list_text())
    return "You have %d open task%s: %s." % (len(items), "" if len(items) == 1 else "s", ". ".join("%d, %s" % (i, x) for i, x in enumerate(items[:8], 1)))


def _nth_open(items: list, n: int):
    open_ = [i for i, x in enumerate(items) if not x.get("done")]
    return open_[n - 1] if 1 <= n <= len(open_) else None


@x2skill(r"^(?:mark |set )(?:task |item |number )(\d+) (?:as )?(?:done|complete|completed|finished)$|^(?:task|item) (\d+) (?:done|complete|ho gaya|hogaya|khatam)(?: karo| kar do)?$|"
         r"^(?:done|finish|complete) (?:task|item) (\d+)$|^(?:mark) (.+?) (?:as )?(?:done|complete|completed)$")
def _todo_done(ctx, m, t):
    g = next(x for x in m.groups() if x)
    with _tlock:
        items = _load_todo()
        if g.isdigit():
            idx = _nth_open(items, int(g))
        else:
            idx = next((i for i, x in enumerate(items) if not x.get("done") and g in x["text"].lower()), None)
            if idx is None:
                return None                                    # "mark my homework done" may be about something else
        if idx is None:
            return "I do not have a task number %s." % g
        items[idx]["done"] = True
        _save_todo(items)
    left = sum(1 for x in items if not x["done"])
    return "Done: %s. %d task%s left." % (items[idx]["text"], left, "" if left == 1 else "s")


@x2skill(r"^(?:remove|delete|cancel) (?:task|item) (\d+)$|^(?:task|item) (\d+) (?:hata do|delete karo|remove karo|hata den)$")
def _todo_remove(ctx, m, t):
    n = int(next(g for g in m.groups() if g))
    with _tlock:
        items = _load_todo()
        idx = _nth_open(items, n)
        if idx is None:
            return "I do not have a task number %d." % n
        gone = items.pop(idx)
        _save_todo(items)
    return "Removed: %s." % gone["text"]


@x2skill(r"^(?:clear|remove|delete) (?:all )?(?:completed|done|finished) (?:tasks|items)$|^(?:completed|done) tasks (?:clear|hata do)(?: karo)?$")
def _todo_clear_done(ctx, m, t):
    with _tlock:
        items = _load_todo()
        keep = [x for x in items if not x.get("done")]
        _save_todo(keep)
    n = len(items) - len(keep)
    return "Cleared %d finished task%s." % (n, "" if n == 1 else "s") if n else "There are no finished tasks to clear."


@x2skill(r"^(?:clear|delete|empty) (?:all )?(?:my |the )?(?:to[ -]?do|todo)(?: list)?$|^(?:clear|delete) all (?:my )?tasks$")
def _todo_clear_all(ctx, m, t):
    with _tlock:
        n = len(_load_todo())
        _save_todo([])
    return "Your to-do list is cleared (%d item%s)." % (n, "" if n == 1 else "s") if n else "Your to-do list was already empty."


# ============================================================================ S6  clipboard
def get_clipboard() -> str | None:
    """Text on the clipboard, or None (empty / not text / not available here)."""
    try:
        if os.name == "nt":
            import ctypes
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            u32.GetClipboardData.restype = ctypes.c_void_p
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            for _ in range(10):
                if u32.OpenClipboard(0):
                    break
                time.sleep(0.05)
            else:
                return None
            try:
                h = u32.GetClipboardData(13)                      # CF_UNICODETEXT
                if not h:
                    return None
                p = k32.GlobalLock(h)
                if not p:
                    return None
                try:
                    return ctypes.wstring_at(p) or None
                finally:
                    k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
        cmds = ([["pbpaste"]] if sys.platform == "darwin" else [["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"], ["xsel", "-ob"]])
        for cmd in cmds:
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=3)
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.decode("utf-8", "replace")
            except (OSError, subprocess.SubprocessError):
                continue
    except Exception:
        log.exception("clipboard read failed")
    return None


_NO_CLIP = "Your clipboard is empty, or what you copied is not text."


@x2skill(r"^(?:read|read out|tell me|show)(?: me)?(?: what is on| whats on)?(?: my| the)? clipboard$|^clipboard (?:padho|sunao|suna do|dikhao|dikha do|read karo)$|"
         r"^what did i (?:just )?copy$|^what(?:s| is) in (?:my |the )?clipboard$|^maine kya copy kiya(?: tha)?$")
def _clip_read(ctx, m, t):
    clip = get_clipboard()
    if not clip or not clip.strip():
        return _NO_CLIP
    agents.show(ctx, "CLIPBOARD", clip[:4000])
    one = re.sub(r"\s+", " ", clip).strip()
    return "You copied: %s%s" % (one[:400], "... and more, it is on the screen." if len(one) > 400 else "")


def summarize_text(ctx, text: str, sentences: int = 3) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    brain = getattr(ctx, "brain", None)
    if brain is not None and hasattr(brain, "complete"):
        out = brain.complete("Summarise this in %d short spoken sentences, plain text:\n\n%s" % (sentences, text[:6000]),
                             "You summarise text for a voice assistant. No markdown, no lists.", 250, 25)
        if out:
            return out
    return services.shorten(text, sentences, 420)


@x2skill(r"^(?:summari[sz]e|summary of|give me a summary of)(?: my| the)? clipboard$|^clipboard (?:ka )?(?:summary|khulasa|khulasah)(?: do| batao| sunao)?$|"
         r"^summari[sz]e (?:what i copied|this text|the copied text)$")
def _clip_summary(ctx, m, t):
    clip = get_clipboard()
    if not clip or not clip.strip():
        return _NO_CLIP
    return _bg(ctx, "Reading what you copied.", lambda: summarize_text(ctx, clip))


@x2skill(r"^(?:save|add|put|store)(?: my| the)? clipboard (?:to|in|as|into)(?: my)? notes?$|^clipboard (?:ko )?(?:note|notes) (?:mein|me) (?:save|add) (?:karo|kar do)$|^clipboard save karo$")
def _clip_save(ctx, m, t):
    clip = get_clipboard()
    if not clip or not clip.strip():
        return _NO_CLIP
    text = re.sub(r"\s+", " ", clip).strip()[:1000]
    ctx.mem.add_note(text)
    try:
        from . import features
        features._mirror_note(ctx, text)
    except Exception:
        log.exception("clipboard note mirror failed")
    return "Saved your clipboard as a note."


# ============================================================================ S7  quick page summary
_URL = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.I)


def fetch_page(url: str) -> tuple[str, str]:
    """(title, readable text) of a web page. http(s) only; 12 s timeout; at most ~1.5 MB read."""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    raw = net.get_bytes(url, timeout=12)[:1_500_000].decode("utf-8", "replace")
    title = html.unescape(re.sub(r"\s+", " ", (re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I) or [None, ""])[1])).strip()
    body = re.sub(r"<(script|style|noscript|svg|header|footer|nav|form)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    paras = [re.sub(r"<[^>]+>", " ", p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", body, flags=re.S | re.I)]
    paras = [re.sub(r"\s+", " ", html.unescape(p)).strip() for p in paras]
    text = " ".join(p for p in paras if len(p) > 40)
    if len(text) < 200:
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return title, text[:20000]


def _current_tab_url() -> str | None:
    """Windows only: Ctrl+L, Ctrl+C in the front browser, then read the clipboard (it replaces what was copied)."""
    from . import winctl
    if not winctl.supported():
        return None
    winctl.hotkey("ctrl", "l")
    time.sleep(0.2)
    winctl.hotkey("ctrl", "c")
    time.sleep(0.3)
    winctl.press("escape")
    clip = (get_clipboard() or "").strip()
    return clip if _URL.fullmatch(clip) or re.match(r"^[\w.-]+\.[a-z]{2,}(?:/\S*)?$", clip, re.I) else None


def _summarize_url(ctx, url: str) -> str:
    def work():
        title, text = fetch_page(url)
        if len(text) < 80:
            return agents.Report("Summary - " + (title or url), "There was not enough readable text on that page.", "There was not enough readable text on that page.", "summary")
        summ = summarize_text(ctx, text, 4)
        body = "## Summary\n%s\n\n## Page\n%s\n%s" % (summ, title, url)
        return agents.Report("Summary - " + (title or url)[:60], body, summ, "summary")
    return agents.run_background(ctx, "summary", work, "Reading the page now. One moment.", "I could not read that page. Check the link and the connection.")


@x2skill(r"^(?:summari[sz]e|summary of|give me a summary of|tldr|tl dr)(?: this| the| current| my)? (?:page|website|web page|site|tab|article)$|"
         r"^(?:is|iss|yeh|ye) (?:page|website|article|site) (?:ka|ki) (?:summary|khulasa|khulasah)(?: do| batao| sunao| karo)?$|"
         r"^(?:page|website|article) (?:ka )?(?:summari[sz]e|summary) (?:karo|do|batao)$")
def _page_summary(ctx, m, t):
    url = None
    try:
        url = _current_tab_url()
    except Exception:
        log.exception("tab url failed")
    if not url:
        return "I could not read the address of the current tab. Copy the link and say summarize the link."
    return _summarize_url(ctx, url)


@x2skill(r"^(?:summari[sz]e|summary of|give me a summary of|tldr|tl dr)(?: this| the| copied)? (?:link|url)$|^(?:link|url) (?:ka )?(?:summary|khulasa) (?:do|batao|karo)$|"
         r"^(?:summari[sz]e|summary of|tldr) (?:https? )?(\S*[a-z0-9]\.[a-z]{2,}\S*)$")
def _link_summary(ctx, m, t):
    raw = getattr(ctx, "raw_text", "") or ""
    hit = _URL.search(raw)
    url = hit.group(0).rstrip(".,)") if hit else None
    if not url and m.lastindex and m.group(1):
        url = m.group(1)
    if not url:
        clip = (get_clipboard() or "").strip()
        hit = _URL.search(clip)
        url = hit.group(0) if hit else None
    if not url:
        return "I did not find a link. Say it with the address, or copy the link first."
    return _summarize_url(ctx, url)


# ============================================================================ S8  daily journal
_JOURNAL: dict = {"step": 0, "answers": [], "t": 0.0}
_QUESTIONS = ("How was your day, in a few words?", "What did you get done today?", "What is the one thing for tomorrow?")
_Q_UR = ("آج کا دن کیسا رہا؟", "آج آپ نے کیا کیا؟", "کل کے لیے سب سے اہم کام کیا ہے؟")
_JTIMEOUT = 600


def journal_active() -> bool:
    return bool(_JOURNAL["step"]) and time.time() - _JOURNAL["t"] < _JTIMEOUT


def _jreset():
    _JOURNAL.update(step=0, answers=[], t=0.0)


def _question(i: int) -> str:
    return _Q_UR[i] if urdu.is_urdu() else _QUESTIONS[i]


@x2skill(r"^(?:start |begin |open |do |write )?(?:my |the |a |todays |daily )*(?:journal|diary|day recap)(?: entry)?(?: now)?$|"
         r"^(?:journal|diary|dairy) (?:likho|likhna hai|shuru karo|start karo)$|^(?:aaj ka|din ka) (?:recap|journal|khulasa)(?: likho| karo| shuru karo)?$|"
         r"^(?:let me |i want to )?(?:journal|write (?:my|a) journal)$|^recap my day$")
def _journal_start(ctx, m, t):
    _JOURNAL.update(step=1, answers=[], t=time.time())
    return "Let us do your journal. Say cancel journal any time. " + _question(0)


@x2skill(r"^(?:cancel|stop|skip|end|forget)(?: the| my)? (?:journal|diary)(?: entry)?$|^journal (?:cancel|band karo|rehne do)$")
def _journal_cancel(ctx, m, t):
    if not _JOURNAL["step"]:
        return "There is no journal entry in progress."
    _jreset()
    return "Journal cancelled. Nothing was saved."


@x2skill(r"^(?:read|show|open)(?: me)?(?: my| the| last| latest)* journal$|^journal (?:padho|dikhao|sunao)$")
def _journal_read(ctx, m, t):
    name = docs.find_report("journal")
    text = docs.read_report(name) if name else None
    if not text:
        return "You have no journal entries yet. Say journal likho to start one."
    agents.show(ctx, "JOURNAL - " + name, text)
    return agents.read_aloud(text, 500) or "That entry is empty."


def _finish_journal(ctx, answers: list) -> str:
    today = time.strftime("%A %d %B %Y")
    title = "Journal - " + today

    def work():
        day, done, tomorrow = answers
        reflect = None
        brain = getattr(ctx, "brain", None)
        if brain is not None and hasattr(brain, "complete"):
            reflect = brain.complete("Day: %s\nDone: %s\nTomorrow: %s\n\nWrite ONE kind, practical sentence of reflection." % (day, done, tomorrow),
                                     "You are a calm journal companion. Plain text, one sentence.", 80, 15)
        blocks = [("h1", _QUESTIONS[0]), ("p", day), ("h1", _QUESTIONS[1]), ("p", done), ("h1", _QUESTIONS[2]), ("p", tomorrow)]
        if reflect:
            blocks += [("h1", "Reflection"), ("p", reflect)]
        path = docs.write_docx(docs.unique_path("Journal", ".docx"), title, blocks)
        body = "\n\n".join("## %s\n%s" % (q, a) for q, a in zip(_QUESTIONS, answers))
        agents.record("journal", title, body, "Journal saved.", path)
        agents.show(ctx, title, body + ("\n\n## Reflection\n" + reflect if reflect else ""))
        try:
            add_task(tomorrow)
            extra = " I added %s to your to-do list." % tomorrow
        except Exception:
            log.exception("journal todo failed")
            extra = ""
        return "Journal saved as %s in your reports folder.%s%s" % (os.path.basename(path), extra, (" " + reflect) if reflect else "")
    return _bg(ctx, "Thank you. Saving your journal.", work)


def _journal_answer(ctx, text: str):
    if not journal_active():
        _jreset()
        return None
    raw = _S().strip_wake_raw(getattr(ctx, "raw_text", "") or "")
    if raw and len(raw) <= 600:
        text = raw
    _JOURNAL["answers"].append(text.strip())
    _JOURNAL["t"] = time.time()
    step = _JOURNAL["step"]
    if step >= 3:
        answers = list(_JOURNAL["answers"])
        _jreset()
        return _finish_journal(ctx, answers)
    _JOURNAL["step"] = step + 1
    return _question(step)


@x2skill(r"^(.+)$", first=True)
def _journal_catch(ctx, m, t):
    if not _JOURNAL["step"]:
        return None
    if re.match(r"^(?:cancel|stop|skip|end|forget)(?: the| my)? (?:journal|diary)(?: entry)?$|^journal (?:cancel|band karo|rehne do)$", t):
        return None                                           # let the cancel skill handle it
    return _journal_answer(ctx, t)


@x2skill(r"^journal answer (.+)$", first=True)
def _journal_catch_urdu(ctx, m, t):
    return _journal_answer(ctx, m.group(1))
