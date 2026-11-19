# -*- coding: utf-8 -*-
"""Urdu support for Jarvis (English <-> Urdu switchable).

  * mode()/set_mode()      "en" or "ur"; saved in data/language.txt, default from JARVIS_UI_LANGUAGE.
  * has_urdu()             does a sentence contain Urdu / Arabic script?
  * to_command()           Urdu sentence -> the English command the skills already understand
                           ("یوٹیوب کھولو" -> "open youtube"). Free text such as a WhatsApp message is kept in Urdu.
  * localize()             English reply -> Urdu (ready-made phrases first, then the AI model translates).
  * voice_for()            picks the Urdu neural voice for Urdu text, the normal voice otherwise.
"""
from __future__ import annotations

import difflib
import os
import re
import time

from .config import ROOT

# ---------------------------------------------------------------------------- script helpers
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_MARKS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED\u200c\u200d\u200e\u200f]")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۃ": "ہ", "ة": "ہ", "ۓ": "ے"})
_PUNCT = re.compile(r"[۔؟،؛!?,;:\"“”«»()\[\]]+|(?<!\d)\.(?!\d)")


def has_urdu(text: str) -> bool:
    return bool(_ARABIC.search(text or ""))


def urdu_ratio(text: str) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    return sum(1 for c in letters if _ARABIC.match(c)) / len(letters) if letters else 0.0


def _clean(text: str) -> str:
    t = _MARKS.sub("", text or "").translate(_FOLD).translate(_DIGITS)
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------- language mode
_STORE = os.path.join(ROOT, "data", "language.txt")
_mode = None


def mode() -> str:
    global _mode
    if _mode is None:
        want = ""
        try:
            with open(_STORE, encoding="utf-8") as f:
                want = f.read().strip().lower()
        except OSError:
            pass
        if want not in ("en", "ur"):
            env = (os.environ.get("JARVIS_UI_LANGUAGE") or "english").strip().lower()
            want = "ur" if env.startswith(("ur", "اردو")) else "en"
        _mode = want
    return _mode


def set_mode(m: str, save: bool = True) -> str:
    global _mode
    _mode = "ur" if str(m).lower().startswith("u") else "en"
    if save:
        try:
            os.makedirs(os.path.dirname(_STORE), exist_ok=True)
            with open(_STORE, "w", encoding="utf-8") as f:
                f.write(_mode)
        except OSError:
            pass
    return _mode


def is_urdu() -> bool:
    return mode() == "ur"


# ---------------------------------------------------------------------------- wake word & control phrases
_WAKE_UR = {"جارویس", "جاروس", "جارویز", "جرویس", "جارویش", "جاروس", "جاوس", "جارواس", "جارویسس", "جارفس", "جاروِس", "چارویس"}
_WAKE_UR = {_clean(w) for w in _WAKE_UR}
_JV = "جارویس"


def _is_wake_tok(tok: str) -> bool:
    return tok in _WAKE_UR or (len(tok) >= 4 and difflib.SequenceMatcher(None, tok, _JV).ratio() >= 0.78)


def has_wake(text: str) -> bool:
    toks = _clean(text).split()
    return any(_is_wake_tok(t) for t in toks[:4] + toks[-2:])


def strip_wake(text: str) -> str:
    """Remove Urdu-script wake words from the start / end (keeps everything else exactly as spoken)."""
    toks = text.strip().split()
    lead = {"ہے", "ہیلو", "او", "اے", "اوکے", "ارے", "سنو"}

    def key(i):
        return _clean(toks[i])
    while toks and (_is_wake_tok(key(0)) or (key(0) in lead and len(toks) > 1 and _is_wake_tok(key(1)))):
        toks.pop(0)
    while toks and _is_wake_tok(key(-1)):
        toks.pop()
    return " ".join(toks) if toks else text.strip()


_STOP_UR = {"رکو", "رک جاؤ", "رک جاو", "بس", "بس کرو", "بس کر دو", "بس کریں", "چپ", "چپ ہو جاؤ", "چپ ہو جاو", "چپ کرو", "خاموش",
            "خاموش ہو جاؤ", "خاموش ہو جاو", "بولنا بند کرو", "بولنا بند", "ٹھہرو", "رکیں", "ٹھیک ہے بس", "سٹاپ", "اسٹاپ"}
_STOP_UR = {_clean(x) for x in _STOP_UR}
_EXIT_UR = {"خدا حافظ", "الوداع", "بند ہو جاؤ", "بند ہو جاو", "شٹ ڈاؤن", "شٹ ڈاون", "بند کرو", "بند", "الله حافظ", "اللہ حافظ",
            "الوداع جارویس", "بند ہوجاو", "بند ہو جائیں", "پروگرام بند کرو", "بند کر دو"}
_EXIT_UR = {_clean(x) for x in _EXIT_UR}


def control(text: str):
    """'stop' | 'exit' | None for an Urdu sentence (the English words are handled elsewhere)."""
    if not has_urdu(text):
        return None
    addressed = has_wake(text)
    t = _clean(strip_wake(text))
    if t in _STOP_UR:
        return "stop"
    if addressed and t in _EXIT_UR:
        return "exit"
    if t in ("خدا حافظ", "الوداع", "اللہ حافظ", "الله حافظ", "الوداع"):
        return "exit" if addressed else None
    return None


# ---------------------------------------------------------------------------- vocabulary
def alt(*words) -> str:
    return "(?:" + "|".join(re.escape(_clean(w)) for w in sorted(words, key=len, reverse=True)) + ")"


