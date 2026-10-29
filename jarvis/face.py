"""The robot face: eye geometry and the blink / look / mood state machine."""
from __future__ import annotations

import math
import random
import time

N_PTS = 36


def eye_pts(cx, cy, rx, ry, op, side, angry, sad, happy, scale=1.0):
    """Polygon points of one eye. op = openness (0 closed .. 1 open), side = -1 left / +1 right."""
    pts = []
    k = min(max(op, 0.0), 1.0)
    op = max(op, 0.03)
    for i in range(N_PTS):
        th = 2 * math.pi * i / N_PTS
        c, s = math.cos(th), math.sin(th)
        sc = math.copysign(abs(c) ** 0.65, c)      # squarish rounded robot eye
        ss = math.copysign(abs(s) ** 0.65, s)
        x = cx + rx * scale * sc
        y = cy + ry * scale * op * ss
        inner = -side * c                          # +1 = side facing the nose
        if ss < 0:                                 # upper lid: angry slants, sad droops
            y += k * ry * scale * (angry * 0.95 * (inner + 1) / 2 + sad * 0.9 * (1 - inner) / 2) * (-ss)
        else:                                      # lower lid rises when happy
            y -= k * ry * scale * happy * 0.75 * ss
        pts += [x, y]
    return pts


class Face:
    def __init__(self):
        self.v = {k: 0.0 for k in ("ol", "orr", "lx", "ly", "angry", "sad", "happy")}
        self.v["ol"] = self.v["orr"] = 1.0
        self.t = dict(self.v)
        self.base = 1.0
        self.sleeping = False
        self.surprised = False
        self.next_blink = time.time() + 2.5
        self.blink_end = 0.0
        self.hold_until = 0.0
        self.roll_until = 0.0
        self.mood_until = 0.0
        self.next_wander = 0.0

    def blink(self, which="both"):
        if self.sleeping:
            return
        if which in ("both", "left"):
            self.t["ol"] = 0.0
        if which in ("both", "right"):
            self.t["orr"] = 0.0
        self.blink_end = time.time() + (0.16 if which == "both" else 0.7)

    def look(self, x, y, secs=5.0):
        self.t["lx"], self.t["ly"] = x, y
        self.hold_until = time.time() + secs

    def roll(self, secs=2.5):
        self.roll_until = time.time() + secs

    def reset_mood(self):
        self.t["angry"] = self.t["sad"] = self.t["happy"] = 0.0
        self.base = 1.0
        self.surprised = False
        self.mood_until = 0.0
        if not self.sleeping:
            self.t["ol"] = self.t["orr"] = 1.0

    def mood(self, name, secs=9.0):
        self.reset_mood()
        if name == "angry":
            self.t["angry"] = 1.0
        elif name == "sad":
            self.t["sad"] = 1.0
        elif name == "happy":
            self.t["happy"] = 1.0
        elif name == "surprised":
            self.base = 1.3
            self.surprised = True
            self.t["ol"] = self.t["orr"] = 1.3
        self.mood_until = time.time() + secs

    def sleep(self, on):
        self.sleeping = on
        if on:
            self.reset_mood()
        else:
            self.t["ol"] = self.t["orr"] = self.base
            self.next_blink = time.time() + 3

    def update(self, now, state):
        t = self.t
        if self.sleeping:
            t["ol"] = t["orr"] = 0.04
            t["lx"] = t["ly"] = 0.0
        else:
            if self.blink_end and now > self.blink_end:
                t["ol"] = t["orr"] = self.base
                self.blink_end = 0.0
                self.next_blink = now + random.uniform(2.5, 6.0)
            elif not self.blink_end and now > self.next_blink:
                self.blink()
            if self.mood_until and now > self.mood_until:
                self.reset_mood()
            if now < self.roll_until:
                a = now * 7
                t["lx"], t["ly"] = math.cos(a), math.sin(a)
            elif now > self.hold_until:
                if state == "thinking":
                    t["lx"], t["ly"] = 0.7, -0.6
                elif now > self.next_wander:
                    t["lx"] = random.uniform(-0.6, 0.6)
                    t["ly"] = random.uniform(-0.4, 0.4)
                    if random.random() < 0.4:
                        t["lx"] = t["ly"] = 0.0
                    self.next_wander = now + random.uniform(1.5, 3.5)
        for k in self.v:
            rate = 0.45 if k in ("ol", "orr") else 0.2
            self.v[k] += (t[k] - self.v[k]) * rate
