"""Meetings and how they are kept on disk.

Every meeting lives in exactly two files, both rewritten in place on each save:

    <folder>/.scribe/<id>.json              the data Scribe reads back
    <folder>/<date> <time> <title>.txt      a readable copy, renamed with the title

Writes go to a temporary file first and are then swapped in, so a crash or
power cut mid-save leaves the previous version intact rather than a torn file.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FORMAT_VERSION = 1

# A new paragraph starts after this much silence, or once a paragraph runs this long.
PARAGRAPH_GAP_S = 2.5
PARAGRAPH_MAX_S = 60.0


def now_local() -> datetime:
    return datetime.now().astimezone()


def format_offset(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left.rstrip()} {right.lstrip()}"


@dataclass
class Block:
    """A paragraph of the transcript: one or more phrases with no long pause between them."""

    id: int
    start: float  # seconds since the meeting started
    end: float
    text: str
    speaker: str | None = None
    closed: bool = False  # set after a manual edit so new speech starts a new paragraph

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
            "speaker": self.speaker,
            "closed": self.closed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Block:
        return cls(
            id=int(data["id"]),
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data["text"]),
            speaker=data.get("speaker"),
            closed=bool(data.get("closed", False)),
        )


@dataclass
class Session:
    id: str
    started_at: datetime
    title: str = ""
    ended_at: datetime | None = None
    blocks: list[Block] = field(default_factory=list)
    model: str = ""
    inputs: list[str] = field(default_factory=list)
    txt_name: str = ""
    dirty: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @property
    def display_title(self) -> str:
        return self.title or "Untitled meeting"

    def elapsed(self) -> float:
        end = self.ended_at or now_local()
        return max(0.0, (end - self.started_at).total_seconds())

    def add_text(self, start: float, end: float, text: str, speaker: str | None) -> Block:
        """Add newly transcribed speech, continuing the last paragraph when it flows on."""
        with self.lock:
            last = self.blocks[-1] if self.blocks else None
            if (
                last is not None
                and not last.closed
                and last.speaker == speaker
                and start - last.end < PARAGRAPH_GAP_S
                and end - last.start < PARAGRAPH_MAX_S
            ):
                last.text = _join_text(last.text, text)
                last.end = max(last.end, end)
                block = last
            else:
                next_id = (self.blocks[-1].id + 1) if self.blocks else 1
                block = Block(id=next_id, start=start, end=end, text=text, speaker=speaker)
                self.blocks.append(block)
            self.dirty = True
            return block

    def edit_block(self, block_id: int, text: str, base_text: str | None = None) -> Block:
        """Replace a paragraph's text with the user's edit.

        ``base_text`` is the text the user started editing from. If speech was
        appended to the paragraph while they were typing, that newer text is kept
        after their edit instead of being thrown away.
        """
        with self.lock:
            block = self.get_block(block_id)
            if base_text is not None and block.text != base_text and block.text.startswith(base_text):
                text = _join_text(text, block.text[len(base_text):])
            block.text = text.strip()
            block.closed = True
            self.dirty = True
            return block

    def get_block(self, block_id: int) -> Block:
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise KeyError(block_id)

    def set_title(self, title: str) -> None:
        with self.lock:
            self.title = " ".join(title.split())[:120]
            self.dirty = True

    def has_text(self) -> bool:
        return any(block.text for block in self.blocks)

    def plain_text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks if block.text)

    def word_count(self) -> int:
        return sum(len(block.text.split()) for block in self.blocks)

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "version": FORMAT_VERSION,
                "id": self.id,
                "title": self.title,
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "ended_at": self.ended_at.isoformat(timespec="seconds") if self.ended_at else None,
                "model": self.model,
                "inputs": list(self.inputs),
                "txt_name": self.txt_name,
                "blocks": [block.to_dict() for block in self.blocks],
            }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        ended = data.get("ended_at")
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(ended) if ended else None,
            model=data.get("model", ""),
            inputs=list(data.get("inputs", [])),
            txt_name=data.get("txt_name", ""),
            blocks=[Block.from_dict(b) for b in data.get("blocks", [])],
        )


def _speaker_prefix(block: Block) -> str:
    return f"{block.speaker}: " if block.speaker else ""


def _date_line(session: Session) -> str:
    start = session.started_at
    line = f"{start:%A} {start.day} {start:%B %Y}, {start:%H:%M}"
    if session.ended_at:
        minutes = round(session.elapsed() / 60)
        line += f" to {session.ended_at:%H:%M} ({minutes} min)"
    else:
        line += " (in progress)"
    return line


def render_text(session: Session) -> str:
    with session.lock:
        lines = [session.display_title, _date_line(session), ""]
        for block in session.blocks:
            if not block.text:
                continue
            lines.append(f"[{format_offset(block.start)}]  {_speaker_prefix(block)}{block.text}")
            lines.append("")
        return "\n".join(lines)


def render_markdown(session: Session) -> str:
    with session.lock:
        lines = [f"# {session.display_title}", "", f"*{_date_line(session)}*", ""]
        for block in session.blocks:
            if not block.text:
                continue
            speaker = f"**{block.speaker}:** " if block.speaker else ""
            lines.append(f"`{format_offset(block.start)}` {speaker}{block.text}")
            lines.append("")
        return "\n".join(lines)


_UNSAFE_FILENAME = re.compile(r'[/\\:*?"<>|\x00-\x1f]+')


def _safe_filename(text: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub(" ", text)
    cleaned = " ".join(cleaned.split()).strip(". ")
    return cleaned[:80].rstrip(". ")


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class SessionStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self.data_dir = folder / ".scribe"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._summaries: dict[Path, tuple[float, dict, str]] = {}
        self._ids_in_use: set[str] = set()

    def _json_path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[0-9A-Za-z-]+", session_id):
            raise KeyError(session_id)
        return self.data_dir / f"{session_id}.json"

    def create(self, title: str = "", model: str = "", inputs: list[str] | None = None) -> Session:
        started = now_local()
        with self._lock:
            base = started.strftime("%Y%m%d-%H%M%S")
            session_id, n = base, 2
            while session_id in self._ids_in_use or self._json_path(session_id).exists():
                session_id, n = f"{base}-{n}", n + 1
            self._ids_in_use.add(session_id)
        session = Session(id=session_id, started_at=started, model=model, inputs=list(inputs or []))
        session.set_title(title)
        return session

    def save(self, session: Session) -> Path | None:
        """Write the meeting to its two files and return the readable one's path.

        A meeting with nothing transcribed yet isn't written, so starting and
        stopping without anyone speaking leaves no empty files behind.
        """
        with self._lock:
            if not session.has_text() and not session.txt_name:
                session.dirty = False
                return None
            return self._save_locked(session)

    def discard(self, session: Session) -> None:
        """Remove a meeting's files, used for meetings in which nothing was said."""
        with self._lock:
            paths = [self._json_path(session.id)]
            if session.txt_name:
                paths.append(self.folder / session.txt_name)
            for path in paths:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            session.txt_name = ""
            session.dirty = False

    def trash(self, session: Session) -> None:
        """Delete a meeting by moving its files to the system Trash, so it can be recovered."""
        with self._lock:
            paths = [p for p in self._paths(session) if p.exists()]
            if paths and shutil.which("gio"):
                result = subprocess.run(["gio", "trash", *map(str, paths)], capture_output=True, timeout=10, check=False)
                paths = [p for p in paths if p.exists()] if result.returncode else []
            if paths:
                # No desktop Trash available: keep the files in a folder of our own instead.
                keep = self.data_dir / "deleted"
                keep.mkdir(exist_ok=True)
                for path in paths:
                    path.replace(keep / path.name)
            session.txt_name = ""
            session.dirty = False

    def _paths(self, session: Session) -> list[Path]:
        paths = [self._json_path(session.id)]
        if session.txt_name:
            paths.append(self.folder / session.txt_name)
        return paths

    def _save_locked(self, session: Session) -> Path:
        with session.lock:
            session.dirty = False
            old_name = session.txt_name
            new_name = self._txt_name_for(session)
            session.txt_name = new_name
            data = json.dumps(session.to_dict(), ensure_ascii=False, indent=1)
            text = render_text(session)
        try:
            write_atomic(self.folder / new_name, text)
            write_atomic(self._json_path(session.id), data)
        except BaseException:
            with session.lock:
                session.dirty = True
                session.txt_name = old_name
            raise
        if old_name and old_name != new_name:
            with contextlib.suppress(FileNotFoundError):
                (self.folder / old_name).unlink()
        return self.folder / new_name

    def _txt_name_for(self, session: Session) -> str:
        stem = f"{session.started_at:%Y-%m-%d %H.%M} {_safe_filename(session.title) or 'Meeting'}"
        candidate, n = f"{stem}.txt", 2
        # Another meeting may already own this name (same minute, same title).
        while candidate != session.txt_name and (self.folder / candidate).exists():
            candidate, n = f"{stem} ({n}).txt", n + 1
        return candidate

    def load(self, session_id: str) -> Session:
        path = self._json_path(session_id)
        try:
            return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise KeyError(session_id) from None

    def list_meetings(self, query: str = "") -> list[dict]:
        """Summaries of every saved meeting, newest first, optionally filtered by text."""
        needle = query.strip().lower()
        results = []
        with self._lock:
            paths = sorted(self.data_dir.glob("*.json"), reverse=True)
            for stale in set(self._summaries) - set(paths):
                del self._summaries[stale]
            for path in paths:
                entry = self._summary(path)
                if entry is None:
                    continue
                summary, haystack = entry
                if needle and needle not in haystack:
                    continue
                results.append(summary)
        # Newest first by when the meeting started (ISO timestamps sort as text).
        results.sort(key=lambda m: m["started_at"], reverse=True)
        return results

    def _summary(self, path: Path) -> tuple[dict, str] | None:
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        cached = self._summaries.get(path)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        try:
            session = Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None
        summary = summarize(session)
        haystack = f"{session.title}\n{session.plain_text()}".lower()
        self._summaries[path] = (mtime, summary, haystack)
        return summary, haystack


def summarize(session: Session) -> dict:
    with session.lock:
        last_end = session.blocks[-1].end if session.blocks else 0.0
        return {
            "id": session.id,
            "title": session.title,
            "started_at": session.started_at.isoformat(timespec="seconds"),
            "ended_at": session.ended_at.isoformat(timespec="seconds") if session.ended_at else None,
            "duration": round(session.elapsed() if session.ended_at else last_end),
            "words": session.word_count(),
            "txt_name": session.txt_name,
            # Untitled meetings are listed by their first words, so they can be told apart.
            "preview": " ".join(session.plain_text().split()[:12]),
        }
