"""Smart / Local mode.

SMART = normal: the AI brain (Groq / Grok / OpenRouter) answers, plans and powers the agents.
LOCAL = privacy mode: the AI is never called. Every voice command, the news desk, weather, notes, reports and the
        agents' no-AI fallbacks keep working; open-ended chat is limited to key-less look-ups.

The choice is saved in data/mode.txt and takes effect immediately (Brain._ready() asks is_local()).
"""
from __future__ import annotations

import os

from .config import DATA_DIR

_PATH = os.path.join(DATA_DIR, "mode.txt")
_mode: str | None = None


def _load() -> str:
    try:
        with open(_PATH, encoding="utf-8") as fh:
            return "local" if fh.read().strip().lower() == "local" else "smart"
    except OSError:
        return "local" if (os.environ.get("JARVIS_MODE", "").strip().lower() == "local") else "smart"


def get() -> str:
    global _mode
    if _mode is None:
        _mode = _load()
    return _mode


def is_local() -> bool:
    return get() == "local"


def set_mode(m: str, save: bool = True) -> str:
    global _mode
    _mode = "local" if str(m).strip().lower() == "local" else "smart"
    if save:
        try:
            os.makedirs(os.path.dirname(_PATH), exist_ok=True)
            with open(_PATH, "w", encoding="utf-8") as fh:
                fh.write(_mode)
        except OSError:
            pass
    return _mode


def describe(ctx=None) -> str:
    if is_local():
        return "Local mode: the AI is switched off, so everything stays on this PC. Commands, news and weather still work."
    ready = bool(getattr(getattr(ctx, "brain", None), "llm_ready", False))
    return "Smart mode: the AI brain is on." + ("" if ready else " No AI key is ready right now, so I am using my built-in fallbacks.")
