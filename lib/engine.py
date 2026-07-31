"""Движковый шов: единственный модуль, знающий, как разговаривать с FluidAudio.

Порт Engine.transcribe() — единственный публичный интерфейс. Движковые опции
(model, diar_mode) живут в конструкторе адаптера. За швом: командный контракт
subprocess, обе JSON-схемы, релейблинг S1..Sn, политика языка.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from language import detect_language

Lang = str  # "ru" | "en" | "auto"
Speakers = str  # "auto" | "off" | "N"


class EngineError(Exception):
    """Провал прогона. stage: "asr" | "diar" | "parse"."""

    def __init__(self, stage: str, reason: str):
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason


class EngineUnavailableError(EngineError):
    """Движок недоступен: бинарник не найден или не запускается."""


@dataclass(frozen=True)
class Transcript:
    words: list = field(default_factory=list)        # [{"start", "end", "text"}]
    segments: list = field(default_factory=list)     # [(start, end, "S<n>", quality)]
    speakers: int = 1
    language: str = "auto"
    text: str = ""
    engine: str = ""


class FluidAudioEngine:
    """Адаптер FluidAudio: transcribe() + process() за одним вызовом."""

    def __init__(self, *, binary: Path, model: str = "v3",
                 diar_mode: str = "streaming", runner: Optional[object] = None):
        self.binary = binary
        self.model = model
        self.diar_mode = diar_mode
        self._runner = runner

    def transcribe(self, wav: Path, *, lang: Lang = "auto",
                   speakers: Speakers = "auto",
                   on_stage: Optional[Callable[[str], None]] = None) -> Transcript:
        if on_stage:
            on_stage("asr")
        asr_data = self._run_transcribe(wav, lang)
        words = _normalize_words(asr_data)
        if not words:
            raise EngineError("asr", "ASR вернул пустой результат")

        segments = []
        if speakers != "off":
            if on_stage:
                on_stage("diar")
            diar_data = self._run_process(wav, _num(speakers))
            segments, n_speakers = _normalize_diar(diar_data)
        else:
            n_speakers = 0
        n_speakers = max(n_speakers, 1)

        lang_out = _resolve_language(lang, asr_data.get("language"), asr_data.get("text") or " ".join(w["text"] for w in words))
        multi = n_speakers > 1
        engine = (f"fluidaudio-parakeet-{self.model} + "
                  f"pyannote-{self.diar_mode}" if multi else f"fluidaudio-parakeet-{self.model}")

        return Transcript(words=words, segments=segments, speakers=n_speakers,
                          language=lang_out, text=asr_data.get("text") or "",
                          engine=engine)

    def _run_transcribe(self, wav: Path, lang: str) -> dict:
        out_json = _tmp_json("asr")
        try:
            if self._runner is None:
                SubprocessFluidRunner(self.binary).transcribe(wav, lang, self.model, out_json)
            else:
                self._runner.transcribe(wav, lang, self.model, out_json)
            return _read_json(out_json)
        finally:
            out_json.unlink(missing_ok=True)

    def _run_process(self, wav: Path, num: int) -> dict:
        out_json = _tmp_json("diar")
        try:
            if self._runner is None:
                SubprocessFluidRunner(self.binary).process(wav, self.diar_mode, num, out_json)
            else:
                self._runner.process(wav, self.diar_mode, num, out_json)
            return _read_json(out_json)
        finally:
            out_json.unlink(missing_ok=True)


def _tmp_json(kind: str) -> Path:
    import tempfile
    return Path(tempfile.mkstemp(prefix=f"engine_{kind}_", suffix=".json")[1])


def _read_json(path: Path) -> dict:
    import json
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise EngineError("parse", f"кривой ответ движка: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("parse", "ответ движка не JSON-объект")
    return data


def _num(speakers: str) -> int:
    return int(speakers) if speakers.isdigit() else -1


def _resolve_language(lang: str, engine_lang, text: str) -> str:
    if lang != "auto":
        return lang
    if isinstance(engine_lang, str) and engine_lang.lower() != "auto":
        return engine_lang
    return detect_language(text)


def _normalize_words(asr_data: dict) -> list:
    words = []
    for w in asr_data.get("wordTimings", []):
        words.append({
            "start": float(w.get("startTime", 0.0)),
            "end": float(w.get("endTime", 0.0)),
            "text": w.get("word", ""),
        })
    return words


def _normalize_diar(diar_data: dict) -> tuple:
    raw = []
    for s in diar_data.get("segments", []):
        raw.append((
            float(s.get("startTimeSeconds", 0.0)),
            float(s.get("endTimeSeconds", 0.0)),
            str(s.get("speakerId", "")),
            float(s.get("qualityScore", 1.0)),
        ))
    raw.sort(key=lambda t: t[0])
    label_map, n = {}, 0
    relabeled = []
    for st, en, spk, quality in raw:
        if spk not in label_map:
            n += 1
            label_map[spk] = f"S{n}"
        relabeled.append((st, en, label_map[spk], quality))
    return relabeled, n


class SubprocessFluidRunner:
    """Реальный раннер: единственное место с subprocess."""

    def __init__(self, binary: Path):
        self.binary = binary

    def transcribe(self, wav: Path, lang: str, model: str, out_json: Path) -> None:
        import subprocess
        cmd = [str(self.binary), "transcribe", str(wav), "--word-timestamps",
               "--model-version", model, "--output-json", str(out_json)]
        if lang != "auto":
            cmd += ["--language", lang]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def process(self, wav: Path, mode: str, num: int, out_json: Path) -> None:
        import subprocess
        cmd = [str(self.binary), "process", str(wav), "--mode", mode, "--output", str(out_json)]
        if num > 0:
            cmd += (["--num-clusters", str(num)] if mode == "streaming"
                    else ["--num-speakers", str(num)])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
