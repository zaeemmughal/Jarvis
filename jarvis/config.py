"""Settings. Everything can be overridden from a `.env` file or real environment variables."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")


def load_env(path: str | None = None) -> None:
    """Tiny .env reader (no python-dotenv needed). Real environment variables win."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip()
            if val[:1] in ("'", '"') and val.count(val[0]) >= 2:      # quoted: keep everything inside the quotes
                val = val[1:val.index(val[0], 1)]
            else:                                                       # unquoted: drop trailing "  # comment"
                val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
                if val.startswith("#"):
                    val = ""
            os.environ.setdefault(key.strip(), val)


def _s(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _b(name: str, default: bool) -> bool:
    v = _s(name)
    return default if v == "" else v.lower() in ("1", "true", "yes", "on")


def _n(name: str, default: float) -> float:
    try:
        return float(_s(name) or default)
    except ValueError:
        return default


@dataclass
class Config:
    groq_key: str = ""                  # Groq API key (console.groq.com) - starts with gsk_
    groq_model: str = "auto"            # auto, or one or more model ids separated by commas
    xai_key: str = ""                   # Grok (xAI) API key
    grok_model: str = "auto"            # auto, or one or more model ids separated by commas
    openrouter_key: str = ""            # OpenRouter API key (free ':free' models)
    openrouter_model: str = "auto"
    ai_provider: str = "auto"           # auto (Groq, Grok, then OpenRouter) | groq | grok | openrouter
    stt: str = "auto"                   # speech-to-text: auto (Groq Whisper if a Groq key exists, else Google) | groq | google
    stt_model: str = "whisper-large-v3-turbo"
    browser: str = "chrome"             # chrome | default | edge | firefox | brave - where websites open
    social: str = "facebook,instagram,whatsapp,twitter,linkedin,youtube"   # what "open all social media" opens
    stream_reply: bool = True           # speak the answer sentence by sentence while the AI is still writing it
    user_name: str = ""
    creator: str = ""
    home_city: str = "Sargodha"
    news_region: str = "PK"
    language: str = "en-US"
    wake_enabled: bool = True
    follow_up_secs: float = 12.0
    fps: int = 30
    lite: bool = False
    fullscreen: bool = False
    tts_engine: str = "auto"            # auto | edge | system | off
    tts_voice: str = "en-GB-RyanNeural"
    tts_rate: str = "+6%"
    force_offline: bool = False
    mic_device: str = ""                # index or name fragment; blank = system default
    vad_min: int = 220                  # minimum loudness (RMS) that counts as speech
    barge_in: bool = True               # keep listening while Jarvis talks so "stop" / "Jarvis closed" work
    barge_sens: float = 2.2             # how much louder than the room you must be to interrupt (raise if he hears himself)
    context_secs: float = 600.0         # how long "it", "there", "search X" stay linked to the last app/site
    background: bool = False            # start with the window hidden (voice only)
    close_to_background: bool = True    # the window's X button hides Jarvis instead of quitting him
    mail: str = "gmail"                 # gmail | outlook | default (mailto:) - used by "compose a new mail"

    @classmethod
    def load(cls) -> "Config":
        load_env()
        lite = _b("JARVIS_LITE", False)
        xai = _s("XAI_API_KEY") or _s("GROK_API_KEY")
        groq = _s("GROQ_API_KEY")
        if xai.startswith("gsk_"):              # a Groq key pasted into the Grok slot: it still works
            groq, xai = groq or xai, ""
        return cls(
            groq_key=groq,
            groq_model=_s("GROQ_MODEL", "auto"),
            stt=_s("JARVIS_STT", "auto").lower(),
            stt_model=_s("JARVIS_STT_MODEL", "whisper-large-v3-turbo"),
            browser=_s("JARVIS_BROWSER", "chrome").lower(),
            social=_s("JARVIS_SOCIAL", "facebook,instagram,whatsapp,twitter,linkedin,youtube"),
            stream_reply=_b("JARVIS_STREAM", True),
            xai_key=xai,
            grok_model=_s("GROK_MODEL", "auto"),
            openrouter_key=_s("OPENROUTER_API_KEY"),
            openrouter_model=_s("OPENROUTER_MODEL", "auto"),
            ai_provider=_s("JARVIS_AI", "auto").lower(),
            user_name=_s("JARVIS_USER_NAME"),
            creator=_s("JARVIS_CREATOR"),
            home_city=_s("JARVIS_CITY", "Sargodha"),
            news_region=_s("JARVIS_NEWS_REGION", "PK"),
            language=_s("JARVIS_LANGUAGE", "en-US"),
            wake_enabled=_b("JARVIS_WAKE_WORD", True),
            follow_up_secs=_n("JARVIS_FOLLOW_UP_SECS", 12),
            fps=int(_n("JARVIS_FPS", 20 if lite else 30)),
            lite=lite,
            fullscreen=_b("JARVIS_FULLSCREEN", False),
            tts_engine=_s("JARVIS_TTS", "auto").lower(),
            tts_voice=_s("JARVIS_VOICE", "en-GB-RyanNeural"),
            tts_rate=_s("JARVIS_VOICE_RATE", "+6%"),
            force_offline=_b("JARVIS_FORCE_OFFLINE", False),
            mic_device=_s("JARVIS_MIC"),
            vad_min=int(_n("JARVIS_VAD_MIN", 220)),
            barge_in=_b("JARVIS_BARGE_IN", True),
            barge_sens=_n("JARVIS_BARGE_SENS", 2.2),
            context_secs=_n("JARVIS_CONTEXT_SECS", 600),
            background=_b("JARVIS_BACKGROUND", False),
            close_to_background=_b("JARVIS_CLOSE_TO_BACKGROUND", True),
            mail=_s("JARVIS_MAIL", "gmail").lower(),
        )
