import io
import json
import math
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import speech_to_text_service as stt
from app.services import speech_to_text_worker as worker


def _wav_bytes(seconds: float, *, rate: int = 44100, channels: int = 2) -> bytes:
    """Build a PCM tone, deliberately not in Whisper's 16 kHz mono format."""
    frames = bytearray()
    for index in range(int(seconds * rate)):
        sample = int(12000 * math.sin(2 * math.pi * 440 * index / rate))
        frames += struct.pack("<h", sample) * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


class LanguageTests(unittest.TestCase):
    def test_blank_and_auto_map_to_auto(self) -> None:
        for raw in ("", None, "auto", "  AUTO  "):
            self.assertEqual(stt.parse_language(raw), stt.AUTO_LANGUAGE)

    def test_codes_are_lowercased(self) -> None:
        self.assertEqual(stt.parse_language(" TR "), "tr")
        self.assertEqual(stt.parse_language("yue"), "yue")
        self.assertEqual(stt.parse_language("turkish"), "turkish")

    def test_anything_but_letters_is_rejected(self) -> None:
        for raw in ("tr; rm -rf /", "en&&whoami", "../../etc/passwd", "en+tr", "t", "--help"):
            with self.assertRaises(ValueError):
                stt.parse_language(raw)


class ModelResolutionTests(unittest.TestCase):
    def test_first_directory_holding_a_model_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            shipped = Path(tmp) / "shipped"
            empty.mkdir()
            shipped.mkdir()
            (shipped / "ggml-small-q5_1.bin").write_bytes(b"model")
            (shipped / "notes.txt").write_text("ignored")

            with patch.object(stt, "MODEL_DIRS", (empty, shipped, Path(tmp) / "missing")):
                self.assertEqual(stt.resolve_model(), shipped / "ggml-small-q5_1.bin")

    def test_missing_model_explains_that_it_ships_with_heym(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(stt, "MODEL_DIRS", (Path(tmp),)):
                with self.assertRaises(ValueError) as raised:
                    stt.resolve_model()
        self.assertIn("ships with Heym", str(raised.exception))


class AudioToTextTests(unittest.TestCase):
    def _run(
        self,
        payload: object,
        *,
        returncode: int = 0,
        stderr: bytes = b"",
        filename: str = "note.ogg",
        language: str = "auto",
    ) -> tuple[stt.SttResult, list[str]]:
        """Transcribe with the model lookup and the child process stubbed out."""
        seen: list[str] = []

        def fake_run(cmd, **kwargs):
            seen.extend(cmd)
            self.assertEqual(kwargs["timeout"], stt.TIMEOUT_SECONDS)
            self.assertEqual(Path(cmd[3]).read_bytes(), b"audio-bytes")
            if payload is not None:
                Path(cmd[-1]).write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, returncode, stdout=b"", stderr=stderr)

        with (
            patch.object(stt, "resolve_model", return_value=Path("/models/ggml-x.bin")),
            patch.object(stt.subprocess, "run", side_effect=fake_run),
        ):
            result = stt.audio_to_text(b"audio-bytes", filename=filename, language=language)
        return result, seen

    def test_result_is_parsed_from_the_worker_payload(self) -> None:
        result, cmd = self._run(
            {
                "text": "Merhaba dünya",
                "language": "tr",
                "duration_seconds": 3.5,
                "segments": [{"start": 0.0, "end": 3.5, "text": "Merhaba dünya"}],
            },
            language="tr",
        )

        self.assertEqual(result.text, "Merhaba dünya")
        self.assertEqual(result.language, "tr")
        self.assertEqual(result.duration_seconds, 3.5)
        self.assertEqual(result.segments, [stt.SttSegment(0.0, 3.5, "Merhaba dünya")])
        self.assertEqual(cmd[0], sys.executable)
        # -P keeps the services directory off the child's import path.
        self.assertEqual(cmd[1], "-P")
        self.assertEqual(Path(cmd[2]).name, "speech_to_text_worker.py")
        self.assertTrue(cmd[3].endswith("input.ogg"))
        self.assertEqual(cmd[4:8], ["/models/ggml-x.bin", "tr", cmd[6], str(stt.MAX_AUDIO_SECONDS)])
        self.assertLessEqual(int(cmd[6]), stt.MAX_THREADS)

    def test_unsafe_filename_suffix_is_not_used(self) -> None:
        _, cmd = self._run({"text": ""}, filename="voice.o g;g")
        self.assertTrue(cmd[3].endswith("input.audio"))

    def test_worker_error_is_raised_with_its_message(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self._run({"error": "the file has no audio track"}, returncode=1)
        self.assertEqual(str(raised.exception), "Voice transcribe: the file has no audio track")

    def test_crash_without_a_result_reports_stderr(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self._run(None, returncode=-11, stderr=b"whisper_init: failed to load model")
        self.assertIn("failed to load model", str(raised.exception))

    def test_crash_without_stderr_reports_the_exit_code(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self._run(None, returncode=-9)
        self.assertIn("exit code -9", str(raised.exception))

    def test_illegal_instruction_names_the_cpu_requirement(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self._run(None, returncode=-signal.SIGILL)
        self.assertIn("AVX2", str(raised.exception))

    def test_timeout_is_reported(self) -> None:
        with (
            patch.object(stt, "resolve_model", return_value=Path("/models/ggml-x.bin")),
            patch.object(
                stt.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="worker", timeout=1),
            ),
        ):
            with self.assertRaises(ValueError) as raised:
                stt.audio_to_text(b"audio-bytes")
        self.assertIn("timed out", str(raised.exception))

    def test_empty_file_is_rejected_before_the_model_is_looked_up(self) -> None:
        with patch.object(stt, "resolve_model") as resolve:
            with self.assertRaises(ValueError):
                stt.audio_to_text(b"")
        resolve.assert_not_called()


class WorkerResampleTests(unittest.TestCase):
    def _tone(self, hertz: float, rate: int, seconds: float = 1.0):
        import numpy

        times = numpy.arange(int(rate * seconds)) / rate
        return numpy.sin(2 * numpy.pi * hertz * times).astype(numpy.float32)

    def _resample(self, signal_in, rate: int, block: int | None = None):
        import numpy

        size = block or signal_in.size
        blocks = [signal_in[i : i + size] for i in range(0, signal_in.size, size)]
        return numpy.concatenate(list(worker.resample(blocks, rate)))

    def _peak_hertz(self, samples) -> float:
        import numpy

        spectrum = numpy.abs(numpy.fft.rfft(samples))
        return float(numpy.argmax(spectrum) * worker.SAMPLE_RATE / samples.size)

    def test_speech_band_tone_keeps_its_pitch_and_level(self) -> None:
        for rate in (8000, 22050, 44100, 48000):
            with self.subTest(rate=rate):
                out = self._resample(self._tone(440, rate), rate)
                self.assertAlmostEqual(out.size, worker.SAMPLE_RATE, delta=2)
                self.assertAlmostEqual(self._peak_hertz(out), 440, delta=2)
                self.assertAlmostEqual(float(abs(out[2000:-2000]).max()), 1.0, delta=0.05)

    def test_content_above_8_khz_is_filtered_out_instead_of_aliasing(self) -> None:
        out = self._resample(self._tone(11000, 44100), 44100)
        self.assertLess(float(abs(out[2000:-2000]).max()), 0.02)

    def test_block_boundaries_do_not_change_the_result(self) -> None:
        import numpy

        tone = self._tone(440, 44100, seconds=2.0)
        whole = self._resample(tone, 44100)
        for block in (997, 4096, 44100):
            with self.subTest(block=block):
                pieces = self._resample(tone, 44100, block=block)
                self.assertEqual(pieces.size, whole.size)
                self.assertTrue(numpy.allclose(pieces, whole, atol=1e-4))

    def test_16_khz_input_passes_through(self) -> None:
        import numpy

        tone = self._tone(440, worker.SAMPLE_RATE)
        self.assertTrue(numpy.allclose(self._resample(tone, worker.SAMPLE_RATE, block=1000), tone))


class WorkerDecodeTests(unittest.TestCase):
    """Runs the decoder for real: decoding is the part a mock would hide."""

    def _write(self, tmp: str, data: bytes, name: str = "input.wav") -> str:
        path = Path(tmp) / name
        path.write_bytes(data)
        return str(path)

    def test_stereo_44k_wav_becomes_16k_mono_float(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pcm = worker.decode_audio(self._write(tmp, _wav_bytes(1.0)), max_seconds=60)

        self.assertEqual(str(pcm.dtype), "float32")
        self.assertEqual(pcm.ndim, 1)
        self.assertAlmostEqual(pcm.size / worker.SAMPLE_RATE, 1.0, delta=0.05)
        self.assertLessEqual(float(abs(pcm).max()), 1.0)
        self.assertGreater(float(abs(pcm).max()), 0.1)

    def test_whatsapp_style_ogg_opus_voice_note_decodes(self) -> None:
        import soundfile

        with tempfile.TemporaryDirectory() as tmp:
            # WhatsApp voice notes: Opus in an Ogg container, mono 16 kHz, named *.opus.
            wav = Path(tmp) / "tone.wav"
            wav.write_bytes(_wav_bytes(1.0, rate=16000, channels=1))
            samples, rate = soundfile.read(str(wav), dtype="float32")
            note = Path(tmp) / "WhatsApp Audio 2026-11-10 at 10.00.36.opus"
            soundfile.write(str(note), samples, rate, format="OGG", subtype="OPUS")

            pcm = worker.decode_audio(str(note), max_seconds=60)

        self.assertAlmostEqual(pcm.size / worker.SAMPLE_RATE, 1.0, delta=0.05)
        self.assertGreater(float(abs(pcm).max()), 0.1)

    def test_unreadable_audio_names_the_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(worker.WorkerError) as raised:
                worker.decode_audio(self._write(tmp, b"not audio at all" * 64), max_seconds=60)
        self.assertIn("mp3, wav, ogg, opus and flac", str(raised.exception))

    def test_recording_over_the_limit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(worker.WorkerError) as raised:
                worker.decode_audio(self._write(tmp, _wav_bytes(2.5, rate=8000)), max_seconds=1)
        self.assertIn("longer than", str(raised.exception))

    def test_non_audio_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(worker.WorkerError) as raised:
                worker.decode_audio(self._write(tmp, b"not audio at all" * 64), max_seconds=60)
        self.assertIn("not readable audio", str(raised.exception))
        self.assertNotIn(tmp, str(raised.exception))

    def test_main_writes_the_error_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            code = worker.main(
                [
                    self._write(tmp, b"not audio at all" * 64),
                    "/models/none.bin",
                    "auto",
                    "1",
                    "60",
                    str(result_path),
                ]
            )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 1)
        self.assertIn("not readable audio", payload["error"])


class WorkerTranscribeTests(unittest.TestCase):
    def _transcribe(self, language: str) -> tuple[dict, dict]:
        """Run the worker's Whisper step against a stand-in for the native library."""
        import numpy

        seen: dict = {}

        class FakeModel:
            _ctx = object()

            def __init__(self, model_path: str, **params: object) -> None:
                seen["model_path"] = model_path
                seen["params"] = params

            def transcribe(self, _pcm: object, **params: object) -> list:
                seen["transcribe"] = params
                return [
                    SimpleNamespace(t0=0, t1=298, text=" Merhaba. "),
                    SimpleNamespace(t0=298, t1=310, text="  "),
                    SimpleNamespace(t0=310, t1=650, text="Toplantı yarın."),
                ]

        native = SimpleNamespace(
            whisper_lang_id=lambda code: 9 if code in ("tr", "auto") else -1,
            whisper_full_lang_id=lambda _ctx: 9,
            whisper_lang_str=lambda _id: "tr",
        )
        modules = {
            "_pywhispercpp": native,
            "pywhispercpp": SimpleNamespace(),
            "pywhispercpp.model": SimpleNamespace(Model=FakeModel),
        }
        pcm = numpy.zeros(worker.SAMPLE_RATE * 2, dtype=numpy.float32)
        with patch.dict(sys.modules, modules):
            return worker.transcribe(pcm, "/models/ggml-x.bin", language, 4), seen

    def test_segments_use_seconds_and_blank_ones_are_dropped(self) -> None:
        payload, seen = self._transcribe("auto")

        self.assertEqual(payload["text"], "Merhaba. Toplantı yarın.")
        self.assertEqual(payload["language"], "tr")
        self.assertEqual(payload["duration_seconds"], 2.0)
        self.assertEqual(
            payload["segments"],
            [
                {"start": 0.0, "end": 2.98, "text": "Merhaba."},
                {"start": 3.1, "end": 6.5, "text": "Toplantı yarın."},
            ],
        )
        self.assertEqual(seen["model_path"], "/models/ggml-x.bin")
        self.assertEqual(seen["params"]["n_threads"], 4)
        self.assertEqual(seen["transcribe"], {"language": "auto"})

    def test_named_language_is_passed_through(self) -> None:
        payload, seen = self._transcribe("tr")

        self.assertEqual(payload["language"], "tr")
        self.assertEqual(seen["transcribe"], {"language": "tr"})

    def test_unknown_language_is_rejected_before_the_model_loads(self) -> None:
        with self.assertRaises(worker.WorkerError) as raised:
            self._transcribe("zz")
        self.assertIn("unknown language 'zz'", str(raised.exception))
