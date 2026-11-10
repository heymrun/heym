"""Child process that decodes one audio file and runs Whisper over it.

``speech_to_text_service`` runs this file as a script. A separate process keeps
native, CPU-bound recognition off the backend's interpreter lock and lets the
parent enforce the timeout by killing it.

Usage: ``speech_to_text_worker.py AUDIO MODEL LANGUAGE THREADS MAX_SECONDS RESULT``.
``RESULT`` receives JSON: the transcript payload, or ``{"error"}``.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    import numpy

SAMPLE_RATE = 16000
AUTO_LANGUAGE = "auto"
_BLOCK_SECONDS = 30
# Filter taps on each side per output sample; 16 keeps speech intact up to about 6 kHz.
_FILTER_WIDTH = 16
# Whisper reports segment times in hundredths of a second.
_TICKS_PER_SECOND = 100


class WorkerError(Exception):
    """A failure the user can act on; its message is returned as-is."""


def _lowpass_kernel(rate: int) -> numpy.ndarray:
    """Windowed-sinc filter that removes what a 16 kHz signal cannot carry."""
    import numpy

    if rate <= SAMPLE_RATE:
        return numpy.ones(1, dtype=numpy.float32)
    half = round(_FILTER_WIDTH * rate / SAMPLE_RATE)
    taps = numpy.arange(-half, half + 1)
    cutoff = 0.45 * SAMPLE_RATE / rate
    kernel = 2 * cutoff * numpy.sinc(2 * cutoff * taps) * numpy.hanning(taps.size)
    return (kernel / kernel.sum()).astype(numpy.float32)


def resample(blocks: Iterable[numpy.ndarray], rate: int) -> Iterator[numpy.ndarray]:
    """Convert mono blocks at ``rate`` to 16 kHz, carrying filter state across blocks."""
    import numpy

    step = rate / SAMPLE_RATE
    kernel = _lowpass_kernel(rate)
    half = kernel.size // 2
    pending = numpy.zeros(half, dtype=numpy.float32)
    first = 0
    emitted = 0
    for block in itertools.chain(blocks, [numpy.zeros(half, dtype=numpy.float32)]):
        buffer = numpy.concatenate([pending, block])
        if buffer.size < kernel.size:
            pending = buffer
            continue
        # filtered[i] is the input sample at index first + i.
        filtered = numpy.convolve(buffer, kernel, mode="valid")
        end = int((first + filtered.size - 1) / step) + 1
        positions = numpy.arange(emitted, end) * step - first
        yield numpy.interp(positions, numpy.arange(filtered.size), filtered).astype(numpy.float32)
        emitted = end
        first += filtered.size - 1
        pending = buffer[filtered.size - 1 :]


def decode_audio(path: str, max_seconds: int) -> numpy.ndarray:
    """Decode an mp3, wav, ogg or flac file into 16 kHz mono float32 samples."""
    import numpy
    import soundfile

    limit = max_seconds * SAMPLE_RATE
    chunks: list[numpy.ndarray] = []
    samples = 0
    try:
        with soundfile.SoundFile(path) as handle:
            rate = handle.samplerate
            mono = (
                block.mean(axis=1, dtype=numpy.float32)
                for block in handle.blocks(
                    blocksize=rate * _BLOCK_SECONDS, dtype="float32", always_2d=True
                )
            )
            for chunk in resample(mono, rate):
                chunks.append(chunk)
                samples += chunk.size
                if samples > limit:
                    raise WorkerError(
                        f"the recording is longer than {max_seconds // 60} minutes. "
                        "Split it into shorter files and transcribe them one by one."
                    )
    except (soundfile.SoundFileError, OSError) as exc:
        raise WorkerError(
            "the file is not readable audio. mp3, wav and ogg are supported."
        ) from exc

    if samples == 0:
        raise WorkerError("the file contains no audio")
    return numpy.concatenate(chunks)


def transcribe(pcm: numpy.ndarray, model_path: str, language: str, threads: int) -> dict:
    """Run Whisper over decoded samples and return the result payload."""
    import _pywhispercpp as whisper_cpp
    from pywhispercpp.model import Model

    if language != AUTO_LANGUAGE and whisper_cpp.whisper_lang_id(language) < 0:
        raise WorkerError(f"unknown language '{language}'. Use a code such as en, tr or de.")

    model = Model(model_path, n_threads=threads, print_progress=False, print_realtime=False)
    segments = model.transcribe(pcm, language=language)

    detected = language
    if language == AUTO_LANGUAGE:
        detected = whisper_cpp.whisper_lang_str(whisper_cpp.whisper_full_lang_id(model._ctx))

    parts = [
        {
            "start": segment.t0 / _TICKS_PER_SECOND,
            "end": segment.t1 / _TICKS_PER_SECOND,
            "text": segment.text.strip(),
        }
        for segment in segments
    ]
    parts = [part for part in parts if part["text"]]
    return {
        "text": " ".join(part["text"] for part in parts),
        "language": detected or "",
        "duration_seconds": round(pcm.size / SAMPLE_RATE, 2),
        "segments": parts,
    }


def main(argv: list[str]) -> int:
    """Transcribe one file; the exit code says whether RESULT holds a transcript."""
    if len(argv) != 6:
        print(__doc__, file=sys.stderr)
        return 2
    audio_path, model_path, language, threads, max_seconds, result_path = argv

    try:
        pcm = decode_audio(audio_path, int(max_seconds))
        payload = transcribe(pcm, model_path, language, int(threads))
        code = 0
    except WorkerError as exc:
        payload = {"error": str(exc)}
        code = 1

    Path(result_path).write_text(json.dumps(payload), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
