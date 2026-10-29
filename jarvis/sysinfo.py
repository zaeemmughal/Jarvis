"""CPU / RAM / battery readings for the HUD. Uses psutil if present, otherwise ctypes or /proc."""
from __future__ import annotations

import ctypes
import os
import sys
import time

try:
    import psutil  # optional
except Exception:  # pragma: no cover
    psutil = None

IS_WIN = os.name == "nt"


class SysMonitor:
    def __init__(self):
        self._prev = None
        self.started = time.time()
        if psutil:
            psutil.cpu_percent(None)

    # ---- windows (ctypes) -----------------------------------------------------
    def _win_cpu(self):
        class FT(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]
        idle, kern, user = FT(), FT(), FT()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        val = lambda f: (f.hi << 32) | f.lo
        cur = (val(idle), val(kern) + val(user))
        pct = None
        if self._prev:
            di, dt = cur[0] - self._prev[0], cur[1] - self._prev[1]
            pct = max(0.0, min(100.0, 100.0 * (1 - di / dt))) if dt > 0 else None
        self._prev = cur
        return pct

    def _win_ram(self):
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                        ("ullAvailExtendedVirtual", ctypes.c_uint64)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return float(ms.dwMemoryLoad)

    def _win_battery(self):
        class SPS(ctypes.Structure):
            _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte),
                        ("sys", ctypes.c_ubyte), ("life", ctypes.c_uint32), ("full", ctypes.c_uint32)]
        s = SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) or s.pct > 100 or s.flag == 128:
            return None
        return int(s.pct), s.ac == 1

    # ---- linux ---------------------------------------------------------------
    def _lin_cpu(self):
        try:
            with open("/proc/stat") as fh:
                p = [int(x) for x in fh.readline().split()[1:]]
        except OSError:
            return None
        idle, total = p[3] + p[4], sum(p)
        pct = None
        if self._prev and total > self._prev[1]:
            pct = 100.0 * (1 - (idle - self._prev[0]) / (total - self._prev[1]))
        self._prev = (idle, total)
        return pct

    def _lin_ram(self):
        try:
            m = {}
            with open("/proc/meminfo") as fh:
                for ln in fh:
                    k, v = ln.split(":")
                    m[k] = int(v.split()[0])
            return 100.0 * (1 - m["MemAvailable"] / m["MemTotal"])
        except Exception:
            return None

    def poll(self) -> dict:
        out = {"cpu": None, "ram": None, "battery": None, "uptime": time.time() - self.started}
        try:
            if psutil:
                out["cpu"] = psutil.cpu_percent(None)
                out["ram"] = psutil.virtual_memory().percent
                b = psutil.sensors_battery()
                out["battery"] = (int(b.percent), bool(b.power_plugged)) if b else None
            elif IS_WIN:
                out["cpu"], out["ram"], out["battery"] = self._win_cpu(), self._win_ram(), self._win_battery()
            elif sys.platform.startswith("linux"):
                out["cpu"], out["ram"] = self._lin_cpu(), self._lin_ram()
        except Exception:
            pass
        return out
