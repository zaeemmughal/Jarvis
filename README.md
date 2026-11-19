# J.A.R.V.I.S - Voice-Controlled AI Desktop Assistant

A talking AI assistant with a living sci-fi HUD. Say **"Jarvis, how are you?"** and he answers out loud.
Ask him anything and he **searches Google live** and speaks the answer. He also controls your PC, sets timers,
reads the news, does maths, takes notes, and reacts to the conversation with his animated robot face.

**Pure Python. Runs on Python 3.10 - 3.14. No PyAudio, no compiling.**

## What it does

| | |
|---|---|
| **Wake word** | Always listening for "Jarvis". After a reply you can keep chatting for 12 s without repeating it. |
| **Conversation** | Natural chat with memory of the last few turns. Replies are spoken, shown on the HUD, and logged. |
| **AI answers** | Groq (or Grok / OpenRouter) answers in short spoken sentences, and he starts talking after the first sentence while the rest is still being written. Without a key: Wikipedia/DuckDuckGo lookups, then opens Google. |
| **Neural voice** | Microsoft Edge neural British voice via `edge-tts`; falls back to the Windows voice offline. |
| **Reactive face** | Blinks, looks around, and changes mood (happy / angry / sad / surprised) from what he says. |
| **Live HUD** | Real microphone waveform, CPU / RAM / battery gauges, weather card, timer countdowns, transcript, boot diagnostics. |
| **PC control** | Open/close any installed app or website, type text, shortcuts, volume, media keys, screenshot, lock. |
| **Utilities** | Weather (any city), news headlines, timers and reminders, notes, voice calculator, system status. |
| **Demo mode** | Say **"Jarvis, run the demo"** - he introduces himself and performs for an audience. |


## New: smarter, always-listening Jarvis

- **Stop works while he talks.** The mic stays open during speech. Say **"stop"** (or quiet / enough / wait) and he goes
  silent, drops any answer he was still working on, and starts listening - no wake word needed. Headphones give the best
  result; if he hears himself through speakers raise `JARVIS_BARGE_SENS`.
- **"Jarvis closed"** (also: Jarvis close / goodbye / exit / end session) ends the session, even mid-sentence.
- **Commands are linked.** "Open YouTube" then "search Karan Aujla" searches *YouTube*. He also looks at the window you
  are really in, so it works on pages you opened yourself. Also: "close it", "open it again", "do that again",
  "open YouTube and search X", and missing details are asked back ("set a timer" -> "For how long?").
- **Email:** "compose a new mail", "write an email to ali subject hello saying I'll be late", "save contact ali as ali at gmail dot com", "send it" (asks first).
- **Your PC:** "how many apps are installed", "list my apps", "is Spotify installed", "what apps are running",
  "what window is this", "how much disk space", "my IP address", "how long has the PC been on", "find file resume",
  "open downloads folder", "switch to Word", "set volume to 40", "brightness down", "shut down the PC" (asks first).
- **Unknown commands** are interpreted by the AI using the context instead of being answered with Wikipedia facts.
- **Background mode:** `python jarvis.py --background` or `Start_Jarvis_Background.bat` (no window, no console).
  "Jarvis, go to background" / "Jarvis, show yourself". The X button hides him. `python jarvis.py --autostart on`
  starts him at every Windows login. `pip install pystray pillow` adds a tray icon.

## Latest fixes - commands that stopped working after changing the speech engine
With **Groq Whisper** hearing you, sentences arrive with punctuation and extra words ("Jarvis, I said open Google
Chrome please."). The command router used to need exact wording, so "open settings", "open VS Code", "stop" and
"shut down" silently fell through to the AI chat, which then answered "I can't do that". Fixed:

- **Punctuation is ignored.** `Open settings.` = `open settings`. Decimals (`3.5`) and sites (`gmail.com`) are untouched.
- **Filler words are stripped before matching.** Lead-ins: *I said, can you, could you, please, okay, so, I want you to*.
  Endings: *please, for me, now, again, bro, sir*. Also "open **up** Chrome" and "the Chrome **browser**".
- **Stop / shut down variants work:** "Jarvis, stop." / "I said stop" / "Jarvis, I said shut down." /
  "I said you to be shut down" / "Closet." (Whisper mishearing of "closed"). A bare "close" or "close the door"
  never quits Jarvis.
- **File Explorer** opens the app (it used to open a screenshot called "File Explorer ...png"); **this PC / my computer**
  open the This PC view.
- **Settings** now really closes ("close settings" force-closes the Windows Settings app).
- **"Open a new tab / new window"** press Ctrl+T / Ctrl+N.

## What's new in this version
- **Groq brain.** Put your key from <https://console.groq.com/keys> after `GROQ_API_KEY=` in `.env`. (A `gsk_...` key pasted
  into `XAI_API_KEY` is also detected and used as Groq.) Groq is tried first; Grok and OpenRouter stay as optional backups.
