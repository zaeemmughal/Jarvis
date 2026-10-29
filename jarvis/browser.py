"""Open websites in the browser you choose (Google Chrome by default), not whatever Windows thinks is the default.

    open_url("https://www.instagram.com")          -> new tab in Chrome
    open_url(url, incognito=True)                  -> private window

Chrome is looked for in the registry, Program Files, and LocalAppData. If it cannot be found (or JARVIS_BROWSER=default)
the normal system browser is used, so a website command never silently does nothing.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import webbrowser

log = logging.getLogger("jarvis.browser")
IS_WIN = os.name == "nt"
NOWIN = 0x08000000 if IS_WIN else 0

# name -> (exe name, registry App Paths name, incognito flag, typical install paths on Windows)
_BROWSERS = {
    "chrome": ("chrome.exe", "chrome.exe", "--incognito",
               [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe"]),
    "edge": ("msedge.exe", "msedge.exe", "--inprivate",
             [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
              r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"]),
    "firefox": ("firefox.exe", "firefox.exe", "-private-window",
                [r"%ProgramFiles%\Mozilla Firefox\firefox.exe", r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"]),
    "brave": ("brave.exe", "brave.exe", "--incognito",
              [r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
               r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"]),
}
_MAC = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "firefox": "Firefox", "brave": "Brave Browser"}
_LINUX = {"chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
          "edge": ("microsoft-edge",), "firefox": ("firefox",), "brave": ("brave-browser",)}

_preferred = "chrome"
_cache: dict = {}


def set_preferred(name: str) -> None:
    global _preferred
    _preferred = (name or "chrome").lower()
    _cache.clear()


def find(name: str | None = None) -> str | None:
    """Full path of the browser executable (or a launcher name on macOS/Linux), None if not installed."""
    name = (name or _preferred).lower()
    if name in _cache:
        return _cache[name]
    found = None
    spec = _BROWSERS.get(name)
    if spec:
        if IS_WIN:
            try:
                import winreg
                for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + spec[1]) as k:
                            p = winreg.QueryValue(k, None)
                            if p and os.path.isfile(p):
                                found = p
                                break
                    except OSError:
                        continue
            except ImportError:
                pass
            for raw in spec[3]:
                if found:
                    break
                p = os.path.expandvars(raw)
                if os.path.isfile(p):
                    found = p
        elif sys.platform == "darwin":
            found = _MAC.get(name) if os.path.isdir("/Applications/%s.app" % _MAC.get(name, "?")) else None
        else:
            found = next((shutil.which(x) for x in _LINUX.get(name, ()) if shutil.which(x)), None)
        found = found or shutil.which(spec[0])
    _cache[name] = found
    return found


def name() -> str:
    """Human name of what open_url will use, for the HUD / --check."""
    if _preferred in ("default", "system", ""):
        return "system default browser"
    return _preferred.title() if find() else "system default browser (%s not found)" % _preferred.title()


def open_url(url: str, incognito: bool = False, new_window: bool = False) -> bool:
    """Open `url`. Returns True when the chosen browser was used, False when the system default had to do it."""
    path = None if _preferred in ("default", "system", "") else find()
    if path:
        try:
            if sys.platform == "darwin" and not os.path.isabs(path):
                cmd = ["open", "-a", path]
                if incognito and _preferred in ("chrome", "brave", "edge"):
                    cmd += ["--args", "--incognito", url]
                else:
                    cmd.append(url)
                subprocess.Popen(cmd)
            else:
                cmd = [path]
                if incognito:
                    cmd.append(_BROWSERS[_preferred][2])
                elif new_window:
                    cmd.append("--new-window" if _preferred != "firefox" else "-new-window")
                cmd.append(url)
                subprocess.Popen(cmd, creationflags=NOWIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            log.warning("could not start %s (%s), using the default browser", path, e)
    webbrowser.open(url)
    return False
