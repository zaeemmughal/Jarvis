"""Keyboard / volume / lock / screenshot control for Windows using plain ctypes.

This replaces pyautogui (whose dependency chain is a pain to install on new Python versions).
Structure sizes are fixed-width so the INPUT layout is identical on every platform (40 bytes on 64-bit).
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from typing import Callable

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000

VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "playpause": 0xB3,
    "plus": 0xBB, "minus": 0xBD, "pgup": 0x21, "pgdn": 0x22,
}
for _i in range(1, 13):
    VK["f%d" % _i] = 0x6F + _i
EXTENDED = set(range(0x21, 0x29)) | {0x2D, 0x2E, 0x5B}

KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
u16, u32, i32, usz = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32, ctypes.c_size_t


class _KI(ctypes.Structure):
    _fields_ = [("wVk", u16), ("wScan", u16), ("dwFlags", u32), ("time", u32), ("dwExtraInfo", usz)]


class _MI(ctypes.Structure):
    _fields_ = [("dx", i32), ("dy", i32), ("mouseData", u32), ("dwFlags", u32), ("time", u32), ("dwExtraInfo", usz)]


class _HI(ctypes.Structure):
    _fields_ = [("uMsg", u32), ("wParamL", u16), ("wParamH", u16)]


class _U(ctypes.Union):
    _fields_ = [("ki", _KI), ("mi", _MI), ("hi", _HI)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", u32), ("u", _U)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", i32), ("y", i32)]


def supported() -> bool:
    return IS_WIN


def _send(vk: int = 0, scan: int = 0, flags: int = 0) -> None:
    inp = INPUT()
    inp.type = 1
    inp.u.ki = _KI(vk, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _key(vk: int, up: bool) -> None:
    flags = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    _send(vk, 0, flags)


def _vk(name: str) -> int:
    name = name.lower()
    if name in VK:
        return VK[name]
    if len(name) == 1:
        return ord(name.upper())
    raise KeyError(name)


def mouse_in_corner() -> bool:
    """Fail-safe: slam the mouse into the top-left corner to abort typing."""
    if not IS_WIN:
        return False
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x <= 0 and pt.y <= 0


def press(name: str) -> None:
    vk = _vk(name)
    _key(vk, False)
    _key(vk, True)


def hotkey(*names: str) -> None:
    codes = [_vk(n) for n in names]
    for c in codes:
        _key(c, False)
    for c in reversed(codes):
        _key(c, True)


def type_text(text: str, abort: Callable[[], bool] = lambda: False, delay: float = 0.03) -> bool:
    """Type any unicode text into the focused window. Returns False if aborted."""
    data = text.encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    for u in units:
        if abort() or mouse_in_corner():
            return False
        if u in (10, 13):
            press("enter")
        else:
            _send(0, u, KEYEVENTF_UNICODE)
            _send(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(delay)
    return True


def lock_screen() -> None:
    ctypes.windll.user32.LockWorkStation()


def screenshot(path: str) -> bool:
    ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
          "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
          "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
          "$g=[System.Drawing.Graphics]::FromImage($bmp);"
          "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
          "$bmp.Save($env:JARVIS_SHOT)")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=25, creationflags=CREATE_NO_WINDOW,
                       env=dict(os.environ, JARVIS_SHOT=path), capture_output=True)
        return os.path.isfile(path)
    except Exception:
        return False


# ---------------------------------------------------------------------------- what is in front of the user
def foreground_info():
    """(window title, process exe name) of the window the user is looking at, or None. Windows only."""
    if not IS_WIN:
        return None
    try:
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return None
        buf = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                size = wintypes.DWORD(520)
                path = ctypes.create_unicode_buffer(520)
                if k32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
                    exe = os.path.basename(path.value)
            finally:
                k32.CloseHandle(h)
        return title, exe
    except Exception:
        return None


def chime(freq: int = 880, ms: int = 70) -> None:
    """Tiny 'I heard you' beep (Windows only, silently ignored elsewhere)."""
    if not IS_WIN:
        return
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass
