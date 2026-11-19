"""News desk: breaking headlines for a chosen country, the world, geopolitics or a topic - in English or Urdu.

Source: Google News RSS (free, no key). Country editions are used where Google has one; anything else falls back
to a "<country> when:1d" search so every country still works.
"""
from __future__ import annotations

import html
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import net

# code -> (English name, Urdu name, Google News English edition id)
COUNTRIES = {
    "PK": ("Pakistan", "پاکستان", "en-PK"), "IN": ("India", "بھارت", "en-IN"), "US": ("the United States", "امریکہ", "en-US"),
    "GB": ("the United Kingdom", "برطانیہ", "en-GB"), "CN": ("China", "چین", None), "IR": ("Iran", "ایران", None),
    "AF": ("Afghanistan", "افغانستان", None), "SA": ("Saudi Arabia", "سعودی عرب", None), "AE": ("the UAE", "متحدہ عرب امارات", "en-AE"),
    "TR": ("Turkey", "ترکی", None), "RU": ("Russia", "روس", None), "UA": ("Ukraine", "یوکرین", None),
    "IL": ("Israel", "اسرائیل", "en-IL"), "PS": ("Palestine", "فلسطین", None), "BD": ("Bangladesh", "بنگلہ دیش", "en-BD"),
    "JP": ("Japan", "جاپان", None), "DE": ("Germany", "جرمنی", "en-DE"), "FR": ("France", "فرانس", "en-FR"),
    "CA": ("Canada", "کینیڈا", "en-CA"), "AU": ("Australia", "آسٹریلیا", "en-AU"), "IQ": ("Iraq", "عراق", None),
    "SY": ("Syria", "شام", None), "YE": ("Yemen", "یمن", None), "EG": ("Egypt", "مصر", "en-EG"), "QA": ("Qatar", "قطر", None),
    "KW": ("Kuwait", "کویت", None), "LK": ("Sri Lanka", "سری لنکا", "en-LK"), "NP": ("Nepal", "نیپال", "en-NP"),
    "MY": ("Malaysia", "ملائیشیا", "en-MY"), "ID": ("Indonesia", "انڈونیشیا", "en-ID"), "SG": ("Singapore", "سنگاپور", "en-SG"),
    "NG": ("Nigeria", "نائجیریا", "en-NG"), "ZA": ("South Africa", "جنوبی افریقہ", "en-ZA"), "BR": ("Brazil", "برازیل", None),
    "IT": ("Italy", "اٹلی", "en-IT"), "ES": ("Spain", "سپین", None), "KR": ("South Korea", "جنوبی کوریا", None),
    "KP": ("North Korea", "شمالی کوریا", None), "TW": ("Taiwan", "تائیوان", "en-TW"), "LB": ("Lebanon", "لبنان", None),
    "JO": ("Jordan", "اردن", None), "OM": ("Oman", "عمان", None), "BH": ("Bahrain", "بحرین", None), "MX": ("Mexico", "میکسیکو", None),
}
_ALIASES = {
    "PK": "pakistan pakistani", "IN": "india indian bharat", "US": "usa us america american united states",
    "GB": "uk britain british england united kingdom", "CN": "china chinese", "IR": "iran iranian", "AF": "afghanistan afghan",
    "SA": "saudi saudi arabia", "AE": "uae dubai emirates", "TR": "turkey turkish turkiye", "RU": "russia russian",
    "UA": "ukraine ukrainian", "IL": "israel israeli", "PS": "palestine palestinian gaza", "BD": "bangladesh bangladeshi",
    "JP": "japan japanese", "DE": "germany german", "FR": "france french", "CA": "canada canadian", "AU": "australia australian",
    "IQ": "iraq iraqi", "SY": "syria syrian", "YE": "yemen yemeni", "EG": "egypt egyptian", "QA": "qatar", "KW": "kuwait",
    "LK": "sri lanka", "NP": "nepal", "MY": "malaysia", "ID": "indonesia", "SG": "singapore", "NG": "nigeria",
    "ZA": "south africa", "BR": "brazil", "IT": "italy", "ES": "spain", "KR": "south korea", "KP": "north korea",
    "TW": "taiwan", "LB": "lebanon", "JO": "jordan", "OM": "oman", "BH": "bahrain", "MX": "mexico",
}
# multi-word aliases are matched on the whole sentence, single words on tokens
_ALIAS_LIST = sorted(((a, c) for c, s in _ALIASES.items() for a in
                      re.findall(r"united states|united kingdom|saudi arabia|south africa|north korea|south korea|sri lanka|[a-z]+", s)),
                     key=lambda x: -len(x[0]))

