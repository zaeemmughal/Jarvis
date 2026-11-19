"""A small read-only reading panel for reports and briefings (opened by the HUD on a "panel" event).
Everything is guarded: if Tk is unavailable or anything fails, the text is still in the transcript."""
from __future__ import annotations

import logging

log = logging.getLogger("jarvis.panel")
_win = {"top": None, "text": None}


def show(root, title: str, text: str) -> None:
    try:
        import tkinter as tk
        top = _win["top"]
        if top is None or not top.winfo_exists():
            top = tk.Toplevel(root)
            top.geometry("620x520")
            top.configure(bg="#050d16")
            box = tk.Text(top, wrap="word", bg="#07131f", fg="#bfe9ff", insertbackground="#bfe9ff", relief="flat",
                          font=("Segoe UI", 11), padx=14, pady=12)
            box.pack(fill="both", expand=True)
            _win["top"], _win["text"] = top, box
        top.title("J.A.R.V.I.S - " + title[:60])
        box = _win["text"]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", title + "\n\n", "h")
        box.tag_configure("h", foreground="#00e5ff", font=("Segoe UI", 14, "bold"))
        box.insert("end", text.replace("## ", ""))
        box.configure(state="disabled")
        top.lift()
    except Exception:
        log.exception("panel failed")
