"""New voice features (additive). Registered in FRONT of the older skills, but every skill here returns None unless its
own, specific pattern matches, so the old commands keep working exactly as before.

    briefing / briefing sunao / aaj ka haal      weather + internet speed + headlines
    speed check / speed check karo               ping + download speed
    write a note ... / note likho ...            note kept in notes.txt AND in today's Word file
    show reports / open the scout report         read reports inside the app (panel + voice)
    volume barhao / awaz 50 kar do / mute karo   Roman-Urdu volume (uses the existing volume skills)
    2500 guna 18 kitne hue                       Roman-Urdu arithmetic (uses the existing calculator)
    smart mode / local mode / which mode         AI on or off
    dobara bolo / repeat the last briefing       repeat things
    scout / herald / voyager / social / seo / muse   six background agents
    make a word file / pdf banao                 turn the last report into .docx or .pdf
    help                                         the old help plus the new features

Patterns see the normalised, lower-case text without punctuation (skills.normalize + strip_filler).
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import threading
import time

from . import agents, briefing, docs, modes, urdu

S = importlib.import_module(".skills", __package__)
log = logging.getLogger("jarvis.features")

_MINE: list = []


def fskill(pattern: str, chat: bool = False):
    rx = re.compile(pattern)

    def deco(fn):
        _MINE.append((rx, fn, chat))
        return fn
    return deco


def _route(ctx, cmd: str):
    """Run an existing English command through the normal router."""
    return S._route_one(ctx, cmd, 1)


def _bg(ctx, ack: str, work, fail: str = "Sorry, that did not work. The details are in the log.") -> str:
    """Run work() -> spoken sentence on a worker thread; it is spoken only if nobody interrupted meanwhile."""
    epoch = getattr(ctx, "epoch", 0)

    def job():
        try:
            out = work()
        except Exception:
            log.exception("background job failed")
            out = fail
        if out:
            agents.speak_if_current(ctx, epoch, out)
    threading.Thread(target=job, daemon=True, name="feature-job").start()
    return ack


# ============================================================================ briefing
@fskill(r"^(?:(?:give me|tell me|read me|read|start|play|run|show|let me hear|whats|what is)(?: me)?(?: my| the| todays)? )?"
        r"(?:daily |morning |todays? |full )?briefing(?: sunao| suna do| sunao please| dikhao| chalao| do| now)?$|"
        r"^(?:aaj ka|aaj ki|din ka|subah ka) (?:haal|briefing|khabrein)(?: sunao| batao| suna do)?$|"
        r"^briefing (?:sunao|suna do|karo|kar do|chalao|dikhao|batao)$")
def _briefing(ctx, m, t):
    briefing.run(ctx)
    return "One moment, I am putting together your briefing: weather, internet speed and the headlines."


# ============================================================================ speed
@fskill(r"^(?:internet |net |wifi |wi fi )?speed (?:check|test)(?: karo| kar do| chalao| lagao| kar lo| do)?$|"
        r"^(?:check|test|run|do|measure)(?: my| the)?(?: internet| net| wifi)? speed(?: test| check)?$|"
        r"^how fast is (?:my |the )?(?:internet|wifi|net|connection)$|"
        r"^(?:internet|net|wifi) (?:ki )?(?:speed|raftar) (?:check|batao|dikhao|maapo|test)(?: karo| kar do)?$")
def _speed(ctx, m, t):
    def work():
        s = briefing.speed_test()
        text = briefing.speed_sentence(s, urdu.is_urdu())
        agents.record("speed", "Speed check", text, text)
        ctx.hud_post("log", "sys", "speed  " + text)
        return text
    return _bg(ctx, "Testing your connection, one moment.", work)


# ============================================================================ notes (extends the old note skill)
def _mirror_note(ctx, text: str) -> None:
    """NEW: the same note in today's Word file (worker thread)."""
    def mirror():
        try:
            path = os.path.join(docs.reports_dir(), "Notes-%s.docx" % time.strftime("%Y-%m-%d"))
            docs.append_note_docx(path, text)
            ctx.hud_post("log", "sys", "note saved  " + os.path.basename(path))
        except Exception:
            log.exception("note docx failed")
    threading.Thread(target=mirror, daemon=True, name="note-docx").start()



