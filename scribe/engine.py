"""The recorder: runs capture and transcription for the live meeting.

All recording state changes happen on one thread, the engine thread. Other
threads (the web server, the terminal) ask for changes with ``request()``,
which queues the action and waits for the engine to carry it out.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from .audio import (
    DEFAULT_MIC,
    DEFAULT_MONITOR,
    Capture,
    default_names,
    describe,
    list_sources,
    resolve_microphone,
    source_info,
)
from .events import EventBus
from .segmenter import Commit, Segmenter, SegmenterOptions
from .sessions import Session, SessionStore, now_local
from .settings import Settings
from .transcriber import SpeechDetector, Transcriber

log = logging.getLogger(__name__)

LOADING, READY, RECORDING, PAUSED, ERROR = "loading", "ready", "recording", "paused", "error"


class UserError(Exception):
    """Something the person can fix; the message is shown to them as-is."""


class Engine:
    def __init__(
        self,
        transcriber: Transcriber,
        store: SessionStore,
        bus: EventBus,
        settings: Settings,
        autosave_s: float = 5.0,
        autostart: bool = True,
        title: str = "",
    ):
        self.transcriber = transcriber
        self.store = store
        self.bus = bus
        self.settings = settings
        self.autosave_s = autosave_s
        self.autostart = autostart
        self.initial_title = title

        self.state = LOADING
        self.message = "Loading the speech model…"
        self.session: Session | None = None
        self.capture: Capture | None = None
        self.segmenter: Segmenter | None = None
        self.detector: SpeechDetector | None = None
        self.input_error: str | None = None
        self.active_inputs: list[dict] = []  # what's being recorded right now, for the UI
        self.last_saved: str | None = None
        self.save_error: str | None = None

        self._stream_base = 0.0  # where in the meeting (seconds) the current capture began
        self._commands: queue.Queue = queue.Queue()
        self._stopping = threading.Event()
        self._save_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._ticker_thread = threading.Thread(target=self._ticker, name="ticker", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ticker_thread.start()

    # Requests from other threads ------------------------------------------------

    def request(self, action: str, timeout: float = 60.0, **kwargs):
        if self.state == LOADING and action != "shutdown":
            raise UserError("The speech model is still loading. Try again in a moment.")
        if self.state == ERROR and action != "shutdown":
            raise UserError(self.message)
        done = threading.Event()
        outcome: dict = {}
        self._commands.put((action, kwargs, done, outcome))
        if not done.wait(timeout):
            raise UserError("Scribe is busy. Try again in a moment.")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("result")

    def set_inputs(self, microphone: str, computer_audio: str) -> None:
        if self.state in (RECORDING, PAUSED):
            self.request("set_inputs", microphone=microphone, computer_audio=computer_audio)
        else:
            self.settings.update(microphone=microphone, computer_audio=computer_audio)
            self._publish_state()

    def set_vocabulary(self, text: str) -> None:
        text = " ".join(text.split())[:1000]
        self.settings.update(vocabulary=text)
        if self.segmenter is not None:
            self.segmenter.vocabulary = text

    def delete(self, session: Session) -> None:
        """Move a meeting to the Trash. The meeting being recorded has to be stopped first."""
        if session is self.session and self.state in (RECORDING, PAUSED):
            raise UserError("Stop recording before deleting this meeting.")
        self.store.trash(session)
        if session is self.session:
            self.session = None
        self.bus.publish("deleted", session_id=session.id)
        self.bus.publish("meetings_changed")

    def shutdown(self, timeout: float = 20.0) -> None:
        if self._thread.is_alive() and self.state != LOADING:
            try:
                self.request("shutdown", timeout=timeout)
            except UserError:
                log.warning("Engine didn't stop in time")
        self._stopping.set()
        if self.session is not None and self.session.dirty:
            self.save()

    # Views ----------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "message": self.message,
            "input_error": self.input_error,
            "inputs": self.active_inputs,
            "model": self.transcriber.model_name,
            "device": self.transcriber.device,
            "session": self.session_payload(self.session) if self.session else None,
            "preview": self.segmenter.preview if self.segmenter and self.state == RECORDING else "",
            "settings": self.settings.as_dict(),
            "folder": str(self.store.folder),
            "last_saved": self.last_saved,
            "save_error": self.save_error,
        }

    def session_payload(self, session: Session) -> dict:
        data = session.to_dict()
        data["live"] = session is self.session and self.state in (RECORDING, PAUSED)
        data["elapsed"] = round(session.elapsed(), 1)
        data["path"] = str(self.store.folder / session.txt_name) if session.txt_name else ""
        return data

    # Saving ---------------------------------------------------------------------

    def save(self, session: Session | None = None) -> None:
        session = session or self.session
        if session is None:
            return
        with self._save_lock:
            try:
                path = self.store.save(session)
            except OSError as exc:
                log.error("Couldn't save %s: %s", session.id, exc)
                self.save_error = f"Couldn't save the transcript: {exc.strerror or exc}"
                self.bus.publish("save_failed", session_id=session.id, message=self.save_error)
                return
        if path is None:
            return  # nothing transcribed yet, so nothing to write
        if session is self.session:
            self.last_saved = now_local().isoformat(timespec="seconds")
            self.save_error = None
        self.bus.publish("saved", session_id=session.id, at=now_local().isoformat(timespec="seconds"), path=str(path))

    # Engine thread --------------------------------------------------------------

    def _run(self) -> None:
        self.transcriber.on_status = lambda message: self._set_state(LOADING, message)
        try:
            self.transcriber.load()
            self.detector = SpeechDetector()
        except Exception as exc:  # shown to the person instead of crashing
            log.exception("Couldn't load the speech model")
            self._set_state(ERROR, f"Couldn't load the speech model: {exc}")
            self._answer_until_shutdown()
            return
        self._set_state(READY, "")
        if self.autostart:
            try:
                self._start(self.initial_title)
            except UserError as exc:
                self._set_state(READY, str(exc))

        while not self._stopping.is_set():
            self._handle_commands(wait=0.0 if self.state == RECORDING else 0.5)
            if self.state == RECORDING:
                try:
                    self._tick()
                except Exception:  # one bad chunk mustn't end the meeting
                    log.exception("Error while transcribing")

    def _answer_until_shutdown(self) -> None:
        while not self._stopping.is_set():
            try:
                action, _kwargs, done, outcome = self._commands.get(timeout=0.5)
            except queue.Empty:
                continue
            if action == "shutdown":
                self._stopping.set()
            else:
                outcome["error"] = UserError(self.message)
            done.set()

    def _handle_commands(self, wait: float) -> None:
        while True:
            try:
                action, kwargs, done, outcome = self._commands.get(timeout=wait) if wait else self._commands.get_nowait()
            except queue.Empty:
                return
            wait = 0.0
            try:
                outcome["result"] = getattr(self, f"_{action}")(**kwargs)
            except UserError as exc:
                outcome["error"] = exc
            except Exception as exc:  # reported to whoever asked, not raised on this thread
                log.exception("Action %s failed", action)
                outcome["error"] = UserError(f"Something went wrong: {exc}")
            finally:
                done.set()

    def _live_session(self) -> Session:
        """The meeting being recorded or paused; callers only run while there is one."""
        if self.session is None:
            raise RuntimeError("No meeting is open")
        return self.session

    def _tick(self) -> None:
        capture, segmenter, session = self.capture, self.segmenter, self.session
        if capture is None or segmenter is None or session is None:
            return  # not recording
        chunk = capture.read(timeout=0.2)
        if capture.error != self.input_error:
            self.input_error = capture.error
            self._publish_state()
        if chunk is None:
            return
        segmenter.feed(*chunk)
        lagging = capture.backlog_seconds() > 1.0
        commits, preview = segmenter.step(time.monotonic(), allow_preview=not lagging)
        self._apply(commits)
        if preview is not None:
            self.bus.publish("preview", session_id=session.id, text=preview)

    def _apply(self, commits: list[Commit]) -> None:
        if not commits:
            return
        session = self._live_session()
        for commit in commits:
            block = session.add_text(
                self._stream_base + commit.start,
                self._stream_base + commit.end,
                commit.text,
                commit.speaker,
            )
            self.bus.publish("block", session_id=session.id, block=block.to_dict())

    def _selected_inputs(self) -> tuple[list[str], list[str]]:
        devices, speakers = [], []
        microphone = self.settings.get("microphone")
        computer = self.settings.get("computer_audio")
        if microphone != "off":
            devices.append(resolve_microphone() if microphone == "default" else microphone)
            speakers.append("You")
        if computer != "off":
            devices.append(DEFAULT_MONITOR if computer == "default" else computer)
            speakers.append("Others")
        if len(devices) == 2:
            # The system's default "microphone" can itself be a monitor of the output.
            # Recording the same source twice would double the audio, so keep one.
            mic_default, monitor_default = default_names()
            resolved = [
                {DEFAULT_MIC: mic_default, DEFAULT_MONITOR: monitor_default}.get(d, d) for d in devices
            ]
            if resolved[0] == resolved[1]:
                devices, speakers = devices[1:], speakers[1:]
        return devices, speakers

    def _begin_capture(self) -> None:
        session = self._live_session()
        if self.detector is None:
            raise RuntimeError("The speech detector isn't loaded")
        devices, speakers = self._selected_inputs()
        if not devices:
            raise UserError("Turn on the microphone or computer audio to record.")
        context = self.segmenter.context if self.segmenter else ""
        self.capture = Capture(devices)
        self.capture.start()
        self.segmenter = Segmenter(
            self.transcriber.transcribe,
            self.detector,
            SegmenterOptions(preview_interval_s=0.6 if self.transcriber.on_gpu else 2.0),
            speakers=speakers,
            vocabulary=self.settings.get("vocabulary"),
        )
        self.segmenter.context = context
        sources = list_sources()
        session.inputs = [describe(d, sources) for d in devices]
        self.active_inputs = [
            {**source_info(d, sources), "role": "microphone" if speaker == "You" else "computer"}
            for d, speaker in zip(devices, speakers)
        ]
        self._stream_base = session.elapsed()

    def _end_capture(self) -> None:
        capture, segmenter = self.capture, self.segmenter
        if capture is None or segmenter is None:
            return
        capture.stop()
        leftover = capture.read(timeout=0)
        if leftover is not None:
            segmenter.feed(*leftover)
        self._apply(segmenter.flush())
        self.capture = None
        self.input_error = None
        self.active_inputs = []
        self.bus.publish("preview", session_id=self._live_session().id, text="")

    def _start(self, title: str = "") -> dict:
        if self.state in (RECORDING, PAUSED):
            self._stop()
        if not self._selected_inputs()[0]:
            raise UserError("Turn on the microphone or computer audio to record.")
        self.segmenter = None
        session = self.session = self.store.create(title=title, model=self.transcriber.model_name)
        self._begin_capture()
        self._set_state(RECORDING, "")
        self.save()
        self.bus.publish("session", session=self.session_payload(session))
        self.bus.publish("meetings_changed")
        return self.session_payload(session)

    def _pause(self) -> None:
        if self.state != RECORDING:
            return
        self._end_capture()
        self._set_state(PAUSED, "")
        self.save()

    def _resume(self) -> None:
        if self.state != PAUSED:
            return
        self._begin_capture()
        self._set_state(RECORDING, "")

    def _stop(self) -> None:
        if self.state not in (RECORDING, PAUSED):
            return
        session = self._live_session()
        self._end_capture()
        session.ended_at = now_local()
        session.dirty = True
        self._set_state(READY, "")
        if session.has_text():
            self.save()
        else:
            self.store.discard(session)
        self.bus.publish("session", session=self.session_payload(session))
        self.bus.publish("meetings_changed")

    def _set_inputs(self, microphone: str, computer_audio: str) -> None:
        previous = (self.settings.get("microphone"), self.settings.get("computer_audio"))
        self.settings.update(microphone=microphone, computer_audio=computer_audio)
        if self.state == RECORDING:
            self._end_capture()
            try:
                self._begin_capture()
            except UserError:
                self.settings.update(microphone=previous[0], computer_audio=previous[1])
                self._begin_capture()
                raise
        self._publish_state()

    def _shutdown(self) -> None:
        self._stop()
        self._stopping.set()

    # State ----------------------------------------------------------------------

    def _set_state(self, state: str, message: str) -> None:
        self.state = state
        self.message = message
        self._publish_state()

    def _publish_state(self) -> None:
        self.bus.publish(
            "state",
            state=self.state,
            message=self.message,
            input_error=self.input_error,
            inputs=self.active_inputs,
            model=self.transcriber.model_name,
            device=self.transcriber.device,
            settings=self.settings.as_dict(),
        )

    def _ticker(self) -> None:
        """Publishes input levels for the meters and saves the live meeting regularly."""
        next_save = time.monotonic() + self.autosave_s
        while not self._stopping.wait(0.15):
            capture = self.capture
            if capture is not None and self.state == RECORDING:
                self.bus.publish("levels", levels=capture.levels())
            if time.monotonic() >= next_save:
                next_save = time.monotonic() + self.autosave_s
                session = self.session
                if session is not None and session.dirty:
                    self.save(session)
