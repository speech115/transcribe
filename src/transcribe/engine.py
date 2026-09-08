"""Run local FluidAudio and normalize its ASR and diarization output."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable
import json
import math
import tempfile
import time
import re
import subprocess

def detect_language(text: str) -> str:
    cyr, lat = len(re.findall(r"[А-Яа-яЁё]", text or "")), len(re.findall(r"[A-Za-z]", text or ""))
    total = cyr + lat
    if total < 20:
        return "auto"
    if cyr / total >= .2 and lat / total >= .2:
        return "mixed"
    if cyr / total >= .5:
        return "ru"
    return "en"

class EngineError(Exception):
    """Провал прогона. stage: "input" | "asr" | "diar" | "parse"."""

    def __init__(self, stage: str, reason: str):
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason


def parse_speakers(value: str) -> int | None:
    if value == "auto":
        return -1
    if value == "off":
        return None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value) and int(value) > 0:
        return int(value)
    raise EngineError("input", "--speakers: укажите auto, off или положительное целое число")


@dataclass(frozen=True)
class Transcript:
    words: list = field(default_factory=list)        # [{"start", "end", "text"}]
    segments: list = field(default_factory=list)     # [(start, end, "S<n>", quality)]
    speakers: int = 1
    language: str = "auto"
    engine: str = ""
    asr_s: float = 0.0
    diar_s: float | None = None
    diar_mode: str | None = None
    diar_status: str = "skipped"
    diar_error: str | None = None


class FluidAudioEngine:
    """Адаптер FluidAudio: transcribe() + process() за одним вызовом."""

    def __init__(self, *, binary: Path, model: str = "v3",
                 diar_mode: str = "streaming"):
        self.binary = binary
        self.model = model
        self.diar_mode = diar_mode

    def transcribe(self, wav: Path, *, lang: str = "auto",
                   speakers: str = "auto",
                   on_stage: Callable[[str], None] | None = None) -> Transcript:
        num_speakers = parse_speakers(speakers)
        diar_s = None
        parallel = num_speakers is not None and self.diar_mode == "streaming"
        cancel = Event()

        def diarize():
            nonlocal diar_s
            started = time.perf_counter()
            try:
                return self._run_process(wav, num_speakers, cancel=cancel if parallel else None)
            finally:
                diar_s = time.perf_counter() - started

        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(diarize) if parallel else None
                if on_stage:
                    on_stage("asr")
                t0_asr = time.perf_counter()
                asr_data = self._run_transcribe(wav, lang)
                asr_s = time.perf_counter() - t0_asr
                words = _normalize_words(asr_data)
                if not words:
                    raise EngineError("asr", "ASR вернул пустой результат")

                segments = []
                diar_status, diar_error = "skipped", None
                if num_speakers is not None:
                    if on_stage and (future is None or not future.done()):
                        on_stage("diar")
                    try:
                        diar_data = future.result() if future is not None else diarize()
                        segments, n_speakers = _normalize_diar(diar_data)
                        diar_status = "success"
                    except EngineError as exc:
                        if num_speakers == -1:
                            n_speakers = 1
                            diar_status = "failed"
                            diar_error = " ".join(exc.reason.split())[:500]
                        else:
                            raise
                else:
                    n_speakers = 0
            finally:
                cancel.set()
        n_speakers = max(n_speakers, 1)

        lang_out = _resolve_language(lang, asr_data.get("language"), " ".join(w["text"] for w in words))
        multi = n_speakers > 1
        engine = (f"fluidaudio-parakeet-{self.model} + "
                  f"pyannote-{self.diar_mode}" if multi else f"fluidaudio-parakeet-{self.model}")

        return Transcript(words=words, segments=segments, speakers=n_speakers,
                          language=lang_out,
                          engine=engine,
                          asr_s=asr_s, diar_s=diar_s,
                          diar_mode=(self.diar_mode if speakers != "off" else None),
                          diar_status=diar_status, diar_error=diar_error)

    def _run_transcribe(self, wav: Path, lang: str) -> dict:
        cmd = [str(self.binary), "transcribe", str(wav), "--word-timestamps", "--model-version", self.model]
        if lang != "auto":
            cmd += ["--language", lang]
        return _run_json(cmd, "asr", "--output-json")

    def _run_process(self, wav: Path, num: int, *, cancel: Event | None = None) -> dict:
        cmd = [str(self.binary), "process", str(wav), "--mode", self.diar_mode]
        if num > 0:
            cmd += (["--num-clusters", str(num)] if self.diar_mode == "streaming" else ["--num-speakers", str(num)])
        return _run_json(cmd, "diar", "--output", cancel=cancel)


def _run_json(cmd: list[str], stage: str, output_flag: str, *, cancel: Event | None = None) -> dict:
    try:
        with tempfile.NamedTemporaryFile(prefix=f"engine_{stage}_", suffix=".json") as tmp:
            _run([*cmd, output_flag, tmp.name], stage, cancel=cancel)
            data = json.loads(Path(tmp.name).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise EngineError("parse", f"не удалось прочитать ответ движка: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("parse", "ответ движка не JSON-объект")
    return data


def _resolve_language(lang: str, engine_lang, text: str) -> str:
    if lang != "auto":
        return lang
    if isinstance(engine_lang, str) and engine_lang.lower() != "auto":
        return engine_lang
    return detect_language(text)


def _normalize_words(asr_data: dict) -> list:
    try:
        words = [{"start": float(w["startTime"]), "end": float(w["endTime"]), "text": w["word"]}
                 for w in asr_data["wordTimings"]]
        for w in words:
            if not (math.isfinite(w["start"]) and math.isfinite(w["end"])
                    and 0 <= w["start"] <= w["end"]
                    and isinstance(w["text"], str) and w["text"].strip()):
                raise ValueError("некорректные таймкоды или текст слова")
        return sorted(words, key=lambda w: w["start"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise EngineError("parse", f"некорректные wordTimings: {exc}") from exc


def _normalize_diar(diar_data: dict) -> tuple:
    try:
        raw = [(float(s["startTimeSeconds"]), float(s["endTimeSeconds"]),
                s["speakerId"], float(s.get("qualityScore", 1.0))) for s in diar_data["segments"]]
        for start, end, speaker, quality in raw:
            if not (all(math.isfinite(v) for v in (start, end, quality)) and 0 <= start <= end
                    and isinstance(speaker, (str, int)) and str(speaker).strip()):
                raise ValueError("некорректный сегмент спикера")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise EngineError("parse", f"некорректные segments: {exc}") from exc
    raw.sort(key=lambda t: t[0])
    label_map = {}
    relabeled = []
    for st, en, spk, quality in raw:
        if spk not in label_map:
            label_map[spk] = f"S{len(label_map) + 1}"
        relabeled.append((st, en, label_map[spk], quality))
    return relabeled, len(label_map)


def _run(cmd: list[str], stage: str, *, cancel: Event | None = None) -> None:
    try:
        if cancel is None:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            try:
                while True:
                    if cancel.is_set():
                        raise EngineError(stage, "обработка отменена")
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                process.kill()
                process.communicate()
                raise
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise EngineError(stage, detail or f"FluidAudio завершился с кодом {exc.returncode}") from exc
    except OSError as exc:
        raise EngineError(stage, f"не удалось запустить FluidAudio: {exc}") from exc
