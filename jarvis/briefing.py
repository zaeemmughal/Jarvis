"""Briefing: weather + internet speed + top headlines, spoken and shown on the HUD.

Runs automatically a few seconds after start-up (JARVIS_STARTUP_BRIEFING=off disables it) and on demand with
"briefing" / "briefing sunao". Gathering happens on a worker thread; each part has its own timeout and fails quietly,
so a missing part is simply left out. Nothing from earlier conversations is mentioned.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from . import agents, net, newsdesk, services, urdu

log = logging.getLogger("jarvis.briefing")


# ---------------------------------------------------------------------------- speed
def speed_test(timeout: float = 12.0) -> dict | None:
    """Ping (ms) and download speed (Mbit/s) against Cloudflare's free speed endpoint. None when offline."""
    try:
        t0 = time.time()
        net.get_bytes("https://www.cloudflare.com/cdn-cgi/trace", timeout=min(timeout, 6))
        ping = (time.time() - t0) * 1000
        t0 = time.time()
        data = net.get_bytes("https://speed.cloudflare.com/__down", {"bytes": 4_000_000}, timeout=timeout)
        secs = max(time.time() - t0, 0.001)
        return {"ping": round(ping), "mbps": round(len(data) * 8 / secs / 1e6, 1)}
    except Exception as e:
        log.info("speed test failed: %s", e)
        return None


def speed_sentence(s: dict | None, ur: bool = False) -> str:
    if not s:
        return "انٹرنیٹ کی رفتار نہیں ناپی جا سکی۔" if ur else "I could not measure the internet speed right now."
    if ur:
        return "انٹرنیٹ کی ڈاؤن لوڈ رفتار %s میگابٹ فی سیکنڈ ہے اور پنگ %d ملی سیکنڈ۔" % (s["mbps"], s["ping"])
    return "Internet speed is %s megabits per second down, with a ping of %d milliseconds." % (s["mbps"], s["ping"])


# ---------------------------------------------------------------------------- weather
def weather_sentence(w: dict | None, ur: bool = False) -> str:
    if not w:
        return ""
    if ur:
        return "%s میں اس وقت %d ڈگری ہے، آج کا اندازہ %d سے %d ڈگری، بارش کا امکان %d فیصد۔" % (w["city"], w["temp"], w["low"], w["high"], w["rain"])
    s = "In %s it is %d degrees with %s, a high of %d and a low of %d." % (w["city"], w["temp"], w["desc"], w["high"], w["low"])
    if w.get("rain", 0) >= 40:
        s += " There is a %d percent chance of rain, so keep an umbrella handy." % w["rain"]
    return s


# ---------------------------------------------------------------------------- build
def gather(cfg, n: int = 10, with_speed: bool = True) -> dict:
    """Fetch the three parts in parallel. Returns {"weather", "speed", "items"} (any may be empty)."""
    out: dict = {"weather": None, "speed": None, "items": [], "todos": []}

    def w():
        try:
            out["weather"] = services.weather(cfg.home_city)
        except Exception as e:
            log.info("weather failed: %s", e)

    def s():
        if with_speed:
            out["speed"] = speed_test()

    def h():
        ur = urdu.is_urdu()
        try:
            out["items"] = newsdesk.fetch(country=cfg.news_region, urdu=ur, n=n, home=cfg.news_region).items
        except Exception as e:
            log.info("news failed: %s", e)
            try:
                out["items"] = [newsdesk.Item(t) for t in services.news(n, cfg.news_region)]
            except Exception:
                out["items"] = []

    def td():
        try:
            from . import extras2
            out["todos"] = extras2.pending()
        except Exception as e:
            log.info("to-do list failed: %s", e)

    ts = [threading.Thread(target=f, daemon=True) for f in (w, s, h, td)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(25)
    return out


def format_briefing(parts: dict, who: str = "", ur: bool = False, greet: bool = False) -> tuple[str, str]:
    """-> (spoken text, display text)."""
    spoken, shown = [], []
    if greet:
        h = int(time.strftime("%H"))
        if ur:
            spoken.append("%s%s۔" % ("صبح بخیر" if h < 12 else ("سلام" if h < 18 else "شام بخیر"), "، " + who if who else ""))
        else:
            spoken.append("%s%s." % ("Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening"), ", " + who if who else ""))
    w = weather_sentence(parts.get("weather"), ur)
    if w:
        spoken.append(w)
        shown.append("## Weather\n" + w)
    if parts.get("speed") is not None or parts.get("with_speed"):
        sp = speed_sentence(parts.get("speed"), ur)
        spoken.append(sp)
        shown.append("## Internet\n" + sp)
    todos = parts.get("todos") or []
    if todos:
        line = ("آپ کے %d کام باقی ہیں: %s۔" if ur else "You have %d open task%s on your list: %s.")
        line = line % (len(todos), "، ".join(todos[:5])) if ur else line % (len(todos), "" if len(todos) == 1 else "s", ", ".join(todos[:5]))
        spoken.append(line)
        shown.append("## To-do\n" + "\n".join("- " + x for x in todos))
    items = parts.get("items") or []
    if items:
        spoken.append(("یہ ہیں آج کی خبریں۔ " if ur else "Here are today's headlines. ") + " ".join(it.title.rstrip(" .۔") + ("۔" if ur else ".") for it in items))
        shown.append("## Headlines\n" + "\n".join("- " + it.title for it in items))
    if not (w or items):
        spoken.append("میں ابھی کچھ حاصل نہیں کر سکا۔" if ur else "I could not reach any of my sources right now.")
    spoken.append("سر، آج کیا کام کرنا ہے؟" if ur else "Sir, what would you like to work on today?")
    return " ".join(spoken), "\n\n".join(shown)


def run(ctx, startup: bool = False) -> None:
    """Gather and deliver a briefing on a worker thread (returns immediately)."""
    epoch = getattr(ctx, "epoch", 0)

    def job():
        try:
            ur = urdu.is_urdu()
            parts = gather(ctx.cfg)
            parts["with_speed"] = True
            who = getattr(ctx.mem, "name", "") or getattr(ctx.cfg, "user_name", "")
            spoken, shown = format_briefing(parts, who, ur, greet=False)
            title = "BRIEFING - " + time.strftime("%A %d %B")
            agents.record("briefing", title, shown, spoken)
            agents.show(ctx, title, shown or spoken)
            agents.speak_if_current(ctx, epoch, spoken)
        except Exception:
            log.exception("briefing failed")
            agents.speak_if_current(ctx, epoch, "Sorry, I could not put the briefing together.")

    threading.Thread(target=job, daemon=True, name="briefing").start()


def startup_enabled() -> bool:
    return (os.environ.get("JARVIS_STARTUP_BRIEFING", "on").strip().lower() not in ("0", "off", "false", "no"))


def start_at_boot(ctx) -> None:
    """Called at the end of Jarvis._boot, after the greeting has been queued. Never raises."""
    try:
        if startup_enabled() and getattr(ctx, "online", False):
            run(ctx, startup=True)
    except Exception:
        log.exception("startup briefing failed")
