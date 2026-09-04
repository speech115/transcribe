"""Движковый шов: единственный модуль, знающий, как разговаривать с FluidAudio.

Порт Engine.transcribe() — единственный публичный интерфейс. Движковые опции
(model, diar_mode) живут в конструкторе адаптера. За швом: командный контракт
subprocess, обе JSON-схемы, релейблинг S1..Sn, политика языка.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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
    if lat / total >= .5:
        return "en"
    return "auto"

Lang = str  # "ru" | "en" | "auto"
Speakers = str  # "auto" | "off" | "N"


class EngineError(Exception):
    """Провал прогона. stage: "asr" | "diar" | "parse"."""

    def __init__(self, stage: str, reason: str):
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class Transcript:
    words: list = field(default_factory=list)        # [{"start", "end", "text"}]
    segments: list = field(default_factory=list)     # [(start, end, "S<n>", quality)]
    speakers: int = 1
    language: str = "auto"
    text: str = ""
    engine: str = ""
    asr_s: float = 0.0
    diar_s: float | None = None
    diar_mode: str | None = None


class FluidAudioEngine:
    """Адаптер FluidAudio: transcribe() + process() за одним вызовом."""

    def __init__(self, *, binary: Path, model: str = "v3",
                 diar_mode: str = "streaming"):
        self.binary = binary
        self.model = model
        self.diar_mode = diar_mode

    def transcribe(self, wav: Path, *, lang: Lang = "auto",
                   speakers: Speakers = "auto",
                   on_stage: Optional[Callable[[str], None]] = None) -> Transcript:
        if on_stage:
            on_stage("asr")
        t0_asr = time.time()
        asr_data = self._run_transcribe(wav, lang)
        asr_s = time.time() - t0_asr
        words = _normalize_words(asr_data)
        if not words:
            raise EngineError("asr", "ASR вернул пустой результат")

        segments = []
        diar_s = None
        diar_run = False
        if speakers != "off":
            if on_stage:
                on_stage("diar")
            t0_diar = time.time()
            diar_data = self._run_process(wav, _num(speakers))
            diar_s = time.time() - t0_diar
            diar_run = True
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
                          engine=engine,
                          asr_s=asr_s, diar_s=diar_s,
                          diar_mode=(self.diar_mode if diar_run else None))

    def _run_transcribe(self, wav: Path, lang: str) -> dict:
        out_json = _tmp_json("asr")
        try:
            cmd = [str(self.binary), "transcribe", str(wav), "--word-timestamps", "--model-version", self.model, "--output-json", str(out_json)]
            if lang != "auto": cmd += ["--language", lang]
            _run(cmd, "asr")
            return _read_json(out_json)
        finally:
            out_json.unlink(missing_ok=True)

    def _run_process(self, wav: Path, num: int) -> dict:
        out_json = _tmp_json("diar")
        try:
            cmd = [str(self.binary), "process", str(wav), "--mode", self.diar_mode, "--output", str(out_json)]
            if num > 0:
                cmd += (["--num-clusters", str(num)] if self.diar_mode == "streaming" else ["--num-speakers", str(num)])
            _run(cmd, "diar")
            return _read_json(out_json)
        finally:
            out_json.unlink(missing_ok=True)


def _tmp_json(kind: str) -> Path:
    import tempfile
    with tempfile.NamedTemporaryFile(prefix=f"engine_{kind}_", suffix=".json", delete=False) as tmp:
        return Path(tmp.name)


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


def _run(cmd: list[str], stage: str) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise EngineError(stage, detail or f"FluidAudio завершился с кодом {exc.returncode}") from exc
    except OSError as exc:
        raise EngineError(stage, f"не удалось запустить FluidAudio: {exc}") from exc
