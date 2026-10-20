"""Choices that persist between runs: which inputs to record, and the vocabulary."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .sessions import write_atomic

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "scribe"

DEFAULTS = {
    # "default" follows the system's default device, "off" disables the input,
    # anything else is a PipeWire/PulseAudio source name.
    "microphone": "default",
    "computer_audio": "off",
    "vocabulary": "",
}


class Settings:
    def __init__(self, path: Path = CONFIG_DIR / "settings.json"):
        self.path = path
        self._lock = threading.Lock()
        self._values = dict(DEFAULTS)
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            self._values.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable settings file %s: %s", path, exc)

    def get(self, key: str) -> str:
        with self._lock:
            return self._values[key]

    def update(self, **values: str) -> None:
        with self._lock:
            self._values.update({k: v for k, v in values.items() if k in DEFAULTS})
            snapshot = dict(self._values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(snapshot, indent=2))
        except OSError as exc:
            log.warning("Couldn't save settings: %s", exc)

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._values)