APPS = {   # Urdu spelling(s) -> English name the skills know
    "واٹس ایپ": "whatsapp", "واٹس اپ": "whatsapp", "وٹس ایپ": "whatsapp", "واٹسایپ": "whatsapp", "وہاٹس ایپ": "whatsapp",
    "یوٹیوب": "youtube", "یو ٹیوب": "youtube", "یوٹوب": "youtube", "گوگل": "google", "کروم": "chrome", "گوگل کروم": "chrome",
    "فیس بک": "facebook", "فیسبک": "facebook", "انسٹاگرام": "instagram", "انسٹا گرام": "instagram", "ٹویٹر": "twitter",
    "ٹوئٹر": "twitter", "لنکڈ ان": "linkedin", "لنکڈان": "linkedin", "ٹک ٹاک": "tiktok", "ٹیلیگرام": "telegram", "ٹیلی گرام": "telegram",
    "اسپاٹیفائی": "spotify", "سپاٹیفائی": "spotify", "نیٹ فلکس": "netflix", "جی میل": "gmail", "ایج": "edge", "فائر فاکس": "firefox",
    "نوٹ پیڈ": "notepad", "کیلکولیٹر": "calculator", "کیلکیولیٹر": "calculator", "پینٹ": "paint", "ٹاسک مینیجر": "task manager",
    "ٹاسک منیجر": "task manager", "سیٹنگز": "settings", "سیٹنگ": "settings", "ایکسل": "excel", "ورڈ": "word", "پاورپوائنٹ": "powerpoint",
    "پاور پوائنٹ": "powerpoint", "فائل ایکسپلورر": "file explorer", "کمانڈ پرامپٹ": "command prompt", "ٹرمینل": "terminal",
    "وی ایس کوڈ": "vs code", "زوم": "zoom", "سکائپ": "skype", "ڈسکورڈ": "discord", "کیمرہ": "camera", "کیمرا": "camera",
    "براؤزر": "browser", "ڈاؤن لوڈز": "downloads", "ڈاؤنلوڈز": "downloads", "ڈیسک ٹاپ": "desktop", "ڈاکومنٹس": "documents",
    "کمپیوٹر": "computer", "سٹیم": "steam", "پلے اسٹور": "play store", "گوگل میپس": "google maps", "میپس": "maps",
    "گوگل نیوز": "google news", "چیٹ جی پی ٹی": "chatgpt", "جیمنی": "gemini", "ایمیزون": "amazon", "ڈراز": "daraz", "اولیکس": "olx",
}
PLACES = {"لاہور": "lahore", "کراچی": "karachi", "اسلام آباد": "islamabad", "راولپنڈی": "rawalpindi", "فیصل آباد": "faisalabad",
          "ملتان": "multan", "پشاور": "peshawar", "کوئٹہ": "quetta", "سرگودھا": "sargodha", "سیالکوٹ": "sialkot",
          "گوجرانوالہ": "gujranwala", "حیدرآباد": "hyderabad", "دہلی": "delhi", "ممبئی": "mumbai", "لندن": "london", "دبئی": "dubai",
          "نیویارک": "new york", "نیو یارک": "new york", "ریاض": "riyadh", "استنبول": "istanbul", "بیجنگ": "beijing", "ٹوکیو": "tokyo",
          "پیرس": "paris", "برلن": "berlin", "واشنگٹن": "washington", "ماسکو": "moscow", "تہران": "tehran", "کابل": "kabul",
          "ڈھاکہ": "dhaka", "مکہ": "mecca", "مدینہ": "medina", "جدہ": "jeddah", "سڈنی": "sydney", "ٹورنٹو": "toronto"}
APPS.update(PLACES)
APPS = {_clean(k): v for k, v in APPS.items()}
_APP_KEYS = sorted(APPS, key=len, reverse=True)

_PARTICLES = {"کو", "کا", "کی", "کے", "پر", "میں", "سے", "ذرا", "زرا", "مجھے", "ہمیں", "پلیز", "براہ", "مہربانی", "اب", "ایک", "یہ",
              "وہ", "اس", "تو", "ہی", "بھی", "نا", "نہ", "جی", "اچھا", "اچھی", "لیے", "لئے", "ذرہ"}

_NUM_WORDS = {"ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10, "پندرہ": 15,
              "بیس": 20, "تیس": 30, "چالیس": 40, "پینتالیس": 45, "پچاس": 50, "ساٹھ": 60, "ستر": 70, "اسی": 80, "نوے": 90, "سو": 100,
              "آدھا": 0, "آدھ": 0}
_NUM_WORDS = {_clean(k): v for k, v in _NUM_WORDS.items()}


def num(tok: str):
    tok = _clean(tok)
    if tok.isdigit():
        return int(tok)
    v = _NUM_WORDS.get(tok)
    return v if v else None


def ent(s: str) -> str:
    """Swap Urdu-spelt app / site names for English ones; everything else is left as spoken."""
    s = " %s " % _clean(s)
    for k in _APP_KEYS:
        s = re.sub(r"(?<=\s)%s(?=\s)" % re.escape(k), APPS[k], s)
    return re.sub(r"\s+", " ", s).strip()


def obj(s: str) -> str:
    toks = _clean(s).split()
    while toks and toks[0] in _PARTICLES:
        toks.pop(0)
    while toks and toks[-1] in _PARTICLES:
        toks.pop()
    return ent(" ".join(toks))


DO = r"(?:\s+" + alt("دو", "دیں", "دیجیے", "دیجئے", "دیجیئے", "لو", "لیں") + r")?"
V_OPEN = alt("کھولو", "کھولیں", "کھولیے", "کھولئے", "کھولیئے", "کھول", "اوپن کرو", "اوپن کریں", "اوپن", "لانچ کرو", "لانچ کریں",
             "چالو کرو", "چالو کریں", "شروع کرو", "شروع کریں", "اوپن کر") + DO
V_CLOSE = alt("بند کرو", "بند کریں", "بند کیجیے", "بند کیجئے", "بند کر", "کلوز کرو", "کلوز کریں", "ختم کرو", "ختم کریں", "بند") + DO
V_PLAY = alt("چلاؤ", "چلاو", "چلائیں", "چلایئے", "چلائیے", "چلا", "لگاؤ", "لگاو", "لگائیں", "لگا", "بجاؤ", "بجاو", "بجائیں",
             "سناؤ", "سناو", "سنائیں", "سنا", "پلے کرو", "پلے کریں", "پلے", "دکھاؤ", "دکھاو", "دکھائیں", "دکھا") + DO
V_SEARCH = alt("سرچ کرو", "سرچ کریں", "سرچ", "تلاش کرو", "تلاش کریں", "تلاش", "ڈھونڈو", "ڈھونڈیں", "ڈھونڈ", "گوگل کرو", "گوگل کریں",
               "ڈھونڈ کر دو", "ڈھونڈ کے دو") + DO
V_TYPE = alt("ٹائپ کرو", "ٹائپ کریں", "ٹائپ کر", "لکھو", "لکھیں", "لکھیے", "لکھئے", "لکھ") + DO
V_SEND = alt("بھیجو", "بھیج", "بھیجیں", "بھیجیے", "بھیجئے", "سینڈ کرو", "سینڈ کریں", "سینڈ", "ارسال کرو", "ارسال کریں") + DO
V_MSG = alt("میسج کرو", "میسج کریں", "میسج بھیجو", "میسج بھیج", "مسیج کرو", "پیغام بھیجو", "پیغام بھیج", "پیغام دو", "میسج دو",
            "میسج", "پیغام", "ٹیکسٹ کرو", "ٹیکسٹ", "لکھو", "لکھ", "بتاؤ", "بتاو", "بتائیں", "کہو", "کہہ دو", "بولو") + DO

