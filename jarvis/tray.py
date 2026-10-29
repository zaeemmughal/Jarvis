"""Optional system-tray icon (needs `pip install pystray pillow`). Lets Jarvis live with no window at all.

Without these packages everything still works: hiding the window just minimises it to the taskbar.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("jarvis.tray")


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    @staticmethod
    def available() -> bool:
        try:
            import PIL.Image  # noqa: F401
            import pystray  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return False
        try:
            img = Image.new("RGBA", (64, 64), (5, 8, 15, 255))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 6, 58, 58), outline=(0, 229, 255, 255), width=5)
            d.ellipse((24, 24, 40, 40), fill=(0, 229, 255, 255))
            app = self.app
            menu = pystray.Menu(
                pystray.MenuItem("Show Jarvis", lambda icon, item: app.show_window(), default=True),
                pystray.MenuItem("Hide window", lambda icon, item: app.hide_window()),
                pystray.MenuItem("Microphone on", lambda icon, item: app.toggle_mic(),
                                 checked=lambda item: app.mic_on),
                pystray.MenuItem("Stop talking", lambda icon, item: app.stop_speaking()),
                pystray.MenuItem("Quit Jarvis", lambda icon, item: app.quit()))
            self.icon = pystray.Icon("jarvis", img, "J.A.R.V.I.S - listening", menu)
            threading.Thread(target=self.icon.run, daemon=True, name="tray").start()
            return True
        except Exception as e:
            log.warning("tray failed: %s", e)
            self.icon = None
            return False

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
