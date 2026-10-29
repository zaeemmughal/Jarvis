"""The HUD: animated face, rotating rings, live mic waveform, system gauges, weather, timers and a transcript."""
from __future__ import annotations

import math
import queue
import random
import time
import tkinter as tk
from collections import deque

from .face import eye_pts

BG, PANEL = "#05080f", "#070f1b"
CYAN, GLOW, DIM, GREEN, AMBER, RED = "#00e5ff", "#08344a", "#0b2236", "#00ff9c", "#ffb300", "#ff3d3d"
SOFT, MUTE, GRID = "#7fdcff", "#4a6a80", "#08121f"
N_BARS = 31
MONO = ("Consolas", 10)

STATE_STYLE = {   # state -> (label, colour)
    "speaking": ("SPEAKING", CYAN), "thinking": ("PROCESSING", AMBER), "listening": ("LISTENING", GREEN),
    "active": ("ACTIVE", GREEN), "standby": ("STANDBY  -  SAY \"JARVIS\"", "#3fa9c9"),
    "mic_off": ("MIC OFFLINE", MUTE),
}


class Gauge:
    """Label + bar + value drawn on the canvas."""

    def __init__(self, c: tk.Canvas, label: str):
        self.c = c
        self.lbl = c.create_text(0, 0, text=label, fill=MUTE, font=(MONO[0], 9, "bold"), anchor="w")
        self.bg = c.create_rectangle(0, 0, 1, 1, fill="#0a1a2a", outline="#12324a")
        self.fill = c.create_rectangle(0, 0, 1, 1, fill=CYAN, outline="")
        self.val = c.create_text(0, 0, text="--", fill=SOFT, font=(MONO[0], 9), anchor="e")
        self.geo = None

    def place(self, x, y, w):
        if self.geo == (x, y, w):
            return
        self.geo = (x, y, w)
        c = self.c
        c.coords(self.lbl, x, y)
        c.coords(self.val, x + w, y)
        c.coords(self.bg, x, y + 9, x + w, y + 17)

    def set(self, frac, text, color=CYAN):
        x, y, w = self.geo
        frac = 0.0 if frac is None else min(max(frac, 0), 1)
        self.c.coords(self.fill, x + 1, y + 10, x + 1 + (w - 2) * frac, y + 16)
        self.c.itemconfigure(self.fill, fill=color)
        self.c.itemconfigure(self.val, text=text)


