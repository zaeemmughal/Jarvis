#!/usr/bin/env python3
"""J.A.R.V.I.S launcher.

    python jarvis.py                  normal start (window + voice)
    python jarvis.py --background     start with no window: voice only, tray icon if pystray is installed
    python jarvis.py --autostart on   start Jarvis in the background every time you log in to Windows (off = undo)
    python jarvis.py --devices        list microphones
    python jarvis.py --selftest       check the command router (no audio, no window)
    python jarvis.py --check          check your .env: Groq key, Chrome, voice, microphone
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart(mode: str) -> None:
    if os.name != "nt":
        print("--autostart is only available on Windows.")
        return
    import winreg
    here = os.path.abspath(__file__)
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")          # pythonw = no console window
    if os.path.isfile(pyw):
        exe = pyw
    cmd = '"%s" "%s" --background' % (exe, here)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if mode == "on":
            winreg.SetValueEx(key, "Jarvis", 0, winreg.REG_SZ, cmd)
            print("Jarvis will now start in the background when you log in.\n  " + cmd)
        else:
            try:
                winreg.DeleteValue(key, "Jarvis")
            except FileNotFoundError:
                pass
            print("Jarvis will no longer start automatically.")


def check(cfg) -> None:
    """Print what Jarvis can see: keys, models, browser, voice, microphone."""
    from jarvis import browser, net
    from jarvis.brain import Brain, nice_error
    from jarvis.memory import Memory
    ok = lambda b: "OK " if b else "-- "
    print("Browser     :", ok(browser.find(cfg.browser) or cfg.browser == "default"), browser.name(),
          "(%s)" % (browser.find(cfg.browser) or "not found"))
    print("Online      :", ok(net.is_online()), "yes" if net.is_online() else "NO INTERNET")
    for name, key in (("Groq", cfg.groq_key), ("Grok/xAI", cfg.xai_key), ("OpenRouter", cfg.openrouter_key)):
        print("%-12s:" % (name + " key"), ok(bool(key)), ("set (%s...)" % key[:6]) if key else "not set")
    b = Brain(cfg, Memory())
    b.on_status = lambda k, m: print("   ", m)
    print("AI brain    :", b.check())
    for p in b.providers:
        if p.key and p.ranked:
            try:
                print("   %s test reply: %s" % (p.name, b.parse_reply(p.chat([{"role": "user", "content": "Say hi in five words."}], 0.5, 40, 15)).text))
            except net.NetError as e:
                print("   %s FAILED: %s" % (p.name, nice_error(e)))
    from jarvis.tts import Speaker
    print("Voice       :", Speaker(cfg).engine)
    print("Speech input:", "Groq Whisper (%s)" % cfg.stt_model if cfg.groq_key and cfg.stt != "google" else "Google")
    from jarvis.audio import list_devices
    print("Microphones :\n" + list_devices())


def main():
    from jarvis.config import Config
    if "--check" in sys.argv:
        check(Config.load())
        return
    if "--devices" in sys.argv:
        from jarvis.audio import list_devices
        print(list_devices())
        return
    if "--autostart" in sys.argv:
        i = sys.argv.index("--autostart")
        autostart(sys.argv[i + 1].lower() if i + 1 < len(sys.argv) else "on")
        return
    from jarvis.app import Jarvis, setup_logging
    setup_logging()
    cfg = Config.load()
    if "--background" in sys.argv:
        cfg.background = True
    if "--selftest" in sys.argv:
        app = Jarvis(cfg, headless=True)
        app.selftest(["jarvis what time is it", "blink twice", "set a timer for 5 minutes", "what is 12 times 7",
                      "take a note buy milk", "remind me to stretch in 10 minutes", "weather in lahore",
                      "open instagram", "open facebook and youtube", "open all social media", "open tiktok in incognito", "open instagrm", "who won the world cup", "cancel timers", "system status", "how many apps are installed",
                      "compose a new mail", "search karan aujla", "close it", "jarvis closed"])
        return
    Jarvis(cfg).run()


if __name__ == "__main__":
    main()
