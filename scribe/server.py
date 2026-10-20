"""The local web server behind the Scribe window.

It only listens on this computer (127.0.0.1) by default. Requests that change
anything must be JSON and come from Scribe's own address, so other websites
open in the browser can't drive it.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import re
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, quote, urlsplit

from . import audio
from .engine import PAUSED, RECORDING, Engine, UserError
from .sessions import Session, SessionStore, render_markdown, render_text, summarize

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"


def input_choices() -> dict:
    """The options for the Microphone and Computer audio pickers."""
    sources = audio.list_sources()
    mic_default, monitor_default = audio.default_names()
    by_name = {s.name: s for s in sources}

    def option(source: audio.Source) -> dict:
        return {"value": source.name, "label": source.label, "detail": source.detail, "icon": source.icon}

    def default(name: str, for_microphone: bool) -> dict:
        choice = {"value": "default", "label": "System default", "icon": "default", "warning": False}
        current = by_name.get(name)
        if for_microphone and (current is None or current.is_monitor):
            # The default input can be an output's monitor (what you hear), so
            # Scribe records a real microphone instead; say which.
            fallback = by_name.get(audio.resolve_microphone(sources))
            choice["detail"] = f"Using {fallback.label} ({fallback.detail.lower()})" if fallback else "No microphone found"
            choice["warning"] = fallback is None
        elif current is None:
            choice["detail"] = "Follows your sound settings"
        else:
            choice["detail"] = f"Currently {current.label}"
        return choice

    off = {"value": "off", "label": "Off", "detail": "Don't record this", "icon": "off"}
    return {
        "microphone": [default(mic_default, True)]
        + [option(s) for s in sources if not s.is_monitor]
        + [off],
        "computer_audio": [default(monitor_default, False)]
        + [option(s) for s in sources if s.is_monitor]
        + [off],
    }


class ScribeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, engine: Engine, store: SessionStore):
        super().__init__(address, Handler)
        self.engine = engine
        self.store = store
        self.closing = threading.Event()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{'127.0.0.1' if host in ('', '0.0.0.0') else host}:{port}/"


ROUTES: list[tuple[str, re.Pattern, str]] = [
    (method, re.compile(f"^{pattern}$"), name)
    for method, pattern, name in [
        ("GET", r"/", "index"),
        ("GET", r"/static/(?P<path>[\w./-]+)", "static"),
        ("GET", r"/api/state", "state"),
        ("GET", r"/api/events", "events"),
        ("GET", r"/api/inputs", "inputs"),
        ("POST", r"/api/inputs", "set_inputs"),
        ("POST", r"/api/vocabulary", "set_vocabulary"),
        ("POST", r"/api/recording/(?P<action>start|pause|resume|stop)", "recording"),
        ("GET", r"/api/meetings", "meetings"),
        ("GET", r"/api/meetings/(?P<id>[\w-]+)", "meeting"),
        ("GET", r"/api/meetings/(?P<id>[\w-]+)/export\.(?P<fmt>txt|md)", "export"),
        ("POST", r"/api/meetings/(?P<id>[\w-]+)/title", "set_title"),
        ("POST", r"/api/meetings/(?P<id>[\w-]+)/blocks/(?P<block>\d+)", "edit_block"),
        ("POST", r"/api/meetings/(?P<id>[\w-]+)/reveal", "reveal"),
        ("POST", r"/api/meetings/(?P<id>[\w-]+)/delete", "delete"),
        ("POST", r"/api/folder/open", "open_folder"),
    ]
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def scribe(self) -> ScribeServer:
        """The server this request came in on, with Scribe's engine and store."""
        return cast(ScribeServer, self.server)

    def log_message(self, format, *args):  # same signature as the base class
        log.debug("%s %s", self.address_string(), format % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        # Read the whole body up front so a kept-alive connection never sees leftovers.
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            self.close_connection = True
            return self._send_json({"error": "Request too large."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self._raw_body = self.rfile.read(length) if length else b""
        if not self._trusted(method):
            return self._send_json({"error": "Request refused."}, HTTPStatus.FORBIDDEN)
        for route_method, pattern, name in ROUTES:
            match = pattern.match(url.path)
            if match and route_method == method:
                try:
                    getattr(self, f"_{name}")(**match.groupdict(), query=parse_qs(url.query))
                except UserError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
                except KeyError:
                    self._send_json({"error": "That meeting doesn't exist."}, HTTPStatus.NOT_FOUND)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:  # answered as a 500; the details go to the log
                    log.exception("Request %s %s failed", method, self.path)
                    self._send_json({"error": "Something went wrong. See the log for details."}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
        self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def _trusted(self, method: str) -> bool:
        port = self.scribe.server_address[1]
        bound = self.scribe.server_address[0]
        if bound not in ("", "0.0.0.0", "::"):
            # Guard against DNS rebinding: only answer to the names Scribe is served on.
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", f"{bound}:{port}"}
            if self.headers.get("Host", "") not in allowed:
                return False
        if method == "POST":
            # JSON bodies can't be sent cross-site without a CORS preflight, which is never granted.
            return self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json"
        return True

    # Helpers --------------------------------------------------------------------

    def _body(self) -> dict:
        if not self._raw_body:
            return {}
        try:
            data = json.loads(self._raw_body)
        except ValueError:
            raise UserError("The request wasn't valid JSON.") from None
        return data if isinstance(data, dict) else {}

    def _send(self, body: bytes, content_type: str, status=HTTPStatus.OK, headers=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=HTTPStatus.OK) -> None:
        self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def _session(self, session_id: str) -> Session:
        live = self.scribe.engine.session
        if live is not None and live.id == session_id:
            return live
        return self.scribe.store.load(session_id)

    # Routes ---------------------------------------------------------------------

    def _index(self, query):
        self._static("index.html", query)

    def _static(self, path, query):
        target = (WEB_DIR / path).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            return self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        self._send(target.read_bytes(), content_type)

    def _state(self, query):
        self._send_json(self.scribe.engine.snapshot())

    def _events(self, query):
        """Server-sent events: a long-lived response the page listens to for live updates."""
        bus = self.scribe.engine.bus
        subscription = bus.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self._write_event("snapshot", self.scribe.engine.snapshot())
            while not self.scribe.closing.is_set():
                try:
                    kind, data = subscription.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                self._write_event(kind, data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(subscription)

    def _write_event(self, kind: str, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())
        self.wfile.flush()

    def _inputs(self, query):
        self._send_json(input_choices())

    def _set_inputs(self, query):
        body = self._body()
        engine = self.scribe.engine
        engine.set_inputs(
            str(body.get("microphone", engine.settings.get("microphone"))),
            str(body.get("computer_audio", engine.settings.get("computer_audio"))),
        )
        self._send_json(engine.snapshot())

    def _set_vocabulary(self, query):
        self.scribe.engine.set_vocabulary(str(self._body().get("text", "")))
        self._send_json({"ok": True})

    def _recording(self, action, query):
        engine = self.scribe.engine
        if action == "start":
            engine.request("start", title=str(self._body().get("title", "")))
        else:
            engine.request(action)
        self._send_json(engine.snapshot())

    def _meetings(self, query):
        text = query.get("q", [""])[0]
        meetings = self.scribe.store.list_meetings(text)
        engine = self.scribe.engine
        live = engine.session
        listed = live is not None and (live.has_text() or engine.state in (RECORDING, PAUSED))
        if listed and text.lower() in f"{live.title}\n{live.plain_text()}".lower():
            # The live meeting may not be on disk yet, and its newest words may not be saved.
            meetings = [m for m in meetings if m["id"] != live.id]
            meetings.insert(0, summarize(live))
        self._send_json({"meetings": meetings})

    def _meeting(self, id, query):
        self._send_json(self.scribe.engine.session_payload(self._session(id)))

    def _export(self, id, fmt, query):
        session = self._session(id)
        name = Path(session.txt_name or f"{session.id}.txt").stem
        body = render_text(session) if fmt == "txt" else render_markdown(session)
        content_type = "text/plain; charset=utf-8" if fmt == "txt" else "text/markdown; charset=utf-8"
        disposition = f"attachment; filename*=UTF-8''{quote(name)}.{fmt}"
        self._send(body.encode(), content_type, headers={"Content-Disposition": disposition})

    def _set_title(self, id, query):
        session = self._session(id)
        session.set_title(str(self._body().get("title", "")))
        self.scribe.engine.save(session)
        self.scribe.engine.bus.publish("meetings_changed")
        self._send_json(self.scribe.engine.session_payload(session))

    def _edit_block(self, id, block, query):
        body = self._body()
        session = self._session(id)
        base = body.get("base")
        edited = session.edit_block(int(block), str(body.get("text", "")), str(base) if base is not None else None)
        self.scribe.engine.save(session)
        self.scribe.engine.bus.publish("block", session_id=session.id, block=edited.to_dict())
        self._send_json(edited.to_dict())

    def _reveal(self, id, query):
        session = self._session(id)
        if not session.txt_name:
            return self._open_folder(query)  # nothing written yet
        path = self.scribe.store.folder / session.txt_name
        try:
            # Ask the file manager to open the folder with the transcript selected.
            subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.freedesktop.FileManager1",
                    "--object-path", "/org/freedesktop/FileManager1",
                    "--method", "org.freedesktop.FileManager1.ShowItems",
                    f"['{path.as_uri()}']", "",
                ],
                check=True, capture_output=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            subprocess.Popen(["xdg-open", str(path.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._send_json({"ok": True})

    def _delete(self, id, query):
        self.scribe.engine.delete(self._session(id))
        self._send_json({"ok": True})

    def _open_folder(self, query):
        subprocess.Popen(
            ["xdg-open", str(self.scribe.store.folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._send_json({"ok": True})


def start_server(engine: Engine, store: SessionStore, host: str, port: int) -> ScribeServer:
    """Bind to ``port``, or the next free one, and serve on a background thread."""
    last_error: OSError | None = None
    for candidate in range(port, port + 20):
        try:
            server = ScribeServer((host, candidate), engine, store)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"No free port between {port} and {port + 19}: {last_error}")
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server
