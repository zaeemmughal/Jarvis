"""Background agents.

Six specialists you can call by name. Each one works on a worker thread, writes a Word report into reports/, shows the
text on the HUD, remembers it in LAST_REPORTS (so "repeat the report" works) and only SPEAKS the result if nobody
said "stop" in the meantime (ctx.epoch). Every agent has a useful no-AI fallback, so they still work in LOCAL mode or
without a key.

    SCOUT   deep research on a topic          HERALD  news on a country / topic
    VOYAGER trips, flights, destinations      SOCIAL  captions, hashtags, content plans
    SEO     keywords, titles, page outlines   MUSE    plans, strategy, drafts, decisions
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass

from . import docs, net, newsdesk, services, urdu

log = logging.getLogger("jarvis.agents")

LAST_REPORTS: dict = {}          # key ("scout", "briefing", ...) -> {"title", "text", "spoken", "path", "time"}; "_last" = newest key
_lock = threading.Lock()


@dataclass
class Report:
    title: str
    text: str                    # full report (paragraphs, "- " bullets, "## " headings)
    spoken: str = ""             # short spoken summary
    kind: str = ""


def record(key: str, title: str, text: str, spoken: str = "", path: str | None = None) -> None:
    with _lock:
        LAST_REPORTS[key] = {"title": title, "text": text, "spoken": spoken, "path": path, "time": time.time()}
        LAST_REPORTS["_last"] = key


def last(key: str | None = None):
    with _lock:
        k = key or LAST_REPORTS.get("_last")
        return LAST_REPORTS.get(k) if k else None


def speak_if_current(ctx, epoch: int, text: str) -> bool:
    """Speak a background result only when the user has not interrupted since the job started."""
    if text and epoch == getattr(ctx, "epoch", epoch):
        ctx.respond(text)
        return True
    return False


def show(ctx, title: str, text: str) -> None:
    """Post a text to the HUD: the transcript always, the reading panel when a HUD exists."""
    try:
        ctx.hud_post("panel", title, text)
        ctx.hud_post("log", "sys", "%s\n%s" % (title, text[:1500] + ("..." if len(text) > 1500 else "")))
    except Exception:
        log.exception("show failed")


def save_report(title: str, text: str, prefix: str = "") -> str | None:
    try:
        return docs.write_docx(docs.unique_path(title, ".docx", prefix), title, docs.blocks_from_text(text))
    except Exception:
        log.exception("could not save report %r", title)
        return None


def short_spoken(text: str, sentences: int = 2, limit: int = 320) -> str:
    """The first real paragraph of a report (not a heading, not the 'Created by' line) as a few spoken sentences."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip() and not p.lstrip().startswith("#")
             and not p.startswith("Created by J.A.R.V.I.S")]
    prose = [p for p in paras if not re.match(r"^\s*[-*\u2022]", p)]
    pick = (prose or paras or [""])[0]
    pick = ". ".join(re.sub(r"^\s*[-*\u2022]\s*", "", ln).strip().rstrip(".") for ln in pick.split("\n") if ln.strip()) + "."
    return services.shorten(re.sub(r"\s+", " ", pick).strip(), sentences, limit)


def read_aloud(text: str, limit: int = 700) -> str:
    """The body of a report as speakable text (title and 'Created by' line dropped, bullets become sentences)."""
    lines = []
    for ln in (text or "").split("\n"):
        ln = re.sub(r"^\s*(?:#+|[-*\u2022])\s*", "", ln).strip()
        if ln and not ln.startswith("Created by J.A.R.V.I.S"):
            lines.append(ln if ln[-1] in ".!?\u06d4\u061f:" else ln + ".")
    out = ""
    for ln in lines[1:] if len(lines) > 1 else lines:             # the first line is the title
        if len(out) + len(ln) > limit:
            break
        out += " " + ln
    return out.strip()


