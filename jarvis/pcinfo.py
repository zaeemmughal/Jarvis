"""Looking at (and controlling) the PC itself: installed apps, running windows, disk, network, files, power.

Windows is the main target (registry, PowerShell, shutdown.exe). The simple readers (disk, IP, uptime, file search)
also work on Linux / macOS so they can be tested anywhere. Every function fails soft: it returns None / [] and the
skill says so out loud instead of crashing.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

log = logging.getLogger("jarvis.pc")
IS_WIN = os.name == "nt"
NOWIN = 0x08000000 if IS_WIN else 0
HOME = os.path.expanduser("~")

FOLDERS = {
    "downloads": os.path.join(HOME, "Downloads"), "download": os.path.join(HOME, "Downloads"),
    "documents": os.path.join(HOME, "Documents"), "document": os.path.join(HOME, "Documents"),
    "desktop": os.path.join(HOME, "Desktop"), "pictures": os.path.join(HOME, "Pictures"),
    "photos": os.path.join(HOME, "Pictures"), "music": os.path.join(HOME, "Music"),
    "videos": os.path.join(HOME, "Videos"), "home": HOME, "user folder": HOME,
}


# ----------------------------------------------------------------------------- PowerShell helper
def ps(script: str, timeout: float = 20, **env) -> str:
    """Run a PowerShell snippet and return stdout ('' on any failure). Values passed via env are $env:NAME."""
    if not IS_WIN:
        return ""
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", full], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NOWIN,
                             env=dict(os.environ, **{k: str(v) for k, v in env.items()}))
        return res.stdout.strip()
    except Exception as e:
        log.warning("powershell failed: %s", e)
        return ""


def _json_list(text: str) -> list:
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


# ----------------------------------------------------------------------------- apps
def start_apps() -> dict:
    """Everything in the Start menu - classic programs AND Microsoft Store apps -> {name_lower: AppUserModelID}."""
    rows = _json_list(ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress", 30))
    return {str(r.get("Name", "")).strip().lower(): str(r.get("AppID", "")) for r in rows
            if isinstance(r, dict) and r.get("Name")}


_JUNK = re.compile(r"^(?:update for|security update|hotfix|kb\d+|microsoft visual c\+\+ \d{4} (?:x86|x64) (?:additional|minimum))",
                   re.I)


def registry_programs() -> list[str]:
    """Names from Windows' 'Installed apps' registry keys (what Control Panel lists)."""
    if not IS_WIN:
        return []
    try:
        import winreg
    except ImportError:
        return []
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", 0),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0)]
    names: dict[str, str] = {}
    for root, path, _ in keys:
        try:
            with winreg.OpenKey(root, path) as k:
                n = winreg.QueryInfoKey(k)[0]
                for i in range(n):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                            def val(name):
                                try:
                                    return winreg.QueryValueEx(sub, name)[0]
                                except OSError:
                                    return None
                            name = val("DisplayName")
                            if not name or val("SystemComponent") == 1 or val("ParentKeyName") or val("ReleaseType") in (
                                    "Update", "Hotfix", "Security Update") or _JUNK.match(str(name)):
                                continue
                            names.setdefault(str(name).strip().lower(), str(name).strip())
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(names.values(), key=str.lower)


def running_windows() -> list[tuple[str, str]]:
    """[(process, window title)] for every app that currently has a visible window."""
    rows = _json_list(ps("Get-Process | Where-Object {$_.MainWindowTitle} | "
                         "Select-Object ProcessName,MainWindowTitle | ConvertTo-Json -Compress", 15))
    return [(str(r.get("ProcessName", "")), str(r.get("MainWindowTitle", ""))) for r in rows if isinstance(r, dict)]


def focus_window(fragment: str) -> bool:
    out = ps("$ok=(New-Object -ComObject WScript.Shell).AppActivate($env:JV_T); if($ok){'1'}else{'0'}", 10,
             JV_T=fragment)
    return out.strip() == "1"


