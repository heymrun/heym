"""Whisper-backed speech recognition used by the converter node (audio -> text).

One multilingual Whisper model covers about a hundred languages and detects the
spoken one itself. The model and the packages that run it (``pywhispercpp``,
``soundfile``) ship with every way of running Heym, so nothing here is configurable.
Recognition runs in a child process, see ``speech_to_text_worker``.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

AUTO_LANGUAGE = "auto"

TIMEOUT_SECONDS = 900
MAX_AUDIO_SECONDS = 30 * 60
MAX_THREADS = 4

# Images bake the model in, run.sh downloads it; docker/install-stt-model.sh names it.
MODEL_DIRS: tuple[Path, ...] = (
    Path("/opt/heym/stt"),
    Path(__file__).resolve().parents[2] / ".cache" / "stt",
)
_MODEL_GLOB = "ggml-*.bin"

_WORKER_PATH = Path(__file__).with_name("speech_to_text_worker.py")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,24}$")
_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")
_STDERR_TAIL_CHARS = 600


@dataclass
class SttSegment:
    """One recognized stretch of speech, with times in seconds."""

    start: float
    end: float
    text: str


@dataclass
class SttResult:
    """Outcome of transcribing one audio file."""

    text: str
    language: str
    duration_seconds: float
    segments: list[SttSegment] = field(default_factory=list)


def parse_language(raw: object) -> str:
    """Validate a language choice: ``auto`` or a Whisper code such as ``tr``."""
    text = str(raw).strip().lower() if raw not in (None, "") else AUTO_LANGUAGE
    if not text or text == AUTO_LANGUAGE:
        return AUTO_LANGUAGE
    if not _LANGUAGE_RE.match(text):
        raise ValueError(
            f"Voice transcribe: invalid language '{text}'. Use a code such as en, tr or de."
        )
    return text


def resolve_model() -> Path:
    """Return the Whisper model file this install ships."""
    for directory in MODEL_DIRS:
        models = sorted(directory.glob(_MODEL_GLOB))
        if models:
            return models[0]
    raise ValueError(
        "Voice transcribe: the speech model was not found. It ships with Heym, so a missing "
        "model means the backend is running outside a standard install. Start Heym with "
        "run.sh or a release image to restore it."
    )


def _run_worker(audio_path: Path, model_path: Path, language: str, result_path: Path) -> dict:
    """Run the recognition child process and return the payload it wrote."""
    threads = max(1, min(MAX_THREADS, os.cpu_count() or 1))
    cmd = [
        sys.executable,
        "-P",
        str(_WORKER_PATH),
        str(audio_path),
        str(model_path),
        language,
        str(threads),
        str(MAX_AUDIO_SECONDS),
        str(result_path),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"Voice transcribe: recognition timed out after {TIMEOUT_SECONDS}s. "
            "Split the recording into shorter files."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Voice transcribe: failed to start recognition: {exc}") from exc

    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        if completed.returncode == -signal.SIGILL:
            raise ValueError(
                "Voice transcribe: this machine's CPU lacks AVX2, which recognition needs "
                "on x86. Run Heym on a CPU from 2013 or later, or expose the host CPU to the VM."
            )
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        detail = stderr[-_STDERR_TAIL_CHARS:] or f"exit code {completed.returncode}"
        raise ValueError(f"Voice transcribe: recognition failed: {detail}")
    return payload


def audio_to_text(
    audio_bytes: bytes,
    *,
    filename: str = "audio",
    language: str = AUTO_LANGUAGE,
) -> SttResult:
    """Transcribe the speech in one audio file."""
    if not audio_bytes:
        raise ValueError("Voice transcribe: the audio file is empty")

    model_path = resolve_model()
    suffix = Path(filename or "").suffix
    if not _SUFFIX_RE.match(suffix):
        suffix = ".audio"

    with tempfile.TemporaryDirectory(prefix="heym-stt-") as tmp:
        audio_path = Path(tmp) / f"input{suffix}"
        audio_path.write_bytes(audio_bytes)
        payload = _run_worker(audio_path, model_path, language, Path(tmp) / "result.json")

    error = payload.get("error")
    if error:
        raise ValueError(f"Voice transcribe: {error}")

    segments = [
        SttSegment(
            start=float(item.get("start", 0)),
            end=float(item.get("end", 0)),
            text=str(item.get("text", "")),
        )
        for item in payload.get("segments", [])
        if isinstance(item, dict)
    ]
    return SttResult(
        text=str(payload.get("text", "")),
        language=str(payload.get("language", "")),
        duration_seconds=float(payload.get("duration_seconds", 0)),
        segments=segments,
    )