def run_background(ctx, key: str, work, ack: str, fail: str = "Sorry, that job failed. The details are in the log.") -> str:
    """Start `work()` (returns Report) on a worker thread and return the acknowledgement to speak right away."""
    epoch = ctx.epoch if hasattr(ctx, "epoch") else 0

    def job():
        try:
            rep = work()
        except Exception:
            log.exception("agent %s failed", key)
            speak_if_current(ctx, epoch, fail)
            return
        if not rep or not rep.text.strip():
            speak_if_current(ctx, epoch, fail)
            return
        path = save_report(rep.title, rep.text, key)                  # files are saved even if the user said stop
        spoken = rep.spoken or short_spoken(rep.text)
        record(key, rep.title, rep.text, spoken, path)
        show(ctx, rep.title, rep.text)
        tail = " The full report is saved in your reports folder." if path else ""
        speak_if_current(ctx, epoch, "%s %s%s" % (key.upper() + " reporting.", spoken, tail))

    threading.Thread(target=job, daemon=True, name="agent-" + key).start()
    return ack


# ---------------------------------------------------------------------------- research helpers
def _try(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        log.info("%s failed: %s", getattr(fn, "__name__", fn), e)
        return None


def suggestions(query: str, n: int = 10) -> list[str]:
    """Google autosuggest (free, no key): what people really type after `query`."""
    data = _try(net.get_json, "https://suggestqueries.google.com/complete/search", {"client": "firefox", "q": query}, 8)
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [str(x) for x in data[1]][:n]
    return []


def _ai(ctx, prompt: str, system: str, tokens: int = 900) -> str | None:
    brain = getattr(ctx, "brain", None)
    if not brain or not hasattr(brain, "complete"):
        return None
    return brain.complete(prompt, system, tokens, 25)


_SYS = ("You are a specialist agent inside a voice assistant. Write a clear, practical report in plain text: a one-line "
        "summary first, then short sections that start with '## ', and '- ' bullets. No markdown tables, no emoji, no "
        "URLs unless given. Be concrete. Say so when something is uncertain.")


def _lang_note() -> str:
    return " Write the report in Urdu (Urdu script)." if urdu.is_urdu() else ""


# ---------------------------------------------------------------------------- SCOUT
def scout(ctx, topic: str) -> Report:
    wiki = _try(services.wikipedia, topic)
    ddg = _try(services.duckduckgo, topic)
    news = _try(newsdesk.fetch, extra=topic, n=6, home=getattr(ctx.cfg, "news_region", "PK"))
    heads = [it.title for it in (news.items if news else [])]
    facts = []
    if wiki:
        facts.append("Wikipedia (%s): %s" % (wiki[0], wiki[1]))
    if ddg:
        facts.append("DuckDuckGo: %s" % ddg[1])
    if heads:
        facts.append("Recent headlines: " + " | ".join(heads))
    title = "Research - " + topic
    ai = _ai(ctx, "Topic: %s\n\nSources gathered:\n%s\n\nWrite a research report." % (topic, "\n".join(facts) or "(none found)"),
             _SYS + _lang_note())
    if ai:
        return Report(title, ai, kind="research")
    if not facts:
        return Report(title, "## Summary\nI could not find anything reliable on %s right now. Check the connection and try again." % topic,
                      "I could not find anything reliable on that right now.", "research")
    parts = ["## Summary\n" + (wiki[1] if wiki else (ddg[1] if ddg else facts[0]))]
    if wiki and ddg and ddg[1] != wiki[1]:
        parts.append("## Quick answer\n" + ddg[1])
    if heads:
        parts.append("## In the news\n" + "\n".join("- " + h for h in heads))
    parts.append("## Note\nAI writing was not available, so this report is a plain collection of what the free sources returned.")
    spoken = services.shorten(wiki[1] if wiki else (ddg[1] if ddg else facts[0]), 2, 300)
    if heads:
        spoken += " I also found %d recent headline%s." % (len(heads), "" if len(heads) == 1 else "s")
    return Report(title, "\n\n".join(parts), spoken, "research")


# ---------------------------------------------------------------------------- HERALD
def herald(ctx, subject: str) -> Report:
    s = (subject or "").lower().strip()
    country, topic = newsdesk.country_of(s), newsdesk.topic_of(s)
    home = getattr(ctx.cfg, "news_region", "PK")
    ur = urdu.is_urdu()
    if country or topic or not s:
        res = _try(newsdesk.fetch, country=country or (None if topic else home), topic=topic, urdu=ur, n=8, home=home)
    else:
        res = _try(newsdesk.fetch, extra=s, urdu=ur, n=8, home=home)
    if not res or not res.items:
        return Report("News desk", "No headlines could be fetched right now.", "I could not reach the news feed right now.", "news")
    label = res.label_ur if ur else res.label_en
    lines = ["- %s%s" % (it.title, " (%s)" % it.source if it.source else "") for it in res.items]
    body = "## Headlines - %s\n%s" % (label, "\n".join(lines))
    ai = None if ur else _ai(ctx, "Headlines:\n%s\n\nGive a 3-sentence overview of what is going on, then 3 bullets on what to watch." %
                             "\n".join(it.title for it in res.items), _SYS, 400)
    if ai:
        body = "## Overview\n%s\n\n%s" % (ai, body)
    return Report("News - %s" % label, body, newsdesk.spoken(res, ur), "news")


# ---------------------------------------------------------------------------- VOYAGER
def _flights_url(origin: str, dest: str) -> str:
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote("Flights from %s to %s" % (origin, dest))


def voyager(ctx, request: str) -> Report:
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)$", request)
    origin, dest = (m.group(1).strip(), m.group(2).strip()) if m else ("", re.sub(r"^(?:a |the )?(?:trip|travel|flight|flights|holiday|vacation)?\s*(?:to|for|in)\s+", "", request).strip() or request)
    dest = re.sub(r"\b(?:flights?|tickets?|trip|plan)\b", "", dest).strip(" ,") or dest
    wx = _try(services.weather, dest)
    wiki = _try(services.wikipedia, dest)
    facts = []
    if wiki:
        facts.append("About %s: %s" % (dest, wiki[1]))
    if wx:
        facts.append("Weather now in %s: %d C, %s; today %d to %d C, rain chance %d percent." %
                     (wx["city"], wx["temp"], wx["desc"], wx["low"], wx["high"], wx["rain"]))
    link = _flights_url(origin or getattr(ctx.cfg, "home_city", "Sargodha"), dest)
    title = "Travel - " + dest
    ai = _ai(ctx, "Trip request: %s\nFacts:\n%s\n\nWrite a trip brief: best time to go, a 3-day outline, budget tips, and what to check "
                  "before booking (visa, documents, weather). Do not invent flight prices." % (request, "\n".join(facts) or "(none)"),
             _SYS + _lang_note(), 900)
    if ai:
        return Report(title, ai + "\n\n## Flights\n- Compare live fares here: " + link, kind="travel")
    text = ("## Destination\n%s\n\n## Flights\n- I cannot see live fares for free. Compare them here: %s\n\n## Before you book\n"
            "- Check passport validity and visa rules.\n- Check the weather for your dates.\n"
            "- Compare at least two airlines and the baggage allowance." % ("\n".join(facts) or "No live facts were available for %s." % dest, link))
    spoken = (wx and "In %s it is %d degrees with %s." % (wx["city"], wx["temp"], wx["desc"]) or "") + " I put a flight comparison link in the report."
    return Report(title, text, spoken.strip(), "travel")