YES = {"ہاں", "جی ہاں", "جی", "ٹھیک ہے", "بالکل", "اوکے", "او کے", "کر دو", "کردو", "کریں", "ہاں جی", "جی بالکل", "بھیج دو",
       "بھیجو", "یس", "صحیح", "درست", "ہاں کر دو", "جی کر دو"}
NO = {"نہیں", "نہ", "جی نہیں", "نہیں نہیں", "کینسل", "رہنے دو", "مت کرو", "رہنے دیں", "منسوخ", "نو", "نا", "نہ کرو", "چھوڑو"}
YES, NO = {_clean(x) for x in YES}, {_clean(x) for x in NO}

NEWS_KW = alt("خبریں", "خبر", "خبرین", "ہیڈ لائنز", "ہیڈلائنز", "ہیڈ لائن", "سرخیاں", "سرخی", "بریکنگ نیوز", "نیوز", "تازہ ترین", "تازہ خبریں",
              "نیوز بلیٹن", "خبرنامہ", "خلاصہ")
_TOPIC_UR = {   # Urdu keyword -> English word the news skill understands
    "جغرافیائی سیاست": "geopolitics", "جیو پولیٹکس": "geopolitics", "جیو پالیٹکس": "geopolitics", "عالمی سیاست": "geopolitics",
    "بین الاقوامی سیاست": "geopolitics", "جنگ": "war", "سفارتی": "diplomacy",
    "عالمی": "world", "دنیا": "world", "بین الاقوامی": "world", "ورلڈ": "world", "گلوبل": "world",
    "کھیل": "sports", "اسپورٹس": "sports", "کرکٹ": "cricket", "کاروبار": "business", "بزنس": "business", "معیشت": "business",
    "ٹیکنالوجی": "technology", "ٹیک": "technology", "سائنس": "science", "صحت": "health", "تفریح": "entertainment", "شوبز": "entertainment",
}
_TOPIC_UR = {_clean(k): v for k, v in _TOPIC_UR.items()}


def _news_command(t: str) -> str | None:
    from . import newsdesk
    if not re.search(NEWS_KW, t):
        return None
    words = []
    if re.search(alt("بریکنگ", "تازہ ترین", "تازہ", "فوری", "ابھی کی"), t):
        words.append("breaking")
    topic = next((v for k, v in sorted(_TOPIC_UR.items(), key=lambda kv: -len(kv[0])) if re.search(r"(?<!\S)%s(?!\S)" % re.escape(k), t)), "")
    code = newsdesk.country_of(t)
    place = ""
    if code:
        place = " from " + newsdesk.COUNTRIES[code][0].replace("the ", "")
    elif not topic and re.search(alt("خلاصہ", "نیوز بلیٹن", "خبرنامہ", "روزانہ"), t):
        return "news briefing"
    if re.search(alt("خلاصہ", "روزانہ", "بلیٹن"), t) and not code and not topic:
        return "news briefing"
    n = next((num(x) for x in t.split() if num(x) and 1 <= (num(x) or 0) <= 10), None)
    top = ("top %d " % n) if n else ""
    return ("%s%s%s news%s" % (top, " ".join(words) + " " if words else "", topic + " " if topic else "", place)).replace("  ", " ").strip()



# ---------------------------------------------------------------------------- briefing / speed / reports / modes / agents (features.py)
_AGENTS_UR = {"سکاؤٹ": "scout", "اسکاؤٹ": "scout", "سکاوٹ": "scout", "ہیرالڈ": "herald", "ہیرلڈ": "herald", "وائجر": "voyager",
              "سوشل": "social", "ایس ای او": "seo", "ایس ای او": "seo", "میوز": "muse"}
_AGENTS_UR = {_clean(k): v for k, v in _AGENTS_UR.items()}
_AG_VERBS = re.compile(r"\s*(?:کے بارے میں|کے لیے|پر|کی|کا|کے)?\s*(?:ریسرچ|تحقیق|پلان|کیپشن|کیپشنز)?\s*(?:کرو|کریں|کر دو|کردو|لکھو|لکھیں|بناؤ|بنا دو|بتاؤ|بتاو|دو)?$")
_OPS_UR = {"ضرب": "times", "گنا": "times", "جمع": "plus", "منفی": "minus", "تقسیم": "divided by"}
_OPS_UR = {_clean(k): v for k, v in _OPS_UR.items()}



_PRAYER_UR = {"فجر": "fajr", "ظہر": "dhuhr", "عصر": "asr", "مغرب": "maghrib", "عشاء": "isha", "عشا": "isha"}
_PRAYER_UR = {_clean(k): v for k, v in _PRAYER_UR.items()}
_CUR_UR = {"ڈالر": "dollars", "یورو": "euros", "پاؤنڈ": "pounds", "ریال": "riyals", "درہم": "dirhams", "روپے": "rupees", "روپیہ": "rupees",
           "روپیے": "rupees", "یوآن": "yuan", "ین": "yen"}