class HUD:
    def __init__(self, app, cfg):
        self.app, self.cfg, self.face = app, cfg, app.face
        self.q: queue.Queue = queue.Queue()
        self.cache: dict = {}
        self.size = (0, 0)
        self.fullscreen = False
        self.t0 = time.time()
        self.level_hist = deque([0.0] * N_BARS, maxlen=N_BARS)
        self.lvl = 0.0
        self.reply_full, self.reply_shown, self.reply_rate, self.reply_end, self._rt = "", 0.0, 40.0, 0.0, time.time()
        self.heard, self.heard_color = "", SOFT
        self.flash_until = 0.0
        self.stats_at = 0.0

        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.geometry("1280x760")
        self.root.minsize(900, 560)
        self.root.configure(bg=BG)
        self._build_widgets()
        self._build_scene()
        r = self.root
        r.bind("<F11>", lambda e: self.set_fullscreen(not self.fullscreen))
        r.bind("<Escape>", self._escape)
        r.bind("<Control-m>", lambda e: app.toggle_mic())
        r.bind("<Control-l>", lambda e: self.clear_log())
        self.hidden = False
        self.has_tray = False
        r.protocol("WM_DELETE_WINDOW", app.on_window_close)
        if cfg.fullscreen:
            self.set_fullscreen(True)

    # ------------------------------------------------------------------ widgets
    def _btn(self, parent, text, cmd, fg):
        b = tk.Button(parent, text=text, width=11, bg="#0a1624", fg=fg, relief="flat", bd=0, command=cmd,
                      activebackground="#12304a", activeforeground=fg, font=(MONO[0], 10, "bold"), cursor="hand2")
        b.pack(side="right", ipady=4, padx=(6, 0))
        return b

    def _build_widgets(self):
        body = tk.Frame(self.root, bg=BG)
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", side="bottom", padx=14, pady=(4, 12))
        body.pack(fill="both", expand=True)
        side = tk.Frame(body, bg=PANEL, width=340)
        side.pack(side="right", fill="y", padx=(0, 14), pady=(52, 6))
        side.pack_propagate(False)
        self.c = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.c.pack(side="left", fill="both", expand=True)

        tk.Label(side, text="TRANSCRIPT", bg=PANEL, fg=MUTE, font=(MONO[0], 9, "bold"), anchor="w").pack(
            fill="x", padx=12, pady=(10, 2))
        self.log = tk.Text(side, bg=PANEL, fg="white", wrap="word", state="disabled", bd=0, highlightthickness=0,
                           padx=12, pady=6, font=MONO, cursor="arrow", spacing3=5)
        self.log.pack(fill="both", expand=True)
        for tag, color, extra in (("you", SOFT, {}), ("jarvis", "#ffffff", {}), ("sys", MUTE, {}),
                                  ("src", GREEN, {}), ("err", RED, {}), ("who", CYAN, {"font": (MONO[0], 8, "bold")})):
            self.log.tag_configure(tag, foreground=color, **extra)

        self.entry = tk.Entry(bar, bg="#0a1624", fg=CYAN, insertbackground=CYAN, relief="flat", font=(MONO[0], 13))
        self.entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self.entry.bind("<Return>", self._on_enter)
        self.entry.focus_set()
        self.stop_btn = self._btn(bar, "STOP", self.app.stop_speaking, AMBER)
        self.wake_btn = self._btn(bar, "WAKE: ON", self.app.toggle_wake, GREEN)
        self.mic_btn = self._btn(bar, "MIC: ON", self.app.toggle_mic, GREEN)
        self.c.bind("<Button-1>", lambda e: self.entry.focus_set())

    def _build_scene(self):
        c = self.c
        n_part = 10 if self.cfg.lite else 30
        self.parts = [[random.random(), random.random(), random.uniform(0.4, 1.4),
                       c.create_oval(0, 0, 1, 1, fill=DIM, outline="")] for _ in range(n_part)]
        self.brackets = [c.create_line(0, 0, 0, 0, 0, 0, fill="#12607f", width=2) for _ in range(4)]
        self.scan = c.create_line(0, 0, 1, 0, fill="#0a2a3c")
        self.pulse = c.create_oval(0, 0, 1, 1, outline=GLOW, width=2)
        self.arcs = [[c.create_arc(0, 0, 1, 1, start=0, extent=ext, style="arc", outline=CYAN, width=w, **dash),
                      rf, sp] for rf, sp, ext, w, dash in
                     ((1.00, 0.6, 70, 2, {}), (1.07, -0.9, 40, 3, {}), (0.93, 1.3, 25, 2, {}),
                      (1.14, 0.3, 110, 1, {}), (1.22, -0.2, 359, 1, {"dash": (2, 10)}),
                      (0.80, -0.5, 359, 1, {"dash": (1, 6)}))]
        self.eyes = []
        for side in (-1, 1):
            self.eyes.append((side, c.create_polygon([0, 0, 0, 0, 0, 0], fill=GLOW, outline=""),
                              c.create_polygon([0, 0, 0, 0, 0, 0], fill=CYAN, outline=""),
                              c.create_oval(0, 0, 1, 1, fill="#021018", outline="")))
        self.bars = [c.create_rectangle(0, 0, 1, 1, fill=CYAN, outline="") for _ in range(N_BARS)]
        mk = lambda **kw: c.create_text(0, 0, **kw)
        self.t_title = mk(text="J . A . R . V . I . S", fill=CYAN, font=(MONO[0], 20, "bold"))
        self.t_sub = mk(text="JUST A RATHER VERY INTELLIGENT SYSTEM", fill=MUTE, font=(MONO[0], 8))
        self.t_clock = mk(text="", fill="#5fb8d6", font=(MONO[0], 12), anchor="w")
        self.t_state = mk(text="", fill=GREEN, font=(MONO[0], 12, "bold"), anchor="e")
        self.t_heard = mk(text="", fill=SOFT, font=(MONO[0], 12), width=700)
        self.t_reply = mk(text="", fill="white", font=(MONO[0], 15, "bold"), width=700, anchor="n")
        self.t_side = mk(text="SYSTEM", fill=MUTE, font=(MONO[0], 9, "bold"), anchor="w")
        self.g_cpu, self.g_ram, self.g_bat = Gauge(c, "CPU"), Gauge(c, "MEMORY"), Gauge(c, "BATTERY")
        self.t_net = mk(text="", fill=GREEN, font=(MONO[0], 9, "bold"), anchor="w")
        self.t_ai = mk(text="", fill=SOFT, font=(MONO[0], 9), anchor="w", width=200)
        self.t_voice = mk(text="", fill=MUTE, font=(MONO[0], 9), anchor="w", width=200)
        self.t_wx_h = mk(text="WEATHER", fill=MUTE, font=(MONO[0], 9, "bold"), anchor="w")
        self.t_wx = mk(text="", fill=SOFT, font=(MONO[0], 12), anchor="w", width=210)
        self.t_tm_h = mk(text="TIMERS", fill=MUTE, font=(MONO[0], 9, "bold"), anchor="w")
        self.t_tm = mk(text="", fill=AMBER, font=(MONO[0], 11), anchor="w", width=210)

    # ------------------------------------------------------------------ thread-safe events
    def post(self, *event):
        self.q.put(event)

    def _drain(self):
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.add_log(ev[1], ev[2])
                elif kind == "reply":                       # whole text at once (no voice)
                    self.reply_full, self.reply_shown = ev[1][-330:], 0.0
                    self.reply_rate = 48.0
                elif kind == "chunk":                       # a clip of speech just started: type it over the same time
                    text, secs = ev[1], max(float(ev[2]), 0.4)
                    now = time.time()
                    if now > self.reply_end + 1.0:          # a new answer
                        self.reply_full, self.reply_shown = text, 0.0
                    else:                                   # the next sentence of the same answer
                        self.reply_full += " " + text
                    over = len(self.reply_full) - 330
                    if over > 0:
                        self.reply_full = self.reply_full[over:]
                        self.reply_shown = max(0.0, self.reply_shown - over)
                    self.reply_rate = max(12.0, len(text) / secs * 1.12)    # a hair ahead of the voice
                    self.reply_end = now + secs
                elif kind == "heard":
                    self.heard, self.heard_color = ev[1], (MUTE if ev[2] else SOFT)
                elif kind == "clear":
                    self.clear_log()
                elif kind == "fullscreen":
                    self.set_fullscreen(ev[1])
                elif kind == "flash":
                    self.flash_until = time.time() + 2.5
                elif kind == "hide":
                    self.hide()
                elif kind == "show":
                    self.show()
                elif kind == "quit":
                    self.root.destroy()
                    return False
        except queue.Empty:
            pass
        return True

    # ------------------------------------------------------------------ actions
    def add_log(self, role: str, text: str):
        who = {"you": "YOU", "jarvis": "JARVIS", "sys": "SYS", "src": "SRC", "err": "ERR"}[role]
        self.log.configure(state="normal")
        self.log.insert("end", who + "\n", "who")
        self.log.insert("end", text + "\n", role)
        if int(self.log.index("end-1c").split(".")[0]) > 400:
            self.log.delete("1.0", "60.0")
        self.log.configure(state="disabled")
        self.log.see("end")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def set_fullscreen(self, on: bool):
        self.fullscreen = bool(on)
        self.root.attributes("-fullscreen", self.fullscreen)

    def hide(self):
        """Background mode: no window, Jarvis keeps listening. With a tray icon the window vanishes completely;
        without one it is minimised to the taskbar so you can always get it back."""
        self.hidden = True
        self.app.hidden = True
        self.root.withdraw() if self.has_tray else self.root.iconify()

    def show(self):
        self.hidden = False
        self.app.hidden = False
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.entry.focus_set()

    def _escape(self, _e):
        self.app.stop_speaking()
        if self.fullscreen:
            self.set_fullscreen(False)

    def _on_enter(self, _e):
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if text:
            self.app.submit(text, typed=True)

    def run(self):
        self.root.after(100, self.tick)
        self.root.mainloop()

    # ------------------------------------------------------------------ frame loop
    def tick(self):
        if not self._drain() or not self.app.running:
            return
        self.hidden = self.app.hidden = self.root.state() in ("withdrawn", "iconic")
        if self.hidden:                                                       # nothing to draw: save the CPU
            self.root.after(250, self.tick)
            return
        now = time.time()
        self.face.update(now, self.app.state)
        self.draw(now)
        self.root.after(int(1000 / max(self.cfg.fps, 5)), self.tick)

    def _set(self, item, **kw):
        key = tuple(sorted(kw.items()))
        if self.cache.get(item) != key:
            self.c.itemconfigure(item, **kw)
            self.cache[item] = key

    def _setw(self, widget, **kw):
        key = tuple(sorted(kw.items()))
        if self.cache.get(id(widget)) != key:
            widget.configure(**kw)
            self.cache[id(widget)] = key

    def _layout(self, W, H):
        c = self.c
        c.delete("grid")
        for x in range(0, W, 48):
            c.create_line(x, 0, x, H, fill=GRID, tags="grid")
        for y in range(0, H, 48):
            c.create_line(0, y, W, y, fill=GRID, tags="grid")
        c.tag_lower("grid")
        m, L = 14, 26
        for item, (sx, sy) in zip(self.brackets, ((m, m), (W - m, m), (m, H - m), (W - m, H - m))):
            dx, dy = (L if sx < W / 2 else -L), (L if sy < H / 2 else -L)
            c.coords(item, sx + dx, sy, sx, sy, sx, sy + dy)
        c.itemconfigure(self.scan, state="hidden" if self.cfg.lite else "normal")
        self.left = 250 if W >= 820 else 0
        self.cx = self.left + (W - self.left) / 2
        wrap = (W - self.left) * 0.82
        c.itemconfigure(self.t_heard, width=wrap)
        c.itemconfigure(self.t_reply, width=wrap)
        side_vis = "normal" if self.left else "hidden"
        for it in (self.t_side, self.t_net, self.t_ai, self.t_voice, self.t_wx_h, self.t_wx, self.t_tm_h, self.t_tm,
                   *[g.lbl for g in (self.g_cpu, self.g_ram, self.g_bat)],
                   *[g.bg for g in (self.g_cpu, self.g_ram, self.g_bat)],
                   *[g.fill for g in (self.g_cpu, self.g_ram, self.g_bat)],
                   *[g.val for g in (self.g_cpu, self.g_ram, self.g_bat)]):
            c.itemconfigure(it, state=side_vis)
        if self.left:
            x, w = 34, 190
            c.coords(self.t_side, x, 92)
            self.g_cpu.place(x, 118, w)
            self.g_ram.place(x, 160, w)
            self.g_bat.place(x, 202, w)
            c.coords(self.t_net, x, 256)
            c.coords(self.t_ai, x, 282)
            c.coords(self.t_voice, x, 322)
            c.coords(self.t_wx_h, x, 380)
            c.coords(self.t_wx, x, 410)
            c.coords(self.t_tm_h, x, 480)
            c.coords(self.t_tm, x, 508)

    def draw(self, now):
        c, app = self.c, self.app
        W, H = max(c.winfo_width(), 300), max(c.winfo_height(), 300)
        if (W, H) != self.size:
            self.size = (W, H)
            self._layout(W, H)
        v, st = self.face.v, app.state
        label, col = STATE_STYLE.get(st, STATE_STYLE["active"])
        boot = min(1.0, (now - self.t0) / 2.0)
        boot = 1 - (1 - boot) ** 3
        flash = now < self.flash_until and int(now * 6) % 2 == 0
        if flash:
            col = AMBER

        # audio level (real microphone while listening)
        lv = app.listener.level if st in ("listening", "active", "standby") else 0.0
        if st == "speaking":
            lv = 0.35 + 0.35 * abs(math.sin(now * 9)) * random.uniform(0.5, 1.0)
        self.lvl += (lv - self.lvl) * 0.4
        self.level_hist.append(self.lvl)

        cx0, cy = self.cx, H * 0.38
        rx = min((W - self.left) * 0.11, H * 0.15)
        ry, gap = rx * 0.95, rx * 1.75

        for p in self.parts:                                  # drifting particles
            p[1] -= 0.0007 * p[2]
            if p[1] < -0.02:
                p[1], p[0] = 1.02, random.random()
            x, y, r = p[0] * W, p[1] * H, p[2] * 2
            c.coords(p[3], x - r, y - r, x + r, y + r)

        R = min(W - self.left, H) * 0.32 * boot                # rotating HUD rings
        for item, rf, speed in self.arcs:
            r = R * rf * (1 + 0.025 * self.lvl)
            c.coords(item, cx0 - r, cy - r, cx0 + r, cy + r)
            c.itemconfigure(item, start=(now * speed * 57) % 360, outline=col)
        pr = R * 0.9 * (1 + 0.08 * self.lvl)
        c.coords(self.pulse, cx0 - pr, cy - pr, cx0 + pr, cy + pr)
        if not self.cfg.lite:
            sy = (now * 70) % H
            c.coords(self.scan, self.left, sy, W, sy)

        ecol = RED if v["angry"] > 0.5 else (GREEN if v["happy"] > 0.5 else CYAN)  # eyes
        for side, glow, eye, pupil in self.eyes:
            op = v["ol" if side == -1 else "orr"]
            ex = cx0 + side * gap + v["lx"] * rx * 0.18
            ey = cy + v["ly"] * ry * 0.15
            args = (rx, ry, op, side, v["angry"], v["sad"], v["happy"])
            c.coords(glow, *eye_pts(ex, ey, *args, scale=1.16))
            c.coords(eye, *eye_pts(ex, ey, *args))
            if self.cache.get("ecol") != ecol:
                c.itemconfigure(eye, fill=ecol)
                c.itemconfigure(glow, fill="#4a1010" if ecol == RED else ("#07402c" if ecol == GREEN else GLOW))
            k = min(max(op, 0), 1)
            prr = rx * 0.30 * k * (0.7 if self.face.surprised else 1.0)
            px, py = ex + v["lx"] * rx * 0.50, ey + v["ly"] * ry * 0.45 * k
            c.coords(pupil, px - prr, py - prr, px + prr, py + prr)
            c.itemconfigure(pupil, state="hidden" if op < 0.25 else "normal")
        self.cache["ecol"] = ecol

        by, bw = H * 0.64, max((W - self.left) * 0.009, 5)      # voice bars (mouth)
        total = N_BARS * bw * 1.8
        hist = list(self.level_hist)
        for i, bar in enumerate(self.bars):
            if st == "speaking":
                amp = 0.2 + 0.8 * abs(math.sin(now * 9 + i * 1.7)) * random.uniform(0.4, 1.0)
            elif st == "thinking":
                amp = 0.9 if int(now * 14) % N_BARS == i else 0.08
            else:
                amp = 0.05 + min(hist[i] * 3.5, 0.95)
            h = 3 + amp * 44
            x = cx0 - total / 2 + i * bw * 1.8
            c.coords(bar, x, by - h / 2, x + bw, by + h / 2)
            c.itemconfigure(bar, fill=col)

        dt, self._rt = min(0.25, max(0.0, now - self._rt)), now
        self.reply_shown = min(len(self.reply_full), self.reply_shown + self.reply_rate * dt)      # typewriter, voice-synced
        c.coords(self.t_title, cx0, 30)
        c.coords(self.t_sub, cx0, 52)
        c.coords(self.t_clock, 20, 30)
        c.coords(self.t_state, W - 20, 30)
        c.coords(self.t_heard, cx0, H * 0.745)
        c.coords(self.t_reply, cx0, H * 0.775)
        self._set(self.t_clock, text=time.strftime("%I:%M:%S %p"))
        self._set(self.t_state, text=label, fill=col)
        self._set(self.t_heard, text=self.heard, fill=self.heard_color)
        self._set(self.t_reply, text=self.reply_full[:int(self.reply_shown)])
        self._set(self.t_title, fill=col)

        if self.left and now - self.stats_at > 1.0:             # side panel
            self.stats_at = now
            s = app.stats
            cpu, ram, bat = s.get("cpu"), s.get("ram"), s.get("battery")
            hot = lambda p: RED if p > 85 else (AMBER if p > 65 else CYAN)
            self.g_cpu.set(None if cpu is None else cpu / 100, "--" if cpu is None else "%d%%" % cpu, hot(cpu or 0))
            self.g_ram.set(None if ram is None else ram / 100, "--" if ram is None else "%d%%" % ram, hot(ram or 0))
            if bat:
                self.g_bat.set(bat[0] / 100, "%d%%%s" % (bat[0], "+" if bat[1] else ""), RED if bat[0] < 20 else GREEN)
            else:
                self.g_bat.set(0, "AC", MUTE)
            self._set(self.t_net, text="NET  ONLINE" if app.online else "NET  OFFLINE", fill=GREEN if app.online else RED)
            self._set(self.t_ai, text="AI   " + app.brain.mode)
            self._set(self.t_voice, text="VOICE %s\nMIC   %s" % (app.speaker.engine, app.listener.device_name or "none")
                      )
            w = app.weather
            self._set(self.t_wx, text="%s\n%d\u00b0C  %s" % (w["city"], w["temp"], w["desc"]) if w else "--")
            tm = app.timers_left()
            self._set(self.t_tm, text="\n".join("%s  %s" % (m_ss(sec), lab) for lab, sec in tm[:3]) or "none")

        mic_on, wake_on = app.mic_on, app.wake_on
        self._setw(self.mic_btn, text="MIC: ON" if mic_on else "MIC: OFF", fg=GREEN if mic_on else RED)
        self._setw(self.wake_btn, text="WAKE: ON" if wake_on else "WAKE: OFF", fg=GREEN if wake_on else MUTE)


def m_ss(sec: float) -> str:
    sec = int(max(sec, 0))
    return "%02d:%02d" % divmod(sec, 60) if sec < 3600 else "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)
