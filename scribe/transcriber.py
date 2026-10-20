"""The Whisper model (via faster-whisper) and the speech detector."""

from __future__ import annotations

import ctypes
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from faster_whisper import WhisperModel  # imported for real in load(), after the CUDA libraries

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Phrases Whisper invents from silence or noise; it learned them from video subtitles.
# They're never said in a meeting, so a segment containing one is dropped.
_HALLUCINATIONS = re.compile(
    r"thanks? (you )?for watching|subtitles? (by|from)|please subscribe|amara\.org"
    r"|transcribed by|transcription by|copyright ©",
    re.IGNORECASE,
)


def preload_cuda_libraries() -> None:
    """Load cuBLAS and cuDNN from the pip ``nvidia-*`` packages, if present.

    CTranslate2 looks these up by name when it starts using the GPU. Loading
    them here first means it finds the right versions without anyone having
    to set LD_LIBRARY_PATH.
    """
    lib_dirs = []
    for package in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
        try:
            module = __import__(package, fromlist=["__path__"])
        except ImportError:
            continue
        lib_dirs += [Path(p) / "lib" for p in module.__path__]
    libraries = sorted(lib for d in lib_dirs if d.is_dir() for lib in d.glob("lib*.so*"))
    # Some libraries depend on others in the list, so retry the failures once.
    for _ in range(2):
        failed = []
        for lib in libraries:
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                failed.append(lib)
        libraries = failed


@dataclass
class Segment:
    start: float  # seconds into the audio that was transcribed
    end: float
    text: str


class Transcriber:
    def __init__(
        self,
        model: str = "auto",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = "en",
    ):
        self.requested_model = model
        self.requested_device = device
        self.requested_compute = compute_type
        self.language = language
        self.model_name = ""
        self.device = ""
        self._model: WhisperModel | None = None
        self.on_status = lambda message: None

    def load(self) -> None:
        preload_cuda_libraries()
        import ctranslate2
        from faster_whisper import WhisperModel

        device = self.requested_device
        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        try:
            self._model = self._open(WhisperModel, device)
        except Exception as exc:  # any CUDA failure falls back to the CPU
            if device != "cuda" or self.requested_device != "auto":
                raise
            log.warning("Couldn't use the GPU (%s); falling back to the CPU", exc)
            device = "cpu"
            self._model = self._open(WhisperModel, device)
        self.device = device
        # The first call is slow while kernels are prepared; get it out of the way now.
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), final=False)
        log.info("Loaded %s on %s", self.model_name, self.device)

    def _open(self, model_class: type[WhisperModel], device: str) -> WhisperModel:
        name = self.requested_model
        if name == "auto":
            name = "large-v3-turbo" if device == "cuda" else "small.en"
        if self.language not in (None, "en") and name.endswith(".en"):
            name = name.removesuffix(".en")
        compute = self.requested_compute
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        self.model_name = name
        log.info("Loading %s on %s (%s)", name, device, compute)
        return model_class(self._model_path(name), device=device, compute_type=compute)

    def _model_path(self, name: str) -> str:
        """Use the downloaded copy if there is one, so starting needs no internet."""
        from faster_whisper.utils import download_model

        if Path(name).is_dir():
            return name
        try:
            return download_model(name, local_files_only=True)
        except Exception:  # noqa: BLE001 - not downloaded yet
            self.on_status(f"Downloading the {name} speech model. This happens once.")
            return download_model(name)

    @property
    def on_gpu(self) -> bool:
        return self.device == "cuda"

    def transcribe(
        self,
        audio: np.ndarray,
        prompt: str = "",
        final: bool = True,
        timestamps: bool = False,
    ) -> list[Segment]:
        """Transcribe 16 kHz mono audio.

        ``final`` trades speed for accuracy: previews use greedy decoding, while
        finished phrases use beam search and retry at higher temperatures if the
        first attempt looks repetitive or unsure.
        """
        if self._model is None:
            raise RuntimeError("The speech model isn't loaded yet")
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5 if final else 1,
            temperature=(0.0, 0.2, 0.4, 0.6) if final else 0.0,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            without_timestamps=not timestamps,
            vad_filter=False,
        )
        results = []
        for segment in segments:
            text = segment.text.strip()
            if not text or _HALLUCINATIONS.search(text):
                continue
            if segment.no_speech_prob > 0.8 and segment.avg_logprob < -0.8:
                continue
            results.append(Segment(segment.start, segment.end, text))
        return results


class SpeechDetector:
    """Finds the stretches of audio that contain speech (Silero VAD)."""

    def __init__(self, min_silence_ms: int = 400, pad_ms: int = 100):
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        self._detect = get_speech_timestamps
        self._options = VadOptions(
            threshold=0.5,
            min_speech_duration_ms=200,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=pad_ms,
        )

    def __call__(self, audio: np.ndarray) -> list[tuple[int, int]]:
        """Return (start, end) sample offsets of each speech region."""
        return [(t["start"], t["end"]) for t in self._detect(audio, self._options)]
