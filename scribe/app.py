"""Command line entry point: ``scribe`` (or ``python -m scribe``)."""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import logging.handlers
import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import audio
from .engine import ERROR, LOADING, PAUSED, READY, RECORDING, Engine, UserError
from .events import EventBus
from .server import start_server
from .sessions import SessionStore, format_offset
from .settings import Settings
from .transcriber import Transcriber

log = logging.getLogger("scribe")

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "scribe"


def default_folder() -> Path:
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "Transcripts"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scribe",
        description="Live meeting transcription with Whisper. Each meeting is saved to one file, updated as you go.",
    )
    parser.add_argument("--title", default="", help="title for the meeting that starts now")
    parser.add_argument("--no-autostart", action="store_true", help="wait for Start instead of recording straight away")
    parser.add_argument(
        "--mic",
        help="microphone to record: 'default', 'off', or a source name from --list-inputs (remembered)",
    )
    parser.add_argument(
        "--computer-audio",
        help="also record what the computer plays, i.e. the other people on a call: "
        "'default', 'off', or a monitor name from --list-inputs (remembered)",
    )
    parser.add_argument("--list-inputs", action="store_true", help="list the audio sources that can be recorded, then exit")
    parser.add_argument(
        "--model",
        default="auto",
        help="Whisper model, e.g. large-v3-turbo, distil-large-v3.5, medium.en, small.en "
        "(default: large-v3-turbo with a GPU, small.en without)",
    )
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--compute-type", default="auto", help="e.g. float16, int8_float16, int8")
    parser.add_argument("--language", default="en", help="language code of the speech, or 'auto' to detect it")
    parser.add_argument("--folder", type=Path, default=default_folder(), help="where transcripts are saved (default: %(default)s)")
    parser.add_argument("--autosave", type=float, default=5, metavar="SECONDS", help="how often the transcript file is updated (default: %(default)s)")
    parser.add_argument(
        "--open",
        choices=["window", "tab", "none"],
        default="window",
        help="open the interface in its own window (needs Chrome or Chromium), a browser tab, or not at all",
    )
    parser.add_argument("--no-web", action="store_true", help="terminal only, without the web interface")
    parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--verbose", action="store_true", help="log more detail to the terminal")
    return parser.parse_args(argv)