_CUR_UR = {_clean(k): v for k, v in _CUR_UR.items()}
_LANG_UR = {"انگریزی": "english", "اردو": "urdu", "رومن اردو": "roman urdu"}
_LANG_UR = {_clean(k): v for k, v in _LANG_UR.items()}
_NUMWORDS_UR = {"ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10}


def _journal_command(t: str) -> str | None:
    from importlib import import_module
    try:
        active = import_module(".extras2", __package__).journal_active()
    except Exception:
        return None
    if not active:
        return None
    if re.match(r"^(?:جرنل|ڈائری) (?:منسوخ|بند کرو|رہنے دو)$", t):
        return "cancel journal"
    return "journal answer " + t


def _part_b_command(t: str) -> str | None:
    """Urdu phrases for S1-S8 (prayer times, focus timer, translate, converters, to-do, clipboard, page summary, journal)."""
    j = _journal_command(t)
    if j:
        return j
    # S1 prayer times
    if re.match(r"^(?:آج کی )?نماز کے اوقات(?: بتاؤ| دکھاؤ)?$|^نماز کا وقت(?: بتاؤ)?$|^نماز ٹائمنگ(?: بتاؤ)?$", t):
        return "prayer times"
    if re.match(r"^(?:اگلی|اگلا) نماز(?: کب ہے| کب ہوگی| کتنی دیر میں)?$|^نماز کب ہے$|^اگلی نماز کا وقت$", t):
        return "next prayer"
    m = re.match(r"^(%s)(?: کی نماز)?(?: کا وقت| کب ہے| کب ہوتی ہے| کا ٹائم)(?: کیا ہے| بتاؤ)?$" % "|".join(_PRAYER_UR), t)
    if m:
        return "%s time" % _PRAYER_UR[m.group(1)]
    if re.match(r"^نماز سے پہلے (?:یاد دلاؤ|یاد دلا دو|ریمائنڈ کرو)$", t):
        return "remind me before the next prayer"
    # S2 focus
    if re.match(r"^(?:فوکس|پومودورو)(?: موڈ| ٹائمر)? (?:شروع کرو|سٹارٹ کرو|چلاؤ|لگاؤ|آن کرو)$", t):
        return "start focus mode"
    if re.match(r"^(?:فوکس|پومودورو)(?: موڈ| ٹائمر)? (?:بند کرو|بند کر دو|ختم کرو)$", t):
        return "stop focus mode"
    if re.match(r"^(?:فوکس|پومودورو)(?: موڈ)? (?:کتنا وقت بچا ہے|اسٹیٹس)$", t):
        return "focus status"
    m = re.match(r"^(\d+) منٹ (?:کا )?(?:فوکس|پومودورو)(?: موڈ)?(?: شروع کرو| لگاؤ)?$", t)
    if m:
        return "start focus mode for %s minutes" % m.group(1)
    # S3 translate: "<text> کا انگریزی میں ترجمہ کرو"
    m = re.match(r"^(.+?) (?:کا|کو|کی) (%s) (?:میں )?(?:ترجمہ|ترجمہ کرو|ترجمہ بتاؤ)(?: کرو| کریں| بتاؤ)?$" % "|".join(sorted(_LANG_UR, key=len, reverse=True)), t)
    if m:
        return "translate %s to %s" % (m.group(1), _LANG_UR[m.group(2)])
    m = re.match(r"^(%s) میں (?:ترجمہ کرو|بتاؤ|بولو) (.+)$" % "|".join(sorted(_LANG_UR, key=len, reverse=True)), t)
    if m:
        return "translate %s to %s" % (m.group(2), _LANG_UR[m.group(1)])
    # S4 currency: "100 ڈالر کتنے روپے ہوئے"
    m = re.match(r"^(\d+(?:\.\d+)?) (%s) (?:کے )?(?:کتنے|کتنی) (%s)(?: ہوئے| ہوتے ہیں| بنتے ہیں| ہوتی ہیں)?$" % ("|".join(_CUR_UR), "|".join(_CUR_UR)), t)
    if m:
        return "%s %s in %s" % (m.group(1), _CUR_UR[m.group(2)], _CUR_UR[m.group(3)])
    m = re.match(r"^(ڈالر|یورو|پاؤنڈ|ریال|درہم) (?:کا )?(?:ریٹ|بھاؤ)(?: کیا ہے| بتاؤ)?$", _clean(t))
    if m:
        return "%s rate" % {"ڈالر": "dollar", "یورو": "euro", "پاؤنڈ": "pound", "ریال": "riyal", "درہم": "dirham"}[m.group(1)]
    # S5 to-do
    m = re.match(r"^(?:ٹو ڈو|ٹوڈو)(?: لسٹ)? میں (.+?) (?:شامل کرو|لکھو|ڈالو|شامل کریں)$", t)
    if m:
        return "add task %s" % m.group(1)
    m = re.match(r"^(?:کام|ٹاسک) (?:شامل کرو|لکھو|ایڈ کرو) (.+)$", t)
    if m:
        return "add task %s" % m.group(1)
    if re.match(r"^(?:میری |میرے )?(?:ٹو ڈو|ٹوڈو)(?: لسٹ)?(?: دکھاؤ| بتاؤ| سناؤ)?$|^(?:آج کے|میرے) کام(?: بتاؤ| دکھاؤ| سناؤ)?$", t):
        return "show my to do list"
    m = re.match(r"^(?:ٹاسک|کام) (\d+) (?:مکمل|ہو گیا|ختم)(?: کرو)?$", t)
    if m:
        return "mark task %s done" % m.group(1)
    m = re.match(r"^(?:ٹاسک|کام) (\d+) (?:ہٹا دو|ڈیلیٹ کرو)$", t)
    if m:
        return "remove task %s" % m.group(1)
    # S6 clipboard
    if re.match(r"^کلپ بورڈ (?:پڑھو|سناؤ|دکھاؤ)$|^میں نے کیا کاپی کیا(?: تھا)?$", t):
        return "read the clipboard"
    if re.match(r"^کلپ بورڈ کا (?:خلاصہ|سمری)(?: دو| بتاؤ| سناؤ)?$", t):
        return "summarize the clipboard"
    if re.match(r"^کلپ بورڈ (?:نوٹ میں|نوٹس میں) (?:محفوظ|سیو) کرو$", t):
        return "save clipboard to notes"
    # S7 page summary
    if re.match(r"^(?:اس|یہ) (?:صفحے|پیج|ویب سائٹ) کا (?:خلاصہ|سمری)(?: دو| بتاؤ| کرو)?$", t):
        return "summarize this page"
    if re.match(r"^(?:اس )?لنک کا (?:خلاصہ|سمری)(?: دو| بتاؤ)?$", t):
        return "summarize the link"
    # S8 journal
    if re.match(r"^(?:جرنل|ڈائری) (?:لکھو|شروع کرو|لکھنی ہے)$|^(?:آج کا|دن کا) (?:خلاصہ|ریکیپ) (?:لکھو|شروع کرو)$", t):
        return "journal"
    if re.match(r"^(?:جرنل|ڈائری) (?:پڑھو|دکھاؤ|سناؤ)$", t):
        return "read my journal"
    return None

def _feature_command(t: str) -> str | None:
    """Urdu phrases for the new voice features -> the English commands features.py understands."""
    pb = _part_b_command(t)
    if pb:
        return pb
    m = re.match(r"^(\d+(?:\.\d+)?) (%s) (\d+(?:\.\d+)?)(?: (?:کتنے ہوئے|کتنا ہوا|کتنے ہوتے ہیں|کتنا ہوتا ہے|کتنے ہیں))?$" % "|".join(_OPS_UR), t)
    if m:
        return "%s %s %s" % (m.group(1), _OPS_UR[m.group(2)], m.group(3))
    if re.search(r"(?<!\S)بریفنگ(?!\S)", t) and not re.search(r"خبر|نیوز|خلاصہ", t):
        if re.search(r"دوبارہ|پھر سے|ایک بار اور", t):
            return "repeat the last briefing"
        return "daily briefing"
    if re.match(r"^(?:آج کا حال|آج کی خبریں اور موسم|دن کا حال)(?: سناؤ| بتاؤ| سنا دو)?$", t):
        return "daily briefing"
    if re.search(r"(?:سپیڈ|اسپیڈ|رفتار)", t) and re.search(r"(?:انٹرنیٹ|نیٹ|وائی فائی)|ٹیسٹ", t) and re.search(r"چیک|ٹیسٹ|بتاؤ|بتاو|ناپو|دیکھو", t):
        return "speed check"
    m = re.match(r"^(?:نوٹ لکھو|نوٹ کرو|نوٹ لکھیں|نوٹ کریں) (.+)$", t)
    if m:
        return "write a note %s" % m.group(1)
    if re.match(r"^(?:میری )?(?:تمام |سب )?رپورٹس (?:دکھاؤ|دکھائیں|دکھا دو|بتاؤ|کھولو)$", t):
        return "show reports"
    if re.match(r"^(?:وہ |آخری |پچھلی )*(?:رپورٹ|نوٹ|ریسرچ) (?:کھولو|کھولیں|دکھاؤ|دکھا دو)$", t):
        return "open the report" if "نوٹ" not in t else "open the notes"
    if re.match(r"^(?:وہ |آخری |پچھلی )*(?:رپورٹ) (?:سناؤ|پڑھو|پڑھ کر سناؤ)$", t):
        return "read the report"
    if re.search(r"(?<!\S)سمارٹ موڈ(?!\S)", t):
        return "smart mode"
    if re.search(r"(?<!\S)لوکل موڈ(?!\S)", t):
        return "local mode"
    if re.search(r"(?:کون سا|کونسا|کون سی) موڈ", t):
        return "which mode"
    if re.match(r"^(?:بریفنگ |رپورٹ |خبریں )?(?:دوبارہ|پھر سے|ایک بار اور) (?:بولو|سناؤ|سنا دو|کہو|بتاؤ|سنائیں)$", t) or t in {"کیا کہا"}:
        return "repeat that"
    if re.search(r"(?<!\S)رپورٹ(?!\S)", t) and re.search(r"دوبارہ|پھر سے", t):
        return "repeat the last report"
    m = re.match(r"^(?:ورڈ(?: فائل)?|ڈاک فائل|ورڈ ڈاکیومنٹ) (?:بناؤ|بنا دو|بنا دیں|چاہیے)$|^(?:رپورٹ کی |اس کی |اسکی )(?:ورڈ(?: فائل)?) (?:بناؤ|بنا دو)$", t)
    if m:
        return "make a word file"
    if re.match(r"^(?:رپورٹ کی |اس کی |اسکی )?پی ڈی ایف(?: فائل)? (?:بناؤ|بنا دو|بنا دیں|چاہیے)$", t):
        return "make a pdf"
    m = re.match(r"^(%s) (.+)$" % "|".join(sorted(_AGENTS_UR, key=len, reverse=True)), t)
    if m:
        name, rest = _AGENTS_UR[m.group(1)], _AG_VERBS.sub("", m.group(2)).strip()
        if name == "scout":
            return "scout research %s" % rest if rest else "scout"
        if name == "social":
            return "social captions for %s" % rest if rest else "social"
        if name == "seo":
            return "seo keywords for %s" % rest if rest else "seo"
        if name == "muse":
            return "muse plan %s" % rest if rest else "muse"
        return "%s %s" % (name, rest)
    m = re.match(r"^(.+?) (?:پر|کے بارے میں) (?:ریسرچ|تحقیق) (?:کرو|کریں|کر دو)$", t)
    if m:
        return "research %s" % m.group(1)
    return None

# ---------------------------------------------------------------------------- Urdu sentence -> English command
def to_command(text: str, pending: bool = False, llm: bool = True):
    """The English command for an Urdu sentence, or None when no rule knows it (the AI then answers in Urdu)."""
    t = _clean(strip_wake(text))
    if not t:
        return None
    lang_word = re.search(r"(?<!\S)(?:زبان|بات|بولو|بولیں|بول|موڈ|سوئچ|تبدیل|جواب)(?!\S)", t)
    if re.search(r"(?<!\S)اردو(?!\S)", t) and (lang_word or len(t.split()) <= 2):
        return "switch to urdu"
    if re.search(r"(?<!\S)(?:انگریزی|انگلش|انگلیش)(?!\S)", t) and (lang_word or len(t.split()) <= 2):
        return "switch to english"
    if pending:
        if t in YES:
            return "yes"
        if t in NO:
            return "no"
    if t in _STOP_UR:
        return "stop"
    if t in _EXIT_UR:
        return "goodbye"
    f = _feature_command(t)
    if f:
        return f
    n = _news_command(t)
    if n:
        return n

    # ---- WhatsApp ----------------------------------------------------------------------
    wa = r"(?:واٹس ایپ|واٹس اپ|وٹس ایپ|واٹسایپ)"
    m = re.match(r"^(?:%s (?:پر|میں|سے) )?(.+?) (?:کو|کے نام) (?:%s (?:پر|میں) )?%s (?:کہ|کے|کہ کہ)? ?(.+)$" % (wa, wa, V_MSG), t)
    if m and (len(m.group(1).split()) <= 4):
        who = obj(m.group(1))
        if who and not re.search(r"(?<!\S)(?:ای میل|ایمیل|میل)(?!\S)", t):
            msg = re.sub(r"^(?:کہ|کے)\s+", "", m.group(2)).strip()
            return "send a message to %s saying %s" % (who, msg) if msg else "open chat of %s" % who
    m = re.match(r"^(?:%s (?:پر|میں) )?(.+?) (?:کا|کی|کے) (?:چیٹ|گفتگو|میسجز|میسج|پیغامات) %s$" % (wa, V_OPEN.replace("کھول)", "کھول|دکھاؤ|دکھا)")), t)
    if m:
        return "open chat of %s on whatsapp" % obj(m.group(1))
    m = re.match(r"^(?:%s (?:پر|میں) )?(.+?) (?:سے|کے ساتھ) (?:چیٹ|بات) (?:کھولو|کھولیں|کرو|کریں|شروع کرو)$" % wa, t)
    if m:
        return "open chat with %s on whatsapp" % obj(m.group(1))
    m = re.match(r"^(?:%s )?(.+?) کو (?:میسج|پیغام|مسیج) (?:کرو|کریں)$" % wa, t)
    if m:
        return "message %s" % obj(m.group(1))
    if re.match(r"^(?:میسج |پیغام |اسے |یہ |اب )?%s$" % V_SEND, t) or t in {"سینڈ", "بھیج دو", "میسج بھیج دو"}:
        return "send"
    if re.match(r"^(?:میسج|پیغام|ڈرافٹ|لکھا ہوا) (?:مٹا دو|مٹاؤ|صاف کرو|ڈیلیٹ کرو|ہٹا دو|کینسل کرو)$", t):
        return "clear the message"
    if re.match(r"^(?:چیٹ|گفتگو) (?:بند کرو|بند کریں|بند)$", t):
        return "close chat"
    if re.match(r"^(?:میسج|پیغام|جو لکھا) (?:پڑھو|سناؤ|پڑھ کر سناؤ|پڑھیں)$", t):
        return "read the message"

    # ---- media / YouTube -----------------------------------------------------------------
    m = re.match(r"^(?:یوٹیوب|یو ٹیوب) (?:پر|میں|سے) (.+?) %s$" % V_PLAY, t) or \
        re.match(r"^(.+?) (?:یوٹیوب|یو ٹیوب) (?:پر|میں|سے) %s$" % V_PLAY, t)
    if m:
        q = obj(m.group(1))
        if q:
            return "play %s on youtube" % q
    m = re.match(r"^(?:یوٹیوب|یو ٹیوب) (?:پر|میں|سے) (.+?) %s$" % V_SEARCH, t) or \
        re.match(r"^(.+?) (?:یوٹیوب|یو ٹیوب) (?:پر|میں|سے) %s$" % V_SEARCH, t)
    if m:
        return "search youtube for %s" % obj(m.group(1))
    if re.match(r"^(?:گانا|ویڈیو|میوزک|موسیقی|گانے|ویڈیوز) (?:روکو|روک دو|روکیں|پاز کرو|پاز|وقفہ کرو|رکو)$|^(?:پاز|روکو|روک دو|پاز کرو|وقفہ|وقفہ کرو)$", t):
        return "pause"
    if re.match(r"^(?:دوبارہ چلاؤ|دوبارہ چلاو|جاری رکھو|جاری رکھیں|پھر سے چلاؤ|پھر چلاؤ|پلے|چلاؤ|چلاو|رزیوم کرو|ریزیوم کرو)$", t):
        return "resume"
    if re.match(r"^(?:اگلا|اگلی|اگلے|نیکسٹ)(?: گانا| گانے| ویڈیو| ٹریک| والا| والی| گیت)?(?: لگاؤ| چلاؤ| لگا دو| چلا دو)?$", t):
        return "next video" if "ویڈیو" in t else "next song"
    if re.match(r"^(?:پچھلا|پچھلی|پچھلے|پہلے والا|پہلے والی|پریویس)(?: گانا| گانے| ویڈیو| ٹریک| والا| والی| گیت)?(?: لگاؤ| چلاؤ| لگا دو| چلا دو)?$", t):
        return "previous video" if "ویڈیو" in t else "previous song"
    m = re.match(r"^(.+?) (سیکنڈ|منٹ) (آگے|پیچھے)(?: کرو| کریں| کر دو| جاؤ)?$", t)
    if m and num(m.group(1)):
        secs = num(m.group(1)) * (60 if m.group(2) == "منٹ" else 1)
        return ("skip %d seconds" if m.group(3) == "آگے" else "rewind %d seconds") % secs
    if re.match(r"^(?:فل اسکرین|فل سکرین|پوری اسکرین)(?: کرو| کریں)?$", t):
        return "fullscreen"
    if re.match(r"^(?:ویڈیو|گانا) (?:تیز|فاسٹ) کرو$|^(?:ویڈیو|گانا|رفتار) (?:بڑھاؤ|بڑھاو|تیز)$", t):
        return "speed up"
    if re.match(r"^(?:ویڈیو|گانا) (?:سلو|آہستہ|دھیمی) کرو$|^رفتار (?:کم کرو|کم|آہستہ)$", t):
        return "slow down"
    if re.match(r"^(?:ویڈیو|گانا) (?:دوبارہ شروع کرو|شروع سے چلاؤ|شروع سے)$", t):
        return "restart the video"
    if re.match(r"^(?:ابھی )?(?:کیا|کون سا) (?:چل رہا ہے|گانا چل رہا ہے|گانا ہے|ویڈیو ہے|ویڈیو چل رہی ہے)$|^یہ (?:کون سا|کیا) (?:گانا|ویڈیو) ہے$", t):
        return "what is playing"

    # ---- volume / brightness ------------------------------------------------------------
    m = re.match(r"^(?:آواز|والیوم|والیم|ساؤنڈ) (.+?) (?:پر )?(?:کرو|کریں|کر دو|سیٹ کرو|رکھو)$", t)
    if m and num(m.group(1)) is not None:
        return "set volume to %d" % num(m.group(1))
    if re.match(r"^(?:آواز|والیوم|والیم|ساؤنڈ)(?: کو)? (?:بڑھاؤ|بڑھاو|بڑھائیں|تیز کرو|تیز|اونچی کرو|زیادہ کرو|زیادہ|اوپر)$", t):
        return "volume up"
    if re.match(r"^(?:آواز|والیوم|والیم|ساؤنڈ)(?: کو)? (?:کم کرو|کم|دھیمی کرو|دھیمی|آہستہ کرو|نیچے|کم کر دو)$", t):
        return "volume down"
    if re.match(r"^(?:آواز|ساؤنڈ|والیوم) (?:بند کرو|بند|میوٹ کرو|میوٹ)$|^میوٹ(?: کرو| کریں)?$", t):
        return "mute"
    if re.match(r"^(?:آواز|ساؤنڈ) (?:چالو کرو|کھولو|ان میوٹ کرو)$|^ان ?میوٹ(?: کرو| کریں)?$", t):
        return "unmute"
    m = re.match(r"^(?:برائٹنس|روشنی|اسکرین کی روشنی) (.+?) (?:پر )?(?:کرو|کریں|سیٹ کرو)$", t)
    if m and num(m.group(1)) is not None:
        return "set brightness to %d" % num(m.group(1))
    if re.match(r"^(?:برائٹنس|روشنی)(?: کو)? (?:بڑھاؤ|بڑھاو|زیادہ کرو|زیادہ|تیز کرو)$", t):
        return "increase brightness"
    if re.match(r"^(?:برائٹنس|روشنی)(?: کو)? (?:کم کرو|کم|دھیمی کرو)$", t):
        return "decrease brightness"

    m = re.match(r"^(.+?) %s$" % V_SEARCH, t)
    if m:
        q = obj(m.group(1))
        m2 = re.match(r"^(.+?) (?:پر|میں) (.+)$", m.group(1))
        if m2 and ent(m2.group(1)) in ("google", "youtube", "amazon", "daraz", "olx", "facebook", "twitter", "instagram"):
            return "search %s on %s" % (obj(m2.group(2)), ent(m2.group(1)))
        return "search for %s" % q if q else None

    # ---- information --------------------------------------------------------------------
    if re.search(r"(?:وقت|ٹائم) (?:کیا|کتنا)|کتنے بجے|کیا بجا|کیا بج|کیا ٹائم|ٹائم کیا", t):
        return "what time is it"
    if re.search(r"(?:تاریخ|ڈیٹ)|(?:آج|کل) کون سا دن|کون سا دن|آج کیا دن", t):
        return "what is the date today" if re.search(r"تاریخ|ڈیٹ", t) else "what day is it"
    if re.search(r"موسم", t):
        city = re.sub(r"(?<!\S)(?:کا|کی|کے|میں|موسم|کیسا|ہے|کیا|حال|بتاؤ|بتاو|بتائیں|آج|آج کا|ابھی|اس وقت|کیسی|ہوا)(?!\S)", " ", t)
        city = obj(city)
        return "weather in %s" % city if city else "weather"
    if re.search(r"بیٹری", t) and re.search(r"کتنی|کتنا|باقی|فیصد|حالت|چیک", t):
        return "battery"
    if re.search(r"سسٹم (?:کی )?(?:حالت|اسٹیٹس|سٹیٹس|رپورٹ)|کمپیوٹر (?:کی )?(?:حالت|رپورٹ)", t):
        return "system status"
    if re.search(r"اسکرین ?شاٹ|سکرین ?شاٹ", t):
        return "take a screenshot"
    m = re.match(r"^(.+?) (منٹ|سیکنڈ|گھنٹے|گھنٹہ|گھنٹی) (?:کا|کے لیے|کے) (?:ٹائمر|الارم)(?: لگاؤ| لگا دو| سیٹ کرو| لگائیں| لگاو)?$", t)
    if m and num(m.group(1)):
        unit = {"منٹ": "minutes", "سیکنڈ": "seconds"}.get(m.group(2), "hours")
        return "set a timer for %d %s" % (num(m.group(1)), unit)
    m = re.match(r"^(.+?) (?:نوٹ کرو|نوٹ کر لو|نوٹ کریں|نوٹ لکھو|نوٹ کر دو|یاد رکھو|یاد رکھنا)$", t)
    if m:
        return "take a note %s" % m.group(1)
    if re.search(r"(?<!\S)(?:لطیفہ|جوک)(?!\S)", t):
        return "tell me a joke"

    # ---- general verbs ------------------------------------------------------------------
    m = re.match(r"^(.+?) %s$" % V_TYPE, t) or re.match(r"^%s (.+)$" % V_TYPE.replace(DO, ""), t)
    if m:
        return "type %s" % m.group(1).strip()
    m = re.match(r"^(.+?) %s$" % V_OPEN, t)
    if m:
        o = obj(m.group(1))
        return "open %s" % o if o else None
    m = re.match(r"^(.+?) %s$" % V_CLOSE, t)
    if m:
        o = obj(m.group(1))
        return "close %s" % o if o else None
    m = re.match(r"^(.+?) %s$" % V_PLAY, t)
    if m:
        o = obj(m.group(1))
        if not o:
            return None
        if ent(m.group(1)) in APPS.values() or o in APPS.values():      # "کروم چلاؤ" means open Chrome
            return "open %s" % o
        return "play %s" % o

    # ---- small talk: only mapped when there is no AI to answer natively in Urdu ------------
    if not llm:
        if re.search(r"سلام|ہیلو|ہائے", t) and len(t.split()) <= 4:
            return "hello"
        if re.search(r"کیسے ہو|کیسے ہیں|کیا حال|حال چال", t):
            return "how are you"
        if re.search(r"کون ہو|کون ہیں|نام کیا|اپنا تعارف", t):
            return "who are you"
        if re.search(r"شکریہ|مہربانی", t) and len(t.split()) <= 4:
            return "thank you"
    return None


_COMMAND_STEMS = re.compile(r"(?:کھول|بند|چلا|لگا|بجا|سرچ|تلاش|ڈھونڈ|ٹائپ|لکھ|بھیج|کرو|کریں|دکھا|سنا|بڑھا|کم کر|میوٹ|اسکرین)")


def looks_like_command(text: str) -> bool:
    return bool(_COMMAND_STEMS.search(_clean(text)))


# ---------------------------------------------------------------------------- English reply -> Urdu
_WEEKDAYS = {"Monday": "پیر", "Tuesday": "منگل", "Wednesday": "بدھ", "Thursday": "جمعرات", "Friday": "جمعہ", "Saturday": "ہفتہ",
             "Sunday": "اتوار"}
_MONTHS = {"January": "جنوری", "February": "فروری", "March": "مارچ", "April": "اپریل", "May": "مئی", "June": "جون", "July": "جولائی",
           "August": "اگست", "September": "ستمبر", "October": "اکتوبر", "November": "نومبر", "December": "دسمبر"}


def _period(h12: int, ampm: str) -> str:
    h24 = (h12 % 12) + (12 if ampm.upper() == "PM" else 0)
    if 4 <= h24 < 12:
        return "صبح"
    if 12 <= h24 < 16:
        return "دوپہر"
    if 16 <= h24 < 20:
        return "شام"
    return "رات"


def _t_time(m):
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3)
    return "اس وقت %s کے %d:%s بجے ہیں۔" % (_period(h, ap), h, mi)