# ---------------------------------------------------------------------------- SOCIAL
def _words(topic: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 2 and w not in ("the", "for", "and", "with", "about", "post", "caption", "captions")]


def social(ctx, topic: str) -> Report:
    title = "Social media - " + topic
    ai = _ai(ctx, "Topic or product: %s\n\nWrite: 5 captions in different tones, 15 hashtags, a 7-day content plan (one line per day), "
                  "and 3 campaign ideas." % topic, _SYS + _lang_note(), 900)
    if ai:
        return Report(title, ai, kind="social")
    ws = _words(topic) or ["brand"]
    tag = "".join(w.capitalize() for w in ws[:3])
    caps = ["Meet %s - made for people who care about quality." % topic, "Big things start small. Today: %s." % topic,
            "Why settle? Try %s and feel the difference." % topic, "Your daily dose of %s. Tell us what you think below." % topic,
            "New day, new reason to love %s." % topic]
    tags = ["#" + tag] + ["#" + w for w in ws[:6]] + ["#pakistan", "#sargodha", "#trending", "#explore", "#smallbusiness", "#localbrand"]
    plan = ["Day 1: announce %s with a photo." % topic, "Day 2: behind the scenes.", "Day 3: customer question and answer.",
            "Day 4: short video or reel.", "Day 5: testimonial or review.", "Day 6: offer or giveaway.", "Day 7: recap and thank you."]
    text = "## Captions\n" + "\n".join("- " + c for c in caps) + "\n\n## Hashtags\n" + " ".join(tags) + \
           "\n\n## 7-day plan\n" + "\n".join("- " + p for p in plan) + "\n\n## Note\nAI was not available, so these are template drafts. Edit them to your voice."
    return Report(title, text, "I wrote five caption drafts, hashtags and a seven day plan.", "social")


