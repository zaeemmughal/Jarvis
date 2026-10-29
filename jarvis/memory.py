"""Persistent profile + notes, and the short rolling conversation history used by the AI brain."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time

from .config import DATA_DIR


class Memory:
    def __init__(self, data_dir: str = DATA_DIR):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.profile_path = os.path.join(self.dir, "profile.json")
        self.notes_path = os.path.join(self.dir, "notes.txt")
        self.lock = threading.Lock()
        self.profile = self._load()
        self._turns: list[tuple[str, str]] = []

    # ---- profile ------------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.profile_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.profile, fh, indent=2)
            os.replace(tmp, self.profile_path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    @property
    def name(self) -> str:
        return str(self.profile.get("name", ""))

    def set_name(self, name: str) -> None:
        with self.lock:
            self.profile["name"] = name
            self._save()

    # ---- contacts (for "compose a mail to ali") -------------------------------------
    def set_contact(self, name: str, email: str) -> None:
        with self.lock:
            self.profile.setdefault("contacts", {})[name.lower()] = email
            self._save()

    def contact(self, name: str) -> str:
        book = self.profile.get("contacts", {})
        name = name.lower().strip()
        if name in book:
            return book[name]
        return next((v for k, v in book.items() if name and (name in k or k in name)), "")

    # ---- conversation -------------------------------------------------------
    def add_turn(self, role: str, text: str) -> None:
        self._turns.append((role, text))
        del self._turns[:-24]

    def turns(self, n: int = 10) -> list[tuple[str, str]]:
        return self._turns[-n:]

    def forget_conversation(self) -> None:
        self._turns.clear()

    # ---- notes --------------------------------------------------------------
    def add_note(self, text: str) -> None:
        with self.lock, open(self.notes_path, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M"), text))

    def read_notes(self, n: int = 5) -> list[str]:
        try:
            with open(self.notes_path, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return []
        return lines[-n:]

    def clear_notes(self) -> None:
        with self.lock:
            try:
                os.remove(self.notes_path)
            except OSError:
                pass