@fskill(r"^(?:note likho|note kar lo|note karo|note kardo|note kar do|likh lo|write me a note|write a note|save a note|new note|add note|"
        r"word note|take a note|make a note|note down|note that|note|write down|remember that|add a note)(?: that| to| ki| ke| ko)?\s+(.+)$")
def _note(ctx, m, t):
    text = (m.group(1) or "").strip()
    if not text or re.fullmatch(r"(?:kholo|khol do|dikhao|dikha do|sunao|suna do|padho|parho|open karo)", text):
        return None                                          # "note kholo" means open the notes file, not save the word "kholo"
    ctx.mem.add_note(text)                                   # the old behaviour, unchanged

    _mirror_note(ctx, text)
    ctx.hud_post("log", "sys", "note  " + text)
    return "Noted."


# ============================================================================ reports (in-app)
def _listing() -> str:
    rows = docs.list_reports()
    return "\n".join("%d. %s   (%s)" % (i, f, time.strftime("%d %b, %I:%M %p", time.localtime(ts))) for i, (f, ts) in enumerate(rows[:20], 1))


@fskill(r"^(?:(?:show|list|display|open|read out|tell me|give me)(?: me)?(?: all)?(?: of)?(?: my| the)? (?:reports|reports? list|reports? folder)|"
        r"(?:meri |meri saari |saari |sab |all )?reports? (?:dikhao|dikha do|dikhain|batao|bata do|list karo|kholo)|"
        r"what reports do i have|how many reports(?: do i have)?|my reports|reports list)$")
def _reports_list(ctx, m, t):
    rows = docs.list_reports()
    if not rows:
        return "Your reports folder is empty. Ask Scout to research something, or say write a note."
    agents.show(ctx, "MY REPORTS", _listing())
    return "You have %d report%s. The newest is %s. The full list is on screen; say open and a name to read one." % (
        len(rows), "" if len(rows) == 1 else "s", rows[0][0])


@fskill(r"^(?P<verb>open|show|read|display|view)(?: me)?(?: the| my| that| this| last| latest| newest| recent)* (?:(?P<kw>.+?) )?"
        r"(?P<what>report|research|notes?|word file|word document)$|"
        r"^(?:(?:wo|woh|ye|yeh|aakhri|akhri|pichli|last)(?: wali)? )?(?:(?P<kw2>.+?) )?(?P<what2>report|notes?|research) "
        r"(?P<verb2>kholo|khol do|dikhao|dikha do|open karo|sunao|suna do|padho|parho)$")
def _report_open(ctx, m, t):
    gd = m.groupdict()
    what = gd.get("what") or gd.get("what2") or ""
    kw = (gd.get("kw") or gd.get("kw2") or "").strip()
    verb = gd.get("verb") or gd.get("verb2") or ""
    kw = re.sub(r"^(?:of |on |about |ki |ka |wali |wala )+", "", kw).strip()
    if what.startswith("note") and not kw and verb in ("open", "show", "read", "display", "view"):
        return None                                          # "read my notes" / "show notes" belong to the old notes skill
    key = " ".join(x for x in (kw, "notes" if what.startswith("note") else ("research" if what == "research" and not kw else "")) if x)
    name = docs.find_report(key)
    if not name:
        if what.startswith("note") or not docs.list_reports():
            return None if what.startswith("note") else "You have no reports yet."
        return "I could not find a report matching %s." % (kw or what)
    text = docs.read_report(name)
    if text:
        text = re.sub(r"^Created by J\.A\.R\.V\.I\.S.*$", "", text, flags=re.M).replace("\n\n\n", "\n\n")
    if text is None:
        return "%s is a PDF. It is in your reports folder, but I can only show Word and text files here." % name
    agents.show(ctx, "REPORT - " + name, text)
    agents.record("opened", name, text, agents.short_spoken(text))
    if verb in ("read", "sunao", "suna", "padho", "parho"):
        return agents.read_aloud(text, 700) or "That report is empty."
    return "I have opened %s on the screen." % name


