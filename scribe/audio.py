"""Recording from PipeWire / PulseAudio.

Each input runs its own ``parec`` process, which lets Scribe record any source
the sound server knows about, including "monitor" sources: the audio your
computer is playing, i.e. the other people on a call. When two inputs are on,
they are mixed into one 16 kHz mono stream, and the level of each is kept
alongside so the transcript can tell your voice apart from the call.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600  # 100 ms
FRAME_BYTES = FRAME_SAMPLES * 2  # s16le mono

DEFAULT_MIC = "@DEFAULT_SOURCE@"
DEFAULT_MONITOR = "@DEFAULT_MONITOR@"


@dataclass
class Source:
    name: str
    description: str
    is_monitor: bool
    label: str = ""  # a short name, e.g. "Digital Microphone"
    detail: str = ""  # where it is, e.g. "This computer"
    icon: str = "microphone"  # microphone, speaker, display or headset


def _friendly(description: str, is_monitor: bool, props: dict) -> tuple[str, str, str]:
    """A short label, a location, and an icon name for a source."""
    bus = props.get("device.bus")
    form = props.get("device.form_factor", "")
    icon_name = props.get("device.icon_name", "")
    profile = props.get("device.profile.description")
    plain = description.removeprefix("Monitor of ")
    if bus == "bluetooth":
        label = props.get("device.description") or plain
        detail = "Bluetooth headphones" if form in ("headset", "headphone", "hands-free") else "Bluetooth"
    elif bus == "pci" and profile:
        label = profile.removesuffix(" Output")
        detail = "External screen" if "HDMI" in profile else "This computer"
    else:
        label = plain
        detail = "USB" if bus == "usb" else ""
    if "headset" in icon_name or "headphone" in icon_name or form in ("headset", "headphone"):
        icon = "headset"
    elif "video-display" in icon_name or "HDMI" in label:
        icon = "display"
    else:
        icon = "speaker" if is_monitor else "microphone"
    return label, detail, icon


def _pactl(*args: str) -> str:
    result = subprocess.run(
        ["pactl", *args], capture_output=True, text=True, timeout=5, check=True
    )
    return result.stdout.strip()


def list_sources() -> list[Source]:
    try:
        data = json.loads(_pactl("--format=json", "list", "sources"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.warning("Couldn't list audio sources: %s", exc)
        return []
    sources = []
    for item in data:
        name = item.get("name", "")
        props = item.get("properties", {})
        description = item.get("description") or name
        is_monitor = props.get("device.class") == "monitor" or name.endswith(".monitor")
        label, detail, icon = _friendly(description, is_monitor, props)
        sources.append(Source(name, description, is_monitor, label, detail, icon))
    return sources


def default_names() -> tuple[str, str]:
    """The sound server's current default source and default output's monitor."""
    try:
        return _pactl("get-default-source"), f"{_pactl('get-default-sink')}.monitor"
    except (OSError, subprocess.SubprocessError):
        return "", ""


def resolve_microphone(sources: list[Source] | None = None) -> str:
    """The microphone "System default" should record.

    The system's default input isn't always a microphone: it can be the
    monitor of an output (what you hear). Then this picks a real microphone
    instead, preferring the computer's built-in one.
    """
    sources = sources if sources is not None else list_sources()
    mic_default, _ = default_names()
    current = next((s for s in sources if s.name == mic_default), None)
    if current is not None and not current.is_monitor:
        return DEFAULT_MIC
    microphones = [s for s in sources if not s.is_monitor]
    built_in = [s for s in microphones if s.detail == "This computer"]
    preferred = [s for s in built_in if "Digital" in s.label] or built_in or microphones
    return preferred[0].name if preferred else DEFAULT_MIC


def source_info(device: str, sources: list[Source]) -> dict:
    """Friendly name and icon for a device Scribe is recording."""
    mic_default, monitor_default = default_names()
    name = {DEFAULT_MIC: mic_default, DEFAULT_MONITOR: monitor_default}.get(device, device)
    source = next((s for s in sources if s.name == name), None)
    if source is None:
        return {"label": name, "detail": "", "icon": "microphone"}
    return {"label": source.label, "detail": source.detail, "icon": source.icon}


def describe(device: str, sources: list[Source] | None = None) -> str:
    sources = sources if sources is not None else list_sources()
    if device in (DEFAULT_MIC, DEFAULT_MONITOR):
        mic, monitor = default_names()
        device = mic if device == DEFAULT_MIC else monitor
    for source in sources:
        if source.name == device:
            return source.description
    return device


def level_from_rms(rms: float) -> float:
    """Map RMS amplitude to 0..1 on a -60..0 dBFS scale, for a level meter."""
    if rms <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, 1.0 + 20.0 * math.log10(rms) / 60.0))


class _Reader(threading.Thread):
    def __init__(self, capture: Capture, index: int, device: str):
        super().__init__(name=f"parec-{index}", daemon=True)
        self.capture = capture
        self.index = index
        self.device = device
        self.stopping = threading.Event()
        self.proc: subprocess.Popen | None = None

    def run(self) -> None:
        while not self.stopping.is_set():
            try:
                self.proc = subprocess.Popen(
                    [
                        "parec",
                        f"--device={self.device}",
                        "--format=s16le",
                        f"--rate={SAMPLE_RATE}",
                        "--channels=1",
                        "--raw",
                        "--latency-msec=50",
                        "--client-name=Scribe",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                self.capture._report(self.index, "Can't record: the 'parec' command isn't installed (package pulseaudio-utils).")
                return
            stdout = self.proc.stdout
            assert stdout is not None  # stdout=PIPE always gives a pipe
            got_audio = False
            while not self.stopping.is_set():
                data = stdout.read(FRAME_BYTES)
                if len(data) < FRAME_BYTES:
                    break
                if not got_audio:
                    got_audio = True
                    self.capture._report(self.index, None)
                self.capture._push(self.index, data)
            self._close()
            if self.stopping.is_set():
                return
            # The device went away (e.g. a Bluetooth headset disconnected). Keep trying.
            self.capture._report(self.index, f"Lost audio from {describe(self.device)}. Reconnecting…")
            log.warning("parec for %s exited; restarting", self.device)
            self.stopping.wait(1.0)

    def _close(self) -> None:
        proc = self.proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()

    def stop(self) -> None:
        self.stopping.set()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


class Capture:
    """Records one or more devices and hands back mixed audio in 100 ms frames."""

    def __init__(self, devices: list[str]):
        if not devices:
            raise ValueError("At least one input device is needed")
        self.devices = list(devices)
        self._buffers = [bytearray() for _ in devices]
        self._levels = [0.0 for _ in devices]
        self._cond = threading.Condition()
        self._readers: list[_Reader] = []
        self._stopped = False
        self._errors: list[str | None] = [None for _ in devices]

    def start(self) -> None:
        self._readers = [_Reader(self, i, device) for i, device in enumerate(self.devices)]
        for reader in self._readers:
            reader.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        for reader in self._readers:
            reader.stop()
        for reader in self._readers:
            reader.join(timeout=3)

    def _push(self, index: int, data: bytes) -> None:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples * samples)))
        with self._cond:
            self._buffers[index] += data
            self._levels[index] = level_from_rms(rms)
            self._cond.notify_all()

    def _report(self, index: int, message: str | None) -> None:
        self._errors[index] = message

    @property
    def error(self) -> str | None:
        return next((e for e in self._errors if e), None)

    def levels(self) -> list[float]:
        with self._cond:
            return list(self._levels)

    def backlog_seconds(self) -> float:
        with self._cond:
            return max(len(b) for b in self._buffers) / 2 / SAMPLE_RATE

    def read(self, timeout: float) -> tuple[np.ndarray, np.ndarray] | None:
        """Wait up to ``timeout`` for audio and return everything available.

        Returns ``(audio, energy)`` where ``audio`` is float32 mono, a whole number
        of frames long, and ``energy`` holds the mean-square level of each input
        for each frame (shape: frames x inputs). Returns None if nothing arrived.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                available = [len(b) // FRAME_BYTES for b in self._buffers]
                frames = min(available)
                # If one input stalls, don't hold up the others for more than 300 ms.
                if frames == 0 and max(available) >= 3:
                    frames = max(available)
                if frames > 0 or self._stopped:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            if frames == 0:
                return None
            wanted = frames * FRAME_BYTES
            chunks = []
            for buffer in self._buffers:
                take = min(len(buffer) // FRAME_BYTES * FRAME_BYTES, wanted)
                chunk = bytes(buffer[:take]) + bytes(wanted - take)
                del buffer[:take]
                # An input that runs ahead of the others (clock drift) is trimmed back.
                if len(buffer) > 5 * FRAME_BYTES:
                    del buffer[: len(buffer) - FRAME_BYTES]
                chunks.append(chunk)

        tracks = np.stack(
            [np.frombuffer(c, dtype=np.int16).astype(np.float32) / 32768.0 for c in chunks]
        )
        energy = np.mean(tracks.reshape(len(chunks), frames, FRAME_SAMPLES) ** 2, axis=2).T
        audio = np.clip(tracks.sum(axis=0), -1.0, 1.0) if len(chunks) > 1 else tracks[0]
        return audio, energy


def parec_available() -> bool:
    return shutil.which("parec") is not None