def setup_logging(verbose: bool) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "scribe.log"
    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    console = logging.StreamHandler()
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[file_handler, console])
    for noisy in ("httpx", "httpx2", "httpcore", "faster_whisper", "huggingface_hub", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_path


def running_instance(port: int) -> str | None:
    """The address of a Scribe that's already running on this port, if there is one."""
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(f"{url}api/state", timeout=1) as response:
            if "state" in json.load(response):
                return url
    except (OSError, ValueError):
        pass
    return None


def open_interface(url: str, mode: str) -> None:
    if mode == "window":
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
            exe = shutil.which(name)
            if exe:
                subprocess.Popen(
                    [exe, f"--app={url}"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
    webbrowser.open(url)


class TerminalView(threading.Thread):
    """Prints the transcript as it arrives, with the live preview on the last line."""

    DIM, RED, BOLD, RESET = "\033[2m", "\033[31m", "\033[1m", "\033[0m"

    def __init__(self, engine: Engine, bus: EventBus, interactive: bool):
        super().__init__(name="terminal", daemon=True)
        self.engine = engine
        self.queue = bus.subscribe()
        self.interactive = interactive
        self._lock = threading.Lock()
        self._preview_shown = False
        self._last_block: tuple[str, int, int] | None = None  # session, block id, chars printed
        self._last_state = None
        self._last_input_error = None

    def _style(self, text: str, *codes: str) -> str:
        return f"{''.join(codes)}{text}{self.RESET}" if self.interactive else text

    def say(self, text: str = "") -> None:
        with self._lock:
            self._clear_preview()
            try:
                print(text, flush=True)
            except OSError:
                pass  # the terminal was closed; keep running so the meeting still saves

    def _clear_preview(self) -> None:
        if self._preview_shown:
            sys.stdout.write("\r\033[2K")
            self._preview_shown = False

    def _show_preview(self, text: str) -> None:
        if not self.interactive:
            return
        with self._lock:
            self._clear_preview()
            if text:
                width = max(20, shutil.get_terminal_size().columns - 4)
                shown = text if len(text) <= width else "…" + text[-(width - 1):]
                try:
                    sys.stdout.write(self._style(shown, self.DIM))
                    sys.stdout.flush()
                except OSError:
                    return
                self._preview_shown = True

    def run(self) -> None:
        while True:
            kind, data = self.queue.get()
            handler = getattr(self, f"_on_{kind}", None)
            if handler:
                handler(**data)

    def _on_state(self, state, message, input_error, model, device, **_):
        if state != self._last_state:
            self._last_state = state
            if state == LOADING and message:
                self.say(message)
            elif state == READY and not self.engine.session:
                where = "the GPU" if device == "cuda" else "the CPU"
                self.say(f"Speech model {model} ready on {where}.")
                if message:
                    self.say(message)
            elif state == READY:
                self.say(self._style("Stopped. ", self.BOLD) + "Start a new meeting from the window or with n.")
            elif state == PAUSED:
                self.say(self._style("Paused.", self.BOLD) + " Press p to resume.")
            elif state == RECORDING:
                self.say(self._style("● Recording", self.RED, self.BOLD))
            elif state == ERROR:
                self.say(self._style(message, self.RED))
        if input_error != self._last_input_error:
            self._last_input_error = input_error
            if input_error:
                self.say(self._style(input_error, self.RED))

    def _on_session(self, session, **_):
        if session.get("live"):
            title = session["title"] or "Untitled meeting"
            self.say()
            self.say(self._style(title, self.BOLD) + self._style(f"  saved in {self.engine.store.folder}", self.DIM))

    def _on_block(self, session_id, block, **_):
        text = block["text"]
        with self._lock:
            last = self._last_block
            if last and last[0] == session_id and last[1] == block["id"]:
                if len(text) <= last[2]:
                    return  # an edit made in the window; nothing new to print
                new_text, prefix = text[last[2]:].strip(), " " * 12
            elif last and last[0] == session_id and block["id"] < last[1]:
                return
            else:
                speaker = f"{block['speaker']}: " if block.get("speaker") else ""
                new_text, prefix = f"{speaker}{text}", "\n" + self._style(f"[{format_offset(block['start'])}]", self.DIM) + "  "
            self._last_block = (session_id, block["id"], len(text))
        self.say(prefix + new_text)

    def _on_preview(self, text, **_):
        self._show_preview(text)

    def _on_save_failed(self, message, **_):
        self.say(self._style(message, self.RED))


def key_loop(engine: Engine, view: TerminalView, stop: threading.Event) -> None:
    """Single-key controls in the terminal: p pause/resume, n new meeting, s stop, q quit."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    def restore() -> None:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)

    atexit.register(restore)
    tty.setcbreak(fd)
    try:
        while not stop.is_set():
            ready, _, _ = select.select([fd], [], [], 0.3)
            if not ready:
                continue
            key = os.read(fd, 1).decode(errors="ignore").lower()
            try:
                if key == "p" and engine.state == RECORDING:
                    engine.request("pause")
                elif key == "p" and engine.state == PAUSED:
                    engine.request("resume")
                elif key == "n":
                    engine.request("start")
                elif key == "s":
                    engine.request("stop")
                elif key == "q":
                    stop.set()
            except UserError as exc:
                view.say(str(exc))
    finally:
        restore()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_path = setup_logging(args.verbose)

    if args.list_inputs:
        for source in audio.list_sources():
            kind = "computer audio" if source.is_monitor else "microphone"
            print(f"{kind:15} {source.name}\n{'':15} {source.description}")
        return 0
    if not audio.parec_available():
        print("Scribe records with 'parec', which isn't installed. Install it with:\n  sudo apt install pulseaudio-utils")
        return 1

    if not args.no_web and (url := running_instance(args.port)):
        # Two copies would record the same meeting twice; show the one that's running.
        print(f"Scribe is already running: {url}")
        if args.open != "none":
            open_interface(url, args.open)
        return 0

    settings = Settings()
    if args.mic:
        settings.update(microphone=args.mic)
    if args.computer_audio:
        settings.update(computer_audio=args.computer_audio)

    store = SessionStore(args.folder.expanduser())
    bus = EventBus()
    transcriber = Transcriber(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=None if args.language == "auto" else args.language,
    )
    engine = Engine(
        transcriber,
        store,
        bus,
        settings,
        autosave_s=args.autosave,
        autostart=not args.no_autostart,
        title=args.title,
    )
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    view = TerminalView(engine, bus, interactive)
    view.start()

    server = None
    if not args.no_web:
        server = start_server(engine, store, args.host, args.port)
    engine.start()

    view.say(view._style("Scribe", view.BOLD))
    if server:
        view.say(f"Window: {server.url}")
    view.say(f"Transcripts: {store.folder}")
    if interactive:
        view.say(view._style("Keys: p pause/resume, n new meeting, s stop, q quit", view.DIM))
    if server and args.open != "none":
        open_interface(server.url, args.open)

    stop = threading.Event()

    def on_signal(signum, _frame):
        if stop.is_set():
            os._exit(130)  # a second Ctrl+C: leave now; the last autosave is on disk
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    keys = None
    if interactive:
        keys = threading.Thread(target=key_loop, args=(engine, view, stop), name="keys", daemon=True)
        keys.start()

    try:
        while not stop.wait(0.5):
            pass
    finally:
        view.say("Saving…")
        engine.shutdown()
        if server:
            server.closing.set()
            server.shutdown()
        if keys:
            keys.join(timeout=1)
        session = engine.session
        if session is not None and session.txt_name:
            view.say(f"Saved: {store.folder / session.txt_name}")
        log.info("Exited; log at %s", log_path)
    return 0