ALIAS_TOKENS = {w for v in _ALIASES.values() for w in v.split()}

TOPICS = {   # keyword regex -> (key, google topic id or None, English label, Urdu label)
    "world": (r"\b(?:world|global|globe|international|worldwide)\b", "WORLD", "world", "عالمی"),
    "geopolitics": (r"\b(?:geo ?politic\w*|foreign policy|diplomacy|diplomatic|global politics|world politics|conflicts?|wars?)\b",
                    None, "geopolitics", "عالمی سیاست"),
    "business": (r"\b(?:business|economy|economic|markets?|finance|financial|stocks?)\b", "BUSINESS", "business", "کاروباری"),
    "technology": (r"\b(?:tech|technology|ai|gadgets?)\b", "TECHNOLOGY", "technology", "ٹیکنالوجی"),
    "sports": (r"\b(?:sports?|cricket|football|soccer)\b", "SPORTS", "sports", "کھیلوں"),
    "science": (r"\bscience\b", "SCIENCE", "science", "سائنس"),
    "health": (r"\bhealth\b", "HEALTH", "health", "صحت"),
    "entertainment": (r"\b(?:entertainment|showbiz|bollywood|lollywood|movies?)\b", "ENTERTAINMENT", "entertainment", "تفریحی"),
}
_GEO_EN = 'geopolitics OR "foreign policy" OR diplomacy OR "peace talks" OR sanctions OR conflict'
_GEO_UR = "عالمی سیاست OR جنگ OR سفارتی OR پابندیاں OR مذاکرات"


@dataclass
class Item:
    title: str
    source: str = ""


@dataclass
class Result:
    items: list
    label_en: str
    label_ur: str
    kind: str = "topic"          # country | world | topic | extra


def country_of(text: str):
    """Country code mentioned in a (lower-case, normalised) sentence, or None."""
    t = " %s " % text
    for alias, code in _ALIAS_LIST:
        if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(alias), t):
            if alias in ("us", "uk") and not re.search(r"(?:of|in|from|for|about) (?:the )?%s\b" % alias, t):
                continue                                   # "tell us the news" is not about the US
            return code
    for code, (_, ur, _) in COUNTRIES.items():
        if ur in text:
            return code
    return None


def topic_of(text: str) -> str | None:
    for key, (rx, *_rest) in TOPICS.items():
        if re.search(rx, text):
            return key
    return None


# ---------------------------------------------------------------------------- fetching
def _parse(xml: bytes, n: int) -> list:
    out, seen = [], set()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    for it in root.iter("item"):
        raw = html.unescape((it.findtext("title") or "").strip())
        src = (it.findtext("source") or "").strip()
        title = raw.rsplit(" - ", 1)[0].strip() if " - " in raw else raw
        if not src and " - " in raw:
            src = raw.rsplit(" - ", 1)[1].strip()
        key = re.sub(r"\W+", "", title.lower())[:60]
        if title and key not in seen:
            seen.add(key)
            out.append(Item(title, src))
        if len(out) >= n:
            break
    return out


def _edition(region: str, urdu: bool) -> dict:
    if urdu:
        return {"hl": "ur", "gl": region if region in ("PK", "IN") else "PK", "ceid": "%s:ur" % (region if region in ("PK", "IN") else "PK")}
    return {"hl": "en-%s" % region, "gl": region, "ceid": "%s:en" % region}


def _get(url: str, params: dict, n: int) -> list:
    return _parse(net.get_bytes(url, params, timeout=8), n)


def _search(query: str, urdu: bool, n: int, region: str = "PK") -> list:
    p = _edition(region if urdu else "US", urdu)
    p["q"] = query + " when:1d"
    return _get("https://news.google.com/rss/search", p, n)