- **Groq Whisper hearing.** With a Groq key, speech-to-text uses `whisper-large-v3-turbo` instead of the free Google
  recogniser: far fewer misheard words. It falls back to Google by itself if Groq is busy. `JARVIS_STT=google` turns it off.
- **Speaks while he thinks.** Answers are streamed: the first sentence is spoken as soon as it is written. Voice clips are
  made in parallel, and the text on the HUD is typed in step with each clip, so voice and typing now run together.
- **Websites open in Chrome** (`JARVIS_BROWSER=chrome`, falls back to your default browser if Chrome is missing). ~90 sites:
  Facebook, Instagram, WhatsApp, TikTok, Snapchat, X/Twitter, LinkedIn, Reddit, Pinterest, Telegram, Discord, Messenger,
  Threads, Twitch, Quora, Medium ... plus Google apps, AI sites, shopping and dev sites.
  Say: "open instagram", "open facebook, instagram and youtube", **"open all social media"**, "open tiktok in incognito",
  "search cats on tiktok". Misheard names ("insta gram", "instagrm", "tik tok", "whats app") still work.
- `python jarvis.py --check` tests your keys, browser, voice and microphone in one go.

## AI brain
Groq, Grok (xAI) and OpenRouter all speak the same protocol; Jarvis asks each service which models your key can use,
ranks them, and skips any that are busy. No model can search the web, so recent-news answers come from the model's own
knowledge. With no key every command still works; only open-ended chat is limited.

## Setup (Windows)

1. Install Python 3.10+ (3.14 is fine) from python.org and tick **Add Python to PATH**.
2. In this folder:
   ```
   pip install -r requirements.txt
   pip install -r requirements-optional.txt
   ```
   (The second file is optional but gives the much nicer voice.)
3. **Free AI brain (recommended):** get a key at <https://console.groq.com/keys>, copy `.env.example`
   to `.env`, and paste it after `GROQ_API_KEY=`. Then run `python jarvis.py --check`.
4. Run: `python jarvis.py`

F11 = fullscreen, Esc = stop talking / leave fullscreen, Ctrl+M = mic on/off, Ctrl+L = clear transcript.
The text box at the bottom always works, so you have a backup if the room is too noisy.

## Try these

- "Jarvis, how are you?" / "Jarvis, tell me about black holes" / "Who won the last cricket world cup?"
- "What's the weather in Lahore?" / "Tell me the news" / "What is 15 percent of 2400?"
- "Set a timer for 10 minutes" / "Remind me to call Ali in 20 minutes" / "Take a note buy milk" / "Read my notes"
- "Open Chrome" / "Open Notepad" / "Type hello world" / "Volume up" / "Take a screenshot" / "Play lo-fi on YouTube"
- "Be happy" / "Look left" / "Blink twice" / "Wink" / "Go to sleep" / "Wake up"
- "System status" / "My name is Hasnat" / "Stop" / "Repeat that" / "Standby" / "Goodbye"

Typing safety: move the mouse into the **top-left corner** or say "stop" to abort typing.