# ============================================================================ volume in Roman Urdu
@fskill(r"^(?:volume|awaz|awaaz|sound|aawaz)(?: ko)? (?:barhao|badhao|barha do|badha do|zyada karo|zyada kar do|tez karo|tez kar do|upar karo|up karo)$|"
        r"^(?:awaz|awaaz|aawaz|volume) barh(?:ao|a do)$")
def _vol_up(ctx, m, t):
    return _route(ctx, "volume up")


@fskill(r"^(?:volume|awaz|awaaz|sound|aawaz)(?: ko)? (?:kam karo|kam kar do|ghatao|ghata do|neeche karo|down karo|halki karo|halki kar do)$")
def _vol_down(ctx, m, t):
    return _route(ctx, "volume down")


@fskill(r"^(?:volume|awaz|awaaz|aawaz)(?: ko)? (\d{1,3})(?: percent| fisad| fees?d)?(?: pe| par| per)?(?: kar do| karo| set karo| kar den)$|"
        r"^(?:volume|awaz|awaaz|aawaz) (?:ko )?(\d{1,3}) (?:pe|par|per) (?:kar do|karo|le aao)$")
def _vol_set(ctx, m, t):
    n = int(m.group(1) or m.group(2))
    return _route(ctx, "set volume to %d" % min(n, 100))


@fskill(r"^(?:mute kar do|mute karo|mute kardo|awaz band karo|awaz band kar do|awaaz band karo|awaaz band kar do|volume band karo|"
        r"volume band kar do|sound band karo|khamosh kar do)$")
def _vol_mute(ctx, m, t):
    return _route(ctx, "mute")


@fskill(r"^(?:unmute kar do|unmute karo|awaz wapas karo|awaz on karo|awaz chalu karo|awaaz wapas karo)$")
def _vol_unmute(ctx, m, t):
    return _route(ctx, "unmute")


# ============================================================================ calculator in Roman Urdu
_CALC_WORDS = (("guna", "times"), ("gunaa", "times"), ("zarb", "times"), ("into", "times"), ("jama", "plus"), ("ghata", "minus"),
               ("ghatao", "minus"), ("tafreeq", "minus"), ("taqseem", "divided by"), ("tagseem", "divided by"), ("bata", "divided by"),
               ("baata", "divided by"))
_CALC_TAIL = r"(?: kitne hue| kitna hua| kitne hote hain| kitna hota hai| kitne hain| kitna hai| kya hua| kya hota hai| kitne ho gaye| batao| bata do)?"


@fskill(r"^(?:hisab karo |hisaab karo |calculate |calculator )?(?P<e>[\d\.\s]*\d[\d\.\s]*(?:guna|gunaa|zarb|into|jama|ghata|ghatao|tafreeq|taqseem|tagseem|bata|baata)"
        r"[\d\.\s]*\d[\d\.\s]*(?:(?:guna|gunaa|zarb|into|jama|ghata|ghatao|tafreeq|taqseem|tagseem|bata|baata|plus|minus|times)[\d\.\s]*\d[\d\.\s]*)*?)"
        + _CALC_TAIL + r"$")
def _calc_roman(ctx, m, t):
    expr = m.group("e")
    for a, b in _CALC_WORDS:
        expr = re.sub(r"\b%s\b" % a, " %s " % b, expr)
    val = S.calculate(expr)
    return None if val is None else "That is %s." % val


# ============================================================================ Smart / Local mode
@fskill(r"^(?:(?:switch|go|change|set|turn|put me)(?: it| me| yourself)?(?: (?:to|on|in|into))? ?|enable |activate )?(smart|local) mode(?: on| karo| kar do| lagao| chalao| set karo| on karo| par| pe)?$|"
        r"^(?:switch|go|change|set) (?:to )?(smart|local)$|^(smart|local) mode (?:chalao|lagao|on karo)$")