def _t_date(m):
    return "آج %s، %s %s %s ہے۔" % (_WEEKDAYS.get(m.group(1), m.group(1)), m.group(2), _MONTHS.get(m.group(3), m.group(3)), m.group(4))


_TEMPLATES = [
    (r"^Opening (?:your )?(.+?)(?: folder)?\.$", lambda m: "%s کھول رہا ہوں۔" % m.group(1)),
    (r"^Closing (.+?)\.$", lambda m: "%s بند کر رہا ہوں۔" % m.group(1)),
    (r"^(?:Closed|I closed) (.+?)\.$", lambda m: "%s بند کر دیا۔" % m.group(1)),
    (r"^Playing (.+?)\.$", lambda m: "%s چلا رہا ہوں۔" % m.group(1)),
    (r"^Searching (.+?) for (.+?)\.$", lambda m: "%s پر %s تلاش کر رہا ہوں۔" % (m.group(1), m.group(2))),
    (r"^Showing Google results for (.+?)\.$", lambda m: "%s کے گوگل نتائج دکھا رہا ہوں۔" % m.group(1)),
    (r"^Done\.$", lambda m: "ہو گیا۔"),
    (r"^Sent\.$", lambda m: "بھیج دیا۔"),
    (r"^It is (\d{1,2}):(\d{2}) (AM|PM)\.$", _t_time),
    (r"^Today is (\w+), (\d{1,2}) (\w+) (\d{4})\.$", _t_date),
    (r"^Volume set to (\d+) percent\.$", lambda m: "آواز %s فیصد پر سیٹ کر دی۔" % m.group(1)),
    (r"^Volume up\.$", lambda m: "آواز بڑھا دی۔"),
    (r"^Volume down\.$", lambda m: "آواز کم کر دی۔"),
    (r"^Brightness set to (\d+) percent\.$", lambda m: "روشنی %s فیصد پر سیٹ کر دی۔" % m.group(1)),
    (r"^Brightness is at (\d+) percent\.$", lambda m: "روشنی %s فیصد ہے۔" % m.group(1)),
    (r"^Screenshot saved in your Pictures folder\.$", lambda m: "اسکرین شاٹ آپ کے پکچرز فولڈر میں محفوظ کر دیا۔"),
    (r"^Goodbye\. Shutting down\.$", lambda m: "خدا حافظ۔ میں بند ہو رہا ہوں۔"),
    (r"^You are welcome\.$", lambda m: "کوئی بات نہیں۔"),
    (r"^Hello! How can I help you\?$|^At your service\.$|^Hello there\. What shall we do\?$",
     lambda m: "السلام علیکم! میں آپ کی کیا مدد کر سکتا ہوں؟"),
    (r"^All systems are running perfectly\..*$|^Operating at peak efficiency.*$", lambda m: "سب کچھ بالکل ٹھیک چل رہا ہے۔ پوچھنے کا شکریہ۔"),
    (r"^I am Jarvis, a voice controlled assistant\..*$", lambda m: "میں جارویس ہوں، آپ کا آواز سے چلنے والا اسسٹنٹ۔ میں ایپس کھول سکتا ہوں اور آپ کے لیے ٹائپ کر سکتا ہوں۔"),
    (r"^Typed\. Say send when you want it sent, or type more\.$", lambda m: "ٹائپ ہو گیا۔ بھیجنے کے لیے بھیجو کہیں، یا مزید ٹائپ کریں۔"),
    (r"^Cleared the message\.$", lambda m: "میسج صاف کر دیا۔"),
    (r"^Closed the chat\.$", lambda m: "چیٹ بند کر دی۔"),
    (r"^Opened the chat of (.+?)\. Say type.*$", lambda m: "%s کی چیٹ کھول دی۔ اب ٹائپ کہہ کر میسج بولیں۔ اگر غلط شخص کھلا ہو تو پورا نام بولیں۔" % m.group(1)),
    (r"^WhatsApp is open\..*$", lambda m: "واٹس ایپ کھل گیا ہے۔ نام کے ساتھ چیٹ کھولو کہیں۔"),
    (r"^Send this to (.+?): (.+)\. Say yes or no\.$", lambda m: "یہ %s کو بھیجوں: %s۔ ہاں یا نہیں کہیں۔" % (m.group(1), m.group(2))),
    (r"^Sorry, I understood that as a command, but I don't know how to do it yet\.$|^I'm afraid I can't do that one yet\.$",
     lambda m: "معذرت، میں یہ کام ابھی نہیں کر سکتا۔"),
    (r"^I can't reach the news feed right now\.$", lambda m: "ابھی خبروں کی فیڈ نہیں مل رہی۔"),
    (r"^Switched to English\.$", lambda m: "ٹھیک ہے، اب میں انگریزی میں بات کروں گا۔"),
]
_TEMPLATES = [(re.compile(rx, re.S), fn) for rx, fn in _TEMPLATES]
_cache: dict = {}