def fetch(country: str | None = None, topic: str | None = None, extra: str = "", urdu: bool = False,
          n: int = 5, home: str = "PK") -> Result:
    """Headlines. country = ISO code; topic = key of TOPICS; extra = free-text subject (e.g. 'bitcoin')."""
    n = max(1, min(int(n), 10))
    tl = TOPICS.get(topic or "", (None, None, "", ""))
    if extra:
        items = _search(extra, urdu, n, home)
        return Result(items, extra, extra, "extra")
    if country:
        en, ur, edition = COUNTRIES.get(country, (country, country, None))
        if topic == "geopolitics":
            items = _search("%s (%s)" % (ur if urdu else en.replace("the ", ""), _GEO_UR if urdu else _GEO_EN), urdu, n, home)
        elif topic and tl[1]:
            items = _search("%s %s" % (ur if urdu else en.replace("the ", ""), tl[3] if urdu else tl[2]), urdu, n, home)
        else:
            items = []
            if urdu and country in ("PK", "IN"):
                items = _get("https://news.google.com/rss", _edition(country, True), n)
            elif not urdu and edition:
                items = _get("https://news.google.com/rss", _edition(edition.split("-")[1], False), n)
            if len(items) < min(n, 3):                       # no edition for this country: search it instead
                items = _search(ur if urdu else en.replace("the ", ""), urdu, n, home)
        return Result(items, en, ur, "country")
    if topic == "geopolitics":
        return Result(_search(_GEO_UR if urdu else _GEO_EN, urdu, n, home), "geopolitics", "عالمی سیاست", "topic")
    gid = tl[1] or "WORLD"
    p = _edition(home if not urdu else "PK", urdu)
    items = _get("https://news.google.com/rss/headlines/section/topic/" + gid, p, n)
    label = tl[2] or "world"
    return Result(items, label, "دنیا" if gid == "WORLD" else tl[3], "world" if gid == "WORLD" else "topic")


# ---------------------------------------------------------------------------- wording
def spoken(res: Result, urdu: bool, breaking: bool = True) -> str:
    """The sentence Jarvis reads out: a short intro, then the headlines."""
    if not res.items:
        return "ابھی خبریں نہیں مل رہیں۔" if urdu else "I couldn't find any headlines for that right now."
    n = len(res.items)
    if urdu:
        if res.kind == "world":
            head = "یہ ہیں دنیا بھر کی تازہ ترین سرخیاں۔"
        else:
            head = "یہ ہیں %s کی تازہ ترین سرخیاں۔" % res.label_ur
        return head + " " + " ".join(it.title.rstrip(" .۔") + "۔" for it in res.items)
    what = "breaking headlines" if breaking else "headlines"
    if res.kind == "country":
        where = "from " + res.label_en
    elif res.kind == "world":
        where = "from around the world"
    else:
        where = "on " + res.label_en
    head = "Here are the top %d %s %s." % (n, what, where)
    return head + " " + " ... ".join(it.title.rstrip(" .") + "." for it in res.items)


def briefing(home: str, urdu: bool, per: int = 3) -> tuple[str, list]:
    """Morning briefing: the home country, then the world, then geopolitics."""
    parts, items = [], []
    for kw in ({"country": home}, {"topic": "world"}, {"topic": "geopolitics"}):
        try:
            r = fetch(urdu=urdu, n=per, home=home, **kw)
        except Exception:
            continue
        if r.items:
            parts.append(spoken(r, urdu))
            items += r.items
    if not parts:
        return ("خبریں حاصل نہیں ہو سکیں۔" if urdu else "I couldn't reach the news feed right now."), []
    intro = "آپ کی روزانہ خبروں کا خلاصہ۔ " if urdu else "Here is your news briefing. "
    return intro + " ".join(parts), items


# ---------------------------------------------------------------------------- optional daily briefing at a set time
def start_daily(app) -> None:
    """JARVIS_DAILY_NEWS=08:00 -> Jarvis reads the briefing once a day at that time while he is running."""
    import os
    at = (os.environ.get("JARVIS_DAILY_NEWS") or "").strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", at)
    if not m:
        return
    hh, mm = int(m.group(1)), int(m.group(2))

    def loop():
        last = ""
        while getattr(app, "running", True):
            now = time.localtime()
            today = time.strftime("%Y-%m-%d", now)
            if now.tm_hour == hh and now.tm_min == mm and last != today:
                last = today
                try:
                    from . import urdu
                    text, items = briefing(app.cfg.news_region, urdu.mode() == "ur")
                    for it in items:
                        app.hud_post("log", "src", "news  " + it.title)
                    app.say_async(text)
                except Exception:
                    pass
            time.sleep(20)
    threading.Thread(target=loop, daemon=True, name="daily-news").start()