# ---------------------------------------------------------------------------- SEO
def seo(ctx, topic: str) -> Report:
    title = "SEO - " + topic
    sug = []
    for q in (topic, topic + " how to", topic + " best", topic + " near me"):
        sug += suggestions(q, 6)
    sug = list(dict.fromkeys(sug))[:20]
    ai = _ai(ctx, "Topic: %s\nReal search suggestions people type:\n%s\n\nGive: a primary keyword, 10 secondary keywords, 3 title tags "
                  "(under 60 characters), a meta description (under 155 characters), and a page outline with H2 headings." %
             (topic, "\n".join(sug) or "(none)"), _SYS + _lang_note(), 800)
    if ai:
        return Report(title, ai, kind="seo")
    primary = sug[0] if sug else topic
    t = topic.strip().title()
    text = ("## Primary keyword\n%s\n\n## Keywords people search\n%s\n\n## Title ideas\n- %s: The Complete Guide\n- Best %s in %s\n- %s - Tips, Prices and Reviews"
            "\n\n## Meta description\nEverything you need to know about %s: how it works, what it costs and how to choose the best option.\n\n"
            "## Page outline\n- What is %s\n- Why it matters\n- How to choose\n- Prices and options\n- Frequently asked questions\n\n"
            "## Note\nAI was not available, so the keywords come from Google autosuggest and the titles are templates." %
            (primary, "\n".join("- " + s for s in sug) or "- (no suggestions could be fetched)", t, t, time.strftime("%Y"), t, topic, topic))
    return Report(title, text, "Your main keyword is %s. I listed %d related searches and drafted titles." % (primary, len(sug)), "seo")


# ---------------------------------------------------------------------------- MUSE
def muse(ctx, request: str) -> Report:
    title = "Plan - " + request[:50]
    ai = _ai(ctx, "Request: %s\n\nWrite a practical plan or draft. Include: goal, 5 to 8 concrete steps with order, risks, and a "
                  "clear recommendation if a decision is needed." % request, _SYS + _lang_note(), 900)
    if ai:
        return Report(title, ai, kind="plan")
    text = ("## Goal\n%s\n\n## Steps\n- Define exactly what done looks like.\n- List what you already have and what is missing.\n"
            "- Break the work into pieces of under two hours.\n- Do the riskiest or most uncertain piece first.\n- Review progress at the halfway point.\n"
            "- Finish, test and write down what you learned.\n\n## Risks\n- Unclear scope.\n- Underestimated time.\n\n"
            "## Note\nAI was not available, so this is a generic planning template. Say it again when Smart mode is on for a tailored plan." % request)
    return Report(title, text, "AI is off, so I wrote a general plan template for that.", "plan")


AGENTS = {
    "scout": (scout, "researching"), "herald": (herald, "gathering the news"), "voyager": (voyager, "planning the trip"),
    "social": (social, "drafting the posts"), "seo": (seo, "checking the keywords"), "muse": (muse, "working out a plan"),
}


def dispatch(ctx, name: str, task: str) -> str:
    """Start agent `name` on `task`. Returns the sentence to speak now (the result is spoken when it is ready)."""
    fn, doing = AGENTS[name]
    task = (task or "").strip()
    return run_background(ctx, name, lambda: fn(ctx, task), "%s here, %s. I will report back." % (name.upper(), doing),
                          "%s could not finish that job. The details are in the log." % name.upper())
