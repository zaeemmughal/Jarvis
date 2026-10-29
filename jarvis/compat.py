"""Chat providers. Groq, Grok (xAI) and OpenRouter all speak the OpenAI chat-completions protocol, so one class serves both.

A provider asks the service which models the key can use, ranks them, and walks down the list: a model that is busy
(429), retired (404) or erroring (5xx) is skipped for a while and the next one is tried. That matters most for
OpenRouter's free models, which are often rate-limited by whoever hosts them.
"""
from __future__ import annotations

import re
import time

from . import net


class Provider:
    def __init__(self, name: str, base: str, key: str, models: str, prefer, include: str, exclude: str, report,
                 extra_headers: dict | None = None):
        self.name, self.base, self.key = name, base, key
        self.fixed = [m.strip() for m in models.split(",") if m.strip() and m.strip().lower() != "auto"]
        self.prefer, self.report = prefer, report
        self.include, self.exclude = re.compile(include), re.compile(exclude)
        self.extra = extra_headers or {}
        self.ranked: list[str] = list(self.fixed)
        self.bad: dict[str, float] = {}                 # model -> time it may be tried again
        self.off_until, self.reason = 0.0, ""           # whole provider paused (bad key, no credit ...)
        self.model = self.fixed[0] if self.fixed else ""  # the one that last worked (for the HUD)

    def ready(self, selected: str, offline: bool) -> bool:
        return bool(self.key) and selected in ("auto", self.name) and not offline and time.time() >= self.off_until

    # ---- http ---------------------------------------------------------------------
    def _call(self, path: str, body: dict | None = None, timeout: float = 30):
        headers = dict(self.extra, Authorization="Bearer " + self.key)
        if body is None:
            return net.get_json(self.base + path, None, 10, headers)
        return net.post_json(self.base + path, body, timeout, headers)

    # ---- models -------------------------------------------------------------------
    def discover(self) -> list[str]:
        if self.ranked:
            return self.ranked
        ids = [m.get("id", "") for m in self._call("/models").get("data", []) if isinstance(m, dict)]
        ok = [i for i in ids if i and self.include.search(i) and not self.exclude.search(i)]
        if not ok:
            raise net.NetError("No usable chat model was found for this %s key." % self.name, 404)
        self.ranked = sorted(ok, key=self.prefer)
        self.model = self.ranked[0]
        self.report("sys", "%s: %d usable models, starting with %s." % (self.name.title(), len(ok), self.model))
        return self.ranked

    def candidates(self, limit: int = 4) -> list[str]:
        now = time.time()
        return [m for m in self.discover() if self.bad.get(m, 0) <= now][:limit]

    # ---- chat ---------------------------------------------------------------------
    def chat(self, messages: list, temperature: float = 0.8, max_tokens: int = 600, timeout: float = 30) -> str:
        last: net.NetError | None = None
        tried = self.candidates()
        for model in tried:
            try:
                data = self._call("/chat/completions", {"model": model, "messages": messages, "stream": False,
                                                        "temperature": temperature, "max_tokens": max_tokens}, timeout)
            except net.NetError as e:
                if e.status in (401, 402, 403) or e.status is None:     # key / credit / network: not the model's fault
                    raise
                last = e
                self.bad[model] = time.time() + (300 if e.status == 429 else 120)
                self.report("sys", "%s: %s is busy or unavailable (%s), trying another." % (self.name.title(), model, e.status))
                continue
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                text = ""
            if not text.strip():                                         # some free models return nothing
                self.bad[model] = time.time() + 60
                continue
            if model != self.model:
                self.model = model
            return text
        if last:
            raise last
        raise net.NetError("No %s model answered." % self.name, 429 if tried else 404)

    def stream(self, messages: list, temperature: float = 0.8, max_tokens: int = 600, timeout: float = 30,
               should_stop=None):
        """Yield the answer in small pieces as the model writes it, so Jarvis can start talking after the first
        sentence instead of after the whole reply. Walks down the model list exactly like chat(): a model that is
        busy or broken *before it says anything* is skipped; an error after the first piece just ends the stream
        (the caller already has some text)."""
        last: net.NetError | None = None
        tried = self.candidates()
        for model in tried:
            got = False
            gen = None
            try:
                gen = net.post_stream(self.base + "/chat/completions",
                                      {"model": model, "messages": messages, "stream": True,
                                       "temperature": temperature, "max_tokens": max_tokens},
                                      timeout, dict(self.extra, Authorization="Bearer " + self.key))
                for ev in gen:
                    if should_stop and should_stop():
                        return
                    try:
                        piece = ev["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError, TypeError, AttributeError):
                        piece = ""
                    if piece:
                        got = True
                        yield piece
                if got:
                    self.model = model
                    return
                self.bad[model] = time.time() + 60                       # model answered with nothing
            except net.NetError as e:
                if got:
                    return
                if e.status in (401, 402, 403) or e.status is None:
                    raise
                last = e
                self.bad[model] = time.time() + (300 if e.status == 429 else 120)
                self.report("sys", "%s: %s is busy or unavailable (%s), trying another." % (self.name.title(), model, e.status))
            finally:
                if gen is not None and hasattr(gen, "close"):
                    gen.close()
        if last:
            raise last
        raise net.NetError("No %s model answered." % self.name, 429 if tried else 404)

    # ---- state --------------------------------------------------------------------
    def pause(self, secs: float, reason: str) -> None:
        self.off_until, self.reason = time.time() + secs, reason

    def error(self, e: net.NetError) -> None:
        if e.status in (401, 403):
            self.pause(300, "%s key rejected or has no access" % self.name)
        elif e.status == 402:
            self.pause(600, "%s is out of credit" % self.name)
        elif e.status == 404:
            self.ranked = list(self.fixed)                                # re-discover next time
            self.pause(120, "no working %s model" % self.name)
        elif e.status == 429:
            self.pause(45, "%s rate limited" % self.name)
        else:
            self.pause(20, "%s unreachable" % self.name)


def groq(cfg, report) -> Provider:
    """Groq (console.groq.com): very fast OpenAI-compatible chat. Voice/safety/speech models are filtered out and the
    big general chat models are tried first, with the small 'instant' model as the quick backup."""
    order = ("llama-3.3-70b", "gpt-oss-120b", "llama-4", "qwen", "kimi", "llama-3.1-8b", "gpt-oss-20b", "llama")

    def pref(i):
        low = i.lower()
        return (next((n for n, k in enumerate(order) if k in low), len(order)), i)
    return Provider("groq", "https://api.groq.com/openai/v1", cfg.groq_key, cfg.groq_model, pref,
                    r"llama|gpt-oss|qwen|kimi|mixtral|gemma",
                    r"whisper|guard|tts|playai|orpheus|safeguard|embed|compound|vision|prompt|distil|moderation|"
                    r"scout-17b-16e-instruct-.*vision", report)


def grok(cfg, report) -> Provider:
    pref = lambda i: ("fast" not in i, "reasoning" in i and "non-reasoning" not in i, i)
    return Provider("grok", "https://api.x.ai/v1", cfg.xai_key, cfg.grok_model, pref, r"^grok",
                    r"image|imagine|video|vision|embed", report)


def openrouter(cfg, report) -> Provider:
    """Only the models whose id ends in ':free'. Instruction-tuned chat models first, 'thinking' models never
    (they are slow and ramble, which is wrong for a voice assistant)."""
    order = ("llama-3.3", "gpt-oss", "llama-4", "qwen", "gemma", "mistral", "llama", "glm", "deepseek")

    def pref(i):
        low = i.lower()
        rank = next((n for n, k in enumerate(order) if k in low), len(order))
        return (rank, "70b" not in low and "120b" not in low, i)
    return Provider("openrouter", "https://openrouter.ai/api/v1", cfg.openrouter_key, cfg.openrouter_model, pref,
                    r":free$", r"vision|image|embed|guard|r1|thinking|reasoning|coder|audio|moderation|safeguard|"
                                r"instruct-base|lyria|vl\b|-vl-", report,
                    {"HTTP-Referer": "https://github.com/jarvis-desktop", "X-Title": "JARVIS Desktop Assistant"})