def _mode_set(ctx, m, t):
    which = m.group(1) or m.group(2) or m.group(3)
    modes.set_mode(which)
    ctx.hud_post("log", "sys", "Mode: " + which.upper())
    if which == "local":
        return "Local mode is on. The AI is switched off and nothing leaves this PC except news, weather and web look-ups you ask for."
    return "Smart mode is on. The AI brain is active again."


@fskill(r"^(?:what|which) mode(?: are you in| is this| is on| is active)?$|^(?:current |kaun sa |konsa )?mode(?: batao| kya hai| kaun sa hai| konsa hai)?$|"
        r"^are you (?:in )?(smart|local)(?: mode)?$")
def _mode_get(ctx, m, t):
    return modes.describe(ctx)


# ============================================================================ repeat (extends the old "repeat that")
_KIND = {"briefing": "briefing", "report": None, "research": "scout", "news": "herald", "speed": "speed", "note": None, "notes": None}


@fskill(r"^(?:repeat|say|read|play|sunao|bolo)(?: me)?(?: the| my| that| it)?(?: last| latest| previous| aakhri| pichli)? "
        r"(briefing|report|research|news|speed)(?: again| once more| dobara| phir se)?$|"
        r"^(?:(?:last|aakhri|akhri|pichli) )?(briefing|report|research|news|speed)(?: ko)? (?:dobara|phir se|ek bar aur|dubara) (?:sunao|suna do|bolo|batao|repeat karo)$|"
        r"^(?:repeat|say|read) (?:the |my )?(?:last |latest )?(briefing|report|research|news|speed) again$|"
        r"^(?:dobara|dubara|phir se|ek baar phir|ek bar phir|ek bar aur|ek baar aur) (?:bolo|sunao|suna do|batao|kaho)$|"
        r"^(?:kya kaha|kya bola|phir se kaho)$")
def _repeat_more(ctx, m, t):
    kind = next((g for g in m.groups() if g), None)
    if kind is None:                                           # "dobara bolo": same as the old "repeat that"
        return ctx.last_reply or "I have not said anything yet."
    key = _KIND.get(kind)
    rec = agents.last(key) if key else agents.last()
    if kind == "report" and rec is None:
        rec = agents.last()
    if not rec:
        return "I have no %s to repeat yet." % kind
    return rec.get("spoken") or agents.short_spoken(rec.get("text", "")) or "That one was empty."


# ============================================================================ the six agents
_ALIASES = {"scout": "scout", "scott": "scout", "skout": "scout", "scoot": "scout", "herald": "herald", "harold": "herald",
            "voyager": "voyager", "voyage": "voyager", "social": "social", "seo": "seo", "s e o": "seo", "muse": "muse", "mews": "muse"}
_SURE = {"scout", "herald", "voyager", "seo", "muse"}                  # names that are safe to react to on their own
_TASK_WORD = re.compile(r"^(?:se |ko |to |please |ab |research|investigate|find|look|dig|search|news|headlines|plan|write|make|create|draft|give|"
                        r"tell|check|keywords?|captions?|hashtags?|flights?|trip|travel|strategy|roadmap|kaho|bolo|batao)\b")
_SOCIAL_OK = re.compile(r"^(?:media|captions?|posts?|hashtags?|content|plan|campaign|ideas?|for|write|make|give|create|se |ke |ko |ki )")
_LEAD = re.compile(r"^(?:(?:se|ko) (?:kaho|bolo|kehna|kehdo|keh do) (?:ki )?|(?:please|can you|could you|ab|zara|zaraa)\s+|(?:research|investigate|find out|find|look into|dig into|"
                   r"search for|search|tell me about|tell me|give me|write me|write|make me|make|create|draft|plan|check|do)\s+|"
                   r"(?:some |a |an |the |deep |detailed |full |complete |new )+|(?:news|headlines|keywords?|captions?|hashtags?|a plan|plan|strategy|content plan|"
                   r"social media|media|posts?|report)\s+(?:on|about|for|of|regarding)\s+|(?:on|about|for|of|regarding|ke liye|ke baare mein|ke bare mein|par|pe|per|ki|ka|ke)\s+)")