## Features pack: briefing, agents, reports, Word files
- **Briefing:** a few seconds after start-up Jarvis reads weather, internet speed and the top 10 headlines (`JARVIS_STARTUP_BRIEFING=off` to disable). Any time: "briefing", "briefing sunao", "aaj ka haal". (\"news briefing\" is still the old headlines-only command.)
- **Speed check:** "speed check", "speed check karo".
- **Notes -> Word:** "take a note ..." / "note likho ..." still saves to `data/notes.txt` and now also to `reports/Notes-<date>.docx`.
- **Reports in the app:** "show reports", "open the scout report", "read the report". Files live in `reports/` (`%APPDATA%\\Jarvis\\reports` in the .exe).
- **Six agents (work in the background, speak only if you did not say stop):** *scout* research, *herald* news, *voyager* trips and flights, *social* captions and hashtags, *seo* keywords, *muse* plans. Each saves a Word report and has a no-AI fallback. "make a word file" / "pdf banao" converts the last report.
- **Smart / Local mode:** "local mode" switches the AI off (nothing is sent to any model), "smart mode" turns it back on. Saved in `data/mode.txt`.
- **Roman Urdu:** "awaz barhao", "awaz 50 kar do", "2500 guna 18 kitne hue", "dobara bolo", "repeat the last briefing".
- **Part B (extras2.py):** *prayer times* ("next namaz kab hai", "namaz se pehle yaad dilao"; Aladhan, free), *focus / pomodoro* ("start focus mode", "pomodoro 50 minutes", "stop focus mode"), *translate* ("translate good morning into urdu"; AI first, MyMemory as the free fallback), *currency and units* ("100 dollar kitne rupees", "convert 5 km to miles"; open.er-api.com), *to-do list* ("add task finish report", "to-do mein add karo FYP report", "mark task 2 done"; `data/todo.json`, open tasks are read in the briefing), *clipboard* ("read the clipboard", "summarize the clipboard", "save clipboard to notes"), *page summary* ("summarize this page" on Windows, "summarize <link>"), *daily journal* ("journal likho": three questions, saved as `reports/Journal-<date>.docx`, tomorrow's item is added to the to-do list).
- New code: `features.py` (skills), `briefing.py`, `docs.py` (.docx/.pdf, no extra packages), `agents.py`, `modes.py`, `panel.py` (HUD reading panel), `extras2.py` (hook for optional extras). Tests: `tests/test_features.py`.

## Project layout

```
jarvis.py            launcher            (python jarvis.py | --devices | --selftest)
jarvis/
  app.py             controller: wake word, request queue, timers, boot, demo
  audio.py           sounddevice mic capture + adaptive voice-activity detection + speech-to-text
  brain.py           Groq / Grok / OpenRouter chat, streaming + command planner, mood tags, key-less fallback  (compat.py = provider client)
  skills.py          ~50 voice commands via a regex skill router
  tts.py             edge-tts neural voice / system voice, chunked + pre-fetched
  ui.py, face.py     Tkinter HUD and the animated face
  winctl.py          ctypes keyboard/volume/lock/screenshot (replaces pyautogui)
  browser.py         opens websites in Chrome (or your chosen browser)
  services.py        weather, news, Wikipedia, DuckDuckGo
  sysinfo.py, memory.py, config.py, net.py
tests/               python -m pytest tests -q        (pip install pytest)
  test_phrases.py    regression table: ~4000 ways of saying open / close / stop / shut down must all work
```

How a request flows: **mic -> VAD -> speech-to-text -> wake-word check -> skill router -> (no match) AI brain
-> reply -> voice + HUD**. Everything heavy runs on worker threads; the UI thread only draws.

The skill router first **cleans the sentence** (`normalize()` removes punctuation, `strip_filler()` removes
"please / I said / for me ..."), then tries the regex skills in order. Anything that looks like a command but matches no
skill is translated by the AI planner; it is never answered as a chat question.

Add your own command in `jarvis/skills.py`:
```python
@skill(r"^flip a coin$")
def _coin(ctx, m, t):
    return random.choice(["Heads.", "Tails."])
```

**After every change, run `python -m pytest tests -q`.** Fixing one phrase can break another, and
`tests/test_phrases.py` catches that immediately. When a phrase fails on your PC, copy the exact words from the
transcript and add them to the lists at the top of that file.

## Optional offline speech recognition
`pip install vosk`, download `vosk-model-small-en-us-0.15` from alphacephei.com/vosk/models, unzip it next to
`jarvis.py` (folder name `model` or the original name). Used automatically when the internet drops;
`JARVIS_FORCE_OFFLINE=true` always uses it.

## Troubleshooting
- **Install error mentioning PyAudio / "Failed building wheel"**: you have an old `requirements.txt`. This
  version no longer uses PyAudio - use the one in this folder.
- **No microphone**: Windows Settings > Privacy > Microphone, then `python jarvis.py --devices` and put the
  number in `JARVIS_MIC`. The text box works meanwhile.
- **He ignores me**: speak right after "Jarvis". Lower `JARVIS_VAD_MIN` for a quiet mic, set
  `JARVIS_LANGUAGE=en-PK`, or turn the wake word off with the WAKE button.
- **"I can't open X" / "I'm unable to ..." from Jarvis**: that is the AI chat answering because no command rule matched
  what it heard. Check the transcript for the exact words, add the phrasing to `tests/test_phrases.py`, and fix the rule.
- **"Stop" does not interrupt him**: he is probably hearing himself through the speakers. Use headphones or raise
  `JARVIS_BARGE_SENS`.
- **He hears himself**: the mic is muted while he talks; headphones help in echoey rooms.
- **AI says "rate limited"**: free tiers have per-minute and daily limits. He drops to the key-less brain for a
  minute, then recovers by himself.
- **Voice sounds robotic**: install `edge-tts` (needs internet).
- Logs are written to `logs/jarvis.log`.

## Exhibition tips
Use a headset mic, keep a phone hotspot ready, press F11, and open with "Jarvis, run the demo".

## WhatsApp, YouTube and more (new)

**WhatsApp** (desktop app or WhatsApp Web, already logged in). Nothing is ever sent without your spoken "yes".
- "Jarvis, open WhatsApp" -> "open chat of Ali" (or "open Ali's chat", "message Ali")
- "type are you coming tonight" -> typed into the open chat, not sent. Say "type ..." again to add more.
- "send" -> Jarvis reads it back: "Send this to Ali: ...? Say yes or no." -> "yes" sends, "no" cancels.
- One go: "send a message to Ali saying I'll be late" -> opens chat, types, asks for confirmation.
- "clear the message", "read the message", "close chat".
- It opens the TOP search result, so say enough of the name to be unique. If Enter alone doesn't open the chat on your
  WhatsApp version, set `JARVIS_WA_OPEN_KEYS=down,enter` in `.env`.

**YouTube**: "play <song or video> [on youtube]" now opens the first real video and starts it (no results page).
Controls (YouTube tab must be open): pause / resume, next / previous video, "skip 30 seconds", "rewind 10 seconds",
"speed up", "slow down", "subtitles", "theater mode", "mini player", "restart the video", "mute the video",
"fullscreen", "what is playing".

**Windows / browser**: "snap window left/right", "go to tab 3", "bookmark this page", "find on page <text>".

## Urdu mode and the news desk (new)

**Two languages - English and Urdu.** Switch any time: say "speak Urdu" / "اردو میں بات کرو" (and "speak English" /
"انگریزی میں بات کرو"), press the **LANG** button, or use the tray menu *Language / زبان*. The choice is remembered.
In Urdu mode Jarvis listens in Urdu (Whisper `whisper-large-v3`), answers in Urdu script and speaks with an Urdu neural voice.
- Commands work in Urdu: "یوٹیوب کھولو", "کروم بند کرو", "آواز بڑھاؤ", "وقت کیا ہوا ہے", "لاہور کا موسم کیسا ہے",
  "یوٹیوب پر ... چلاؤ", "اسکرین شاٹ لو", "پانچ منٹ کا ٹائمر لگاؤ", "حسنات کو واٹس ایپ پر میسج کرو کہ ..." (still asks for
  your "ہاں" before sending). Anything it has no rule for is answered by the AI in Urdu.
- Wake word in Urdu: "جارویس". Stop: "رکو" / "بس". Exit: "جارویس بند ہو جاؤ" / "خدا حافظ".
- Needs internet for the Urdu voice (Microsoft Edge neural voices) and a Groq key for good Urdu recognition and for
  translating replies that have no ready-made Urdu phrase.

**News.** Free Google News feeds, no key. Say (or in Urdu: "پاکستان کی تازہ خبریں"):
- "what are the breaking news of Pakistan" / "news from India" / "headlines of Iran" - any country
- "tell me the breaking news from the global world" / "world news" - global headlines
- "geopolitics news" / "latest geopolitical update on Iran" - geopolitics, optionally for one country
- "top 3 business headlines", "sports news", "technology news", "news about bitcoin"
- "daily news briefing" - home country + world + geopolitics. Set `JARVIS_DAILY_NEWS=08:00` and he reads it by himself every day.
- Add "in Urdu" to hear any of them in Urdu.