# ----------------------------------------------------------------------------- facts
def disk_info(path: str | None = None) -> tuple[float, float, float] | None:
    """(total, used, free) in GB for the system drive."""
    path = path or (os.environ.get("SystemDrive", "C:") + "\\" if IS_WIN else "/")
    try:
        t, u, f = shutil.disk_usage(path)
    except OSError:
        return None
    gb = 1024 ** 3
    return t / gb, u / gb, f / gb


def local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("10.255.255.255", 1))          # no packet is sent; this just picks the outgoing interface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def wifi_name() -> str | None:
    if not IS_WIN:
        return None
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=8,
                             creationflags=NOWIN).stdout
    except Exception:
        return None
    m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    return m.group(1).strip() if m else None


def uptime_secs() -> float | None:
    try:
        if IS_WIN:
            k = ctypes.windll.kernel32
            k.GetTickCount64.restype = ctypes.c_uint64
            return k.GetTickCount64() / 1000.0
        with open("/proc/uptime") as fh:
            return float(fh.read().split()[0])
    except Exception:
        return None


def os_summary() -> str:
    return "%s %s on %s" % (platform.system(), platform.release(), platform.node() or "this machine")


# ----------------------------------------------------------------------------- files
def find_files(query: str, limit: int = 5, secs: float = 4.0, roots: list[str] | None = None) -> list[str]:
    """Look for files whose name contains every word of `query` in the usual user folders (time-boxed)."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w]
    if not words:
        return []
    roots = roots or [FOLDERS["desktop"], FOLDERS["documents"], FOLDERS["downloads"], FOLDERS["pictures"],
                      FOLDERS["music"], FOLDERS["videos"]]
    deadline, hits = time.time() + secs, []
    for root in roots:
        for dp, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in ("node_modules", "__pycache__",
                                                                                             "site-packages", "appdata")]
            for fn in files:
                low = re.sub(r"[^a-z0-9]+", " ", fn.lower())
                if all(w in low for w in words):
                    hits.append(os.path.join(dp, fn))
            if time.time() > deadline:
                break
        if time.time() > deadline:
            break

    def mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    return sorted(hits, key=mtime, reverse=True)[:limit]


# ----------------------------------------------------------------------------- power / display
POWER = {
    "shutdown": (["shutdown", "/s", "/t", "5"], "Shutting down the computer."),
    "restart": (["shutdown", "/r", "/t", "5"], "Restarting the computer."),
    "signout": (["shutdown", "/l"], "Signing you out."),
    "sleep": (["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], "Putting the computer to sleep."),
    "hibernate": (["shutdown", "/h"], "Hibernating."),
}


def power(action: str) -> str:
    if not IS_WIN:
        return "Power commands are only supported on Windows."
    cmd, msg = POWER[action]
    try:
        subprocess.Popen(cmd, creationflags=NOWIN)
        return msg
    except Exception:
        return "That didn't work."


def abort_shutdown() -> bool:
    if not IS_WIN:
        return False
    try:
        return subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=NOWIN).returncode == 0
    except Exception:
        return False


def get_brightness() -> int | None:
    out = ps("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction Stop).CurrentBrightness", 10)
    return int(out) if out.strip().isdigit() else None


def set_brightness(pct: int) -> bool:
    pct = max(0, min(100, int(pct)))
    out = ps("try{(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop)"
             ".WmiSetBrightness(1,[int]$env:JV_N);'1'}catch{'0'}", 10, JV_N=pct)
    return out.strip() == "1"


def fmt_uptime(sec: float) -> str:
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append("%d day%s" % (d, "" if d == 1 else "s"))
    if h:
        parts.append("%d hour%s" % (h, "" if h == 1 else "s"))
    if m or not parts:
        parts.append("%d minute%s" % (m, "" if m == 1 else "s"))
    return " ".join(parts)