_TAIL = re.compile(r"\s+(?:(?:par|pe|per|ke baare mein|ke bare mein|k bare mein|ke liye|ki|ka)\s+)?(?:research|tehqeeq|maloomat|report|plan|captions?|keywords?|news|khabrein)?\s*"
                   r"(?:karo|kar do|kardo|kar den|lao|le aao|nikalo|nikal do|batao|bata do|likho|likh do|banao|bana do|bana den|chahiye|do|please)$")


def _task(rest: str) -> str:
    s = rest.strip()
    for _ in range(6):
        n = _LEAD.sub("", s, count=1).strip()
        if n == s:
            break
        s = n
    for _ in range(3):
        n = _TAIL.sub("", s, count=1).strip()
        if n == s:
            break
        s = n
    return re.sub(r"\s+(?:par|pe|per)$", "", s).strip()


def _run_agent(ctx, name: str, rest: str) -> str:
    task = _task(rest)
    if not task and name != "herald":
        return "What should %s work on? For example: %s." % (name.upper(), {
            "scout": "scout, research electric cars", "voyager": "voyager, flights from Lahore to Dubai",
            "social": "social, captions for my tea shop", "seo": "seo, keywords for organic honey",
            "muse": "muse, plan my exam preparation"}[name])
    return agents.dispatch(ctx, name, task)


@fskill(r"^(?:hey |ok |okay )?(scout|scott|skout|scoot|herald|harold|voyager|voyage|social|seo|s e o|muse|mews)\b(?: agent)?\s*(.*)$")
def _named_agent(ctx, m, t):
    word, rest = m.group(1), m.group(2).strip()
    name = _ALIASES[word]
    if word not in _SURE:                                     # mishearings and the common word "social": need a task-like start
        if word == "social" and not _SOCIAL_OK.match(rest):
            return None
        if word != "social" and not _TASK_WORD.match(rest):
            return None
    if word in ("muse", "mews") and not rest:
        return None
    if word in ("herald",) and rest and not _TASK_WORD.match(rest) and not re.match(r"^(?:ki |ka |ke |se |ko |about|on |for |in |from )", rest):
        rest = rest                                           # "herald pakistan" is fine
    return _run_agent(ctx, name, rest)


@fskill(r"^(?:do |run |make |start |please do )?(?:a |some |deep |detailed )?research(?: report)?(?: on| about| into| for)? (.+)$|"
        r"^research karo (.+)$|^(?:(.+?) )(?:par|pe|per|ke baare mein|ke bare mein|k bare mein) (?:research|tehqeeq|maloomat)(?: karo| kar do| lao| nikalo| batao| chahiye)?$")
def _research(ctx, m, t):
    task = next((g for g in m.groups() if g), "")
    if not task or task.split()[0] in ("is", "was", "has", "paper", "papers", "shows"):
        return None
    return _run_agent(ctx, "scout", task)


@fskill(r"^(?:cheap |best )?flights? (?:from .+ )?to .+$|^(?:plan|organi[sz]e|arrange) (?:a |my |me a )?(?:trip|tour|holiday|vacation|travel)(?: plan)?(?: to| for)? .+$|"
        r"^(.+?) (?:ki|ka|ke liye) (?:flights?|trip|safar|tour) (?:dhundo|batao|plan karo|dekho|check karo)$")
def _travel(ctx, m, t):
    req = m.group(1) if m.lastindex and m.group(1) else t
    if not m.lastindex or not m.group(1):
        req = re.sub(r"^(?:plan|organi[sz]e|arrange)(?: a| my| me a)? ", "", t)
    else:
        req = "to " + req
    return agents.dispatch(ctx, "voyager", req)


@fskill(r"^(?:write|make|give me|create|generate|draft)(?: me)? (?:some |a few |\d+ |ten |five )?(?:instagram |facebook |tiktok |linkedin |social media )?"
        r"(?:captions?|hashtags?|content plan|social media plan)(?: for| on| about)? (.+)$")
def _social(ctx, m, t):
    return _run_agent(ctx, "social", m.group(1))