def template(text: str):
    for rx, fn in _TEMPLATES:
        m = rx.match(text.strip())
        if m:
            return fn(m)
    return None


def localize(text: str, translate=None) -> str:
    """English reply -> Urdu when Urdu mode is on. `translate(text)` is the AI fallback (may return None)."""
    if not text or not is_urdu() or has_urdu(text):
        return text
    if not re.search(r"[A-Za-z]{2}", text):
        return text
    hit = template(text)
    if hit:
        return hit
    if text in _cache:
        return _cache[text]
    if translate:
        try:
            out = translate(text)
        except Exception:
            out = None
        if out and has_urdu(out):
            if len(_cache) > 300:
                _cache.clear()
            _cache[text] = out
            return out
    return text                                     # no AI available: keep the English (it is still spoken, in the English voice)


# ---------------------------------------------------------------------------- voice
def voice_for(text: str, default: str) -> tuple[str, str | None]:
    """(voice, rate) for a piece of speech: the Urdu neural voice for Urdu text."""
    if urdu_ratio(text) >= 0.3:
        return (os.environ.get("JARVIS_URDU_VOICE") or "ur-PK-AsadNeural").strip(), os.environ.get("JARVIS_URDU_RATE", "+0%").strip() or "+0%"
    return default, None


BRAIN_NOTE = (" IMPORTANT: the user has chosen URDU. Reply ONLY in natural, conversational Urdu written in Urdu (Arabic) script - "
              "never Roman Urdu and never English, except unavoidable names. Use simple spoken Urdu, one to three short sentences, "
              "end sentences with the Urdu full stop (۔) or question mark (؟). The mood tag at the start must stay in English.")

TRANSLATE_SYSTEM = ("You translate the assistant's short spoken reply into natural conversational Urdu in Urdu script (not Roman Urdu). "
                    "Keep names, numbers, app names and times as they are. Output ONLY the Urdu translation, no quotes, no notes.")
