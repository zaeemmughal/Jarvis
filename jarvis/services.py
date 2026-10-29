"""Free, key-less web services: weather (Open-Meteo), news (Google News RSS), Wikipedia, DuckDuckGo."""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from . import net

WMO = {0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
       81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
       95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def shorten(text: str, sentences: int = 2, max_chars: int = 330) -> str:
    text = re.sub(r"\s*\([^)]*\)", "", text or "")
    text = re.sub(r"\[\d+\]", "", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for p in parts[:sentences]:
        if out and len(out) + len(p) > max_chars:
            break
        out = (out + " " + p).strip()
    return out[:max_chars].rstrip()


def weather(city: str) -> dict | None:
    g = net.get_json("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1, "language": "en"})
    res = g.get("results") or []
    if not res:
        return None
    p = res[0]
    w = net.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto", "forecast_days": 1,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    cur, day = w["current"], w["daily"]
    first = lambda k: (day.get(k) or [0])[0] or 0
    return {"city": p["name"], "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
            "humidity": round(cur["relative_humidity_2m"]), "wind": round(cur["wind_speed_10m"]),
            "desc": WMO.get(cur["weather_code"], "unsettled weather"),
            "high": round(first("temperature_2m_max")), "low": round(first("temperature_2m_min")),
            "rain": round(first("precipitation_probability_max"))}


def news(n: int = 5, region: str = "PK") -> list[str]:
    xml = net.get_bytes("https://news.google.com/rss", {"hl": "en-" + region, "gl": region, "ceid": "%s:en" % region})
    titles = [(it.findtext("title") or "").rsplit(" - ", 1)[0].strip() for it in ET.fromstring(xml).iter("item")]
    return [t for t in titles if t][:n]


def wikipedia(query: str):
    s = net.get_json("https://en.wikipedia.org/w/api.php",
                     {"action": "query", "list": "search", "srsearch": query, "srlimit": 1, "format": "json"})
    hits = s.get("query", {}).get("search", [])
    if not hits:
        return None
    title = hits[0]["title"]
    d = net.get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")))
    if not d.get("extract"):
        return None
    return title, shorten(d["extract"]), d.get("content_urls", {}).get("desktop", {}).get("page", "")


def duckduckgo(query: str):
    d = net.get_json("https://api.duckduckgo.com/", {"q": query, "format": "json", "no_html": 1,
                                                       "skip_disambig": 1, "t": "jarvis"})
    text = d.get("Answer") or d.get("AbstractText") or d.get("Definition")
    if isinstance(text, str) and text.strip():
        return "DuckDuckGo", shorten(text), d.get("AbstractURL", "")
    return None


_LEAD = re.compile(r"^(?:who|what|whats|whos)(?: is| are| was| were)?(?: an?| the)?\s+|^tell me (?:more )?about\s+|"
                   r"^(?:define|explain|meaning of)\s+")


def lookup(question: str):
    """Key-less answer finder. Returns (source, text, url) or None."""
    q = _LEAD.sub("", question.lower().strip()).strip() or question
    for fn in (duckduckgo, wikipedia):
        try:
            r = fn(q)
        except net.NetError:
            raise
        except Exception:
            r = None
        if r:
            if fn is wikipedia:
                return "Wikipedia", r[1], r[2]
            return r
    return None


def google_url(q: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote(q)