@fskill(r"^(?:find |give me |suggest |get |show me )?(?:seo )?keywords? (?:for|on|about) (.+)$")
def _seo(ctx, m, t):
    return _run_agent(ctx, "seo", m.group(1))


@fskill(r"^(?:make|write|create|draft|give me)(?: me)? (?:a |an )?(?:plan|strategy|roadmap|study plan|business plan) (?:for|to|on) (.+)$")
def _muse(ctx, m, t):
    return _run_agent(ctx, "muse", m.group(0))


# ============================================================================ Word / PDF of the last report (SCRIBE)
@fskill(r"^(?:scribe[ ,]*)?(?:make|create|save|export|convert|turn|give me|write|banao|generate)(?: me)?(?: a| an| the| this| that| last| latest| scouts?)*"
        r"(?: report| briefing| research| notes?| it)?(?: into| to| as| in)?(?: a| an)? (word|docx|pdf)(?: file| document| doc)?(?: of (?:the |that |last |it).*| from (?:the |that |last ).*)?$|"
        r"^(?:(?:report|briefing|research|isko|usko|iski|uski|iss ki|us ki|last report ki|scout ki report ki|scout ki|aakhri report ki)(?: ki)? )?(word|pdf|docx)(?: file| document)? "
        r"(?:banao|bana do|bana den|chahiye|do|bhejo)$|^(?:scribe)[ ,]+(word|pdf|docx)$")
def _scribe(ctx, m, t):
    fmt = next(g for g in m.groups() if g)
    rec = agents.last()
    if not rec or not rec.get("text"):
        return "There is no report to convert yet. Ask for a briefing or a research report first."
    want_pdf = fmt == "pdf"
    title, text = rec["title"], rec["text"]

    def work():
        blocks = docs.blocks_from_text(text)
        if want_pdf and docs.pdf_possible(title + text):
            path = docs.write_pdf(docs.unique_path(title, ".pdf", "scribe"), title, blocks)
            note = ""
        else:
            path = docs.write_docx(docs.unique_path(title, ".docx", "scribe"), title, blocks)
            note = " Urdu text cannot go into my PDF writer, so I made a Word file instead." if want_pdf else ""
        ctx.hud_post("log", "sys", "saved  " + os.path.basename(path))
        return "Done. I saved %s in your reports folder.%s" % (os.path.basename(path), note)
    return _bg(ctx, "SCRIBE is on it.", work)


# ============================================================================ help (extends the old help)
_NEW_HELP = (" New: say briefing for weather, internet speed and headlines. Speed check. Write a note, and I keep it in a Word file too. "
             "Show reports, or open the scout report. Smart mode or local mode. Repeat the last briefing. "
             "Call my agents by name: scout researches, herald reads the news, voyager plans trips, social writes captions, "
             "seo finds keywords, and muse makes plans. Say make a word file or make a pdf to save the last report. "
             "Also: prayer times and next prayer, focus mode, translate, currency and unit conversion, a to-do list, the clipboard, "
             "summarize this page, and a daily journal. "
             "Roman Urdu works too, like briefing sunao or awaz barhao.")


@fskill(r"^(?:what can you do|help|commands|what are your commands|show help|what are your features)$|^(?:new features|what is new|whats new)$")
def _help3(ctx, m, t):
    try:
        from . import extras
        base = extras._help2(ctx, m, t)
    except Exception:
        base = S._help(ctx, m, t)
    return base + _NEW_HELP


# ============================================================================ Part B (extras2.py: S1-S8), then install in front
_FIRST: list = []
try:
    from . import extras2  # noqa: F401 - S1-S8 register themselves into extras2._MINE / extras2._FIRST
    _FIRST = list(extras2._FIRST)                                    # the journal answer catcher must see every sentence first
    _MINE.extend(extras2._MINE)
except Exception:                                                 # never let an optional module stop Jarvis
    log.exception("extras2 failed to load")

_names = {id(fn) for _, fn, _ in S._SKILLS}
S._SKILLS[:0] = [e for e in _FIRST + _MINE if id(e[1]) not in _names]
