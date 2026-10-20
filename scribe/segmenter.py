"""Turns a live audio stream into finished phrases plus a live preview.

Audio collects in a buffer while someone talks. As soon as they pause, the
buffered speech is transcribed carefully and committed, and the buffer is
emptied. While they're still talking, the buffer is transcribed quickly and
often so the preview keeps up with them. If nobody pauses for a long time, the
buffer is cut at the quietest gap so it never grows without limit.

Everything here is plain computation on numpy arrays: the transcriber and
speech detector are passed in, which keeps this testable without a model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .audio import FRAME_SAMPLES, SAMPLE_RATE
from .transcriber import Segment

TranscribeFn = Callable[..., list[Segment]]
DetectFn = Callable[[np.ndarray], list[tuple[int, int]]]


@dataclass
class SegmenterOptions:
    pause_s: float = 0.8  # silence that ends a phrase
    max_phrase_s: float = 20.0  # cut the buffer if nobody pauses for this long
    preview_interval_s: float = 0.6
    pad_s: float = 0.2  # audio kept either side of the speech when transcribing
    keep_silence_s: float = 0.5  # silence kept while waiting for speech to start


@dataclass
class Commit:
    start: float  # seconds since the stream started
    end: float
    text: str
    speaker: str | None


def _samples(seconds: float) -> int:
    return int(seconds * SAMPLE_RATE)


def _floor_frame(samples: int) -> int:
    return samples // FRAME_SAMPLES * FRAME_SAMPLES


def _ceil_frame(samples: int) -> int:
    return math.ceil(samples / FRAME_SAMPLES) * FRAME_SAMPLES


def _join(segments: list[Segment]) -> str:
    return " ".join(s.text for s in segments if s.text).strip()


class Segmenter:
    def __init__(
        self,
        transcribe: TranscribeFn,
        detect_speech: DetectFn,
        options: SegmenterOptions | None = None,
        speakers: list[str] | None = None,
        vocabulary: str = "",
    ):
        self.transcribe = transcribe
        self.detect_speech = detect_speech
        self.options = options or SegmenterOptions()
        # One label per input, used to say who spoke when there are several inputs.
        self.speakers = speakers
        self.vocabulary = vocabulary
        self.audio = np.zeros(0, dtype=np.float32)
        self.energy = np.zeros((0, len(speakers or [None])), dtype=np.float32)
        self.offset = 0  # stream position of self.audio[0], in samples
        self.context = ""  # the most recent committed text, used as a prompt
        self.preview = ""
        self._last_preview = -math.inf

    def feed(self, audio: np.ndarray, energy: np.ndarray) -> None:
        """Add audio (a whole number of frames) and its per-frame, per-input energy."""
        self.audio = np.concatenate([self.audio, audio])
        self.energy = np.concatenate([self.energy, energy]) if len(self.energy) else energy

    @property
    def buffered_seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE

    def step(self, now: float, allow_preview: bool = True) -> tuple[list[Commit], str | None]:
        """Process what's buffered.

        Returns any newly finished phrases, and the new preview text: None when
        the preview hasn't changed, "" when it should be cleared.
        """
        opts = self.options
        if len(self.audio) < 5 * FRAME_SAMPLES:
            return [], None
        speech = self.detect_speech(self.audio)
        if not speech:
            self._drop(_floor_frame(len(self.audio) - _samples(opts.keep_silence_s)))
            return [], self._set_preview("")

        # Drop silence before the speech so the buffer starts just ahead of it.
        lead = _floor_frame(speech[0][0] - _samples(opts.pad_s))
        if lead > 0:
            self._drop(lead)
            speech = [(start - lead, end - lead) for start, end in speech]

        length = len(self.audio)
        last_end = speech[-1][1]
        if length - last_end >= _samples(opts.pause_s):
            commits = self._commit(min(length, last_end + _samples(opts.pad_s)), speech)
            return commits, self._set_preview("")

        if length >= _samples(opts.max_phrase_s):
            cut = self._quietest_gap(speech)
            commits = self._commit(cut, speech) if cut else self._commit_whisper_segments(speech)
            return commits, self._set_preview("")

        if allow_preview and now - self._last_preview >= opts.preview_interval_s:
            self._last_preview = now
            segments = self.transcribe(self.audio, prompt=self._prompt(), final=False)
            return [], self._set_preview(_join(segments))
        return [], None

    def flush(self) -> list[Commit]:
        """Commit whatever speech is still buffered, e.g. when pausing or stopping."""
        commits: list[Commit] = []
        if len(self.audio) >= 3 * FRAME_SAMPLES:
            speech = self.detect_speech(self.audio)
            if speech:
                commits = self._commit(len(self.audio), speech)
        self._drop(len(self.audio))
        self.preview = ""
        return commits

    def _commit(self, cut: int, speech: list[tuple[int, int]]) -> list[Commit]:
        """Transcribe the buffer up to ``cut`` as a finished phrase, then drop it."""
        segments = self.transcribe(self.audio[:cut], prompt=self._prompt(), final=True)
        inside = [(s, min(e, cut)) for s, e in speech if s < cut]
        commit = self._make_commit(_join(segments), inside[0][0], inside[-1][1])
        self._drop(min(len(self.audio), _ceil_frame(cut)))
        return [commit] if commit else []

    def _commit_whisper_segments(self, speech: list[tuple[int, int]]) -> list[Commit]:
        """Continuous speech with no gap to cut at: let Whisper's own segments decide.

        Everything but the last segment is committed; the last one may be a
        sentence still in progress, so its audio stays in the buffer.
        """
        segments = self.transcribe(self.audio, prompt=self._prompt(), final=True, timestamps=True)
        if len(segments) < 2:
            commit = self._make_commit(_join(segments), speech[0][0], len(self.audio))
            self._drop(len(self.audio))
        else:
            cut = _floor_frame(int(segments[-1].start * SAMPLE_RATE))
            commit = self._make_commit(_join(segments[:-1]), speech[0][0], cut)
            self._drop(cut)
        return [commit] if commit else []

    def _quietest_gap(self, speech: list[tuple[int, int]]) -> int:
        """Middle of the longest pause between speech regions, or 0 if there isn't one."""
        gaps = [(speech[i + 1][0] - speech[i][1], i) for i in range(len(speech) - 1)]
        gaps = [(size, i) for size, i in gaps if size > 0]
        if not gaps:
            return 0
        _, i = max(gaps)
        return _floor_frame((speech[i][1] + speech[i + 1][0]) // 2)

    def _make_commit(self, text: str, start: int, end: int) -> Commit | None:
        if not text:
            return None
        self.context = f"{self.context} {text}"[-400:]
        return Commit(
            start=(self.offset + start) / SAMPLE_RATE,
            end=(self.offset + end) / SAMPLE_RATE,
            text=text,
            speaker=self._speaker(start, end),
        )

    def _speaker(self, start: int, end: int) -> str | None:
        if not self.speakers or len(self.speakers) < 2:
            return None
        frames = self.energy[start // FRAME_SAMPLES : max(start // FRAME_SAMPLES + 1, _ceil_frame(end) // FRAME_SAMPLES)]
        if len(frames) == 0:
            return None
        return self.speakers[int(np.argmax(frames.mean(axis=0)))]

    def _prompt(self) -> str:
        parts = []
        if self.vocabulary:
            parts.append(f"Names and terms: {self.vocabulary}.")
        if self.context:
            # Start the context at a word boundary.
            context = self.context.strip()
            if len(context) >= 400 and " " in context:
                context = context.split(" ", 1)[1]
            parts.append(context)
        return " ".join(parts)

    def _drop(self, samples: int) -> None:
        samples = _floor_frame(max(0, min(samples, len(self.audio))))
        if samples == 0:
            return
        self.audio = self.audio[samples:]
        self.energy = self.energy[samples // FRAME_SAMPLES :]
        self.offset += samples

    def _set_preview(self, text: str) -> str | None:
        if text == self.preview:
            return None
        self.preview = text
        return text
