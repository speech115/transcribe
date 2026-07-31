"""Прогон транскрибации: run() и status() — два пути одного глубокого модуля.

run() владеет всем контрактом прогона: стадии, ETA, live-трейсинг в
progress.json, калибровка RTF по прошлым прогонам, артефакты
(transcript.md / transcript.json / manifest.json), финализация.
status() читает progress.json и отдаёт одно из: running | done | error |
idle | degraded. Оболочка bin/transcribe не знает ни имён файлов, ни стадий.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine import EngineError, FluidAudioEngine
from merge import merge_words_to_turns
from naming import safe_folder_name, unique_dir

DEFAULT_RTF = 30.0
STALE_S = 60.0
PROGRESS_NAME = "progress.json"
YT_RE = re.compile(r"(youtube\.com|youtu\.be)", re.I)


class RunError(Exception):
    """Любая ошибка прогона; сообщение готово для stderr. Код выхода 1."""


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    transcript_md: Path
    transcript_json: Path
    manifest: Path
    speakers: int
    duration_s: float
    asr_rtf: float | None
    language: str


@dataclass(frozen=True)
class Status:
    kind: str                      # running | done | error | idle | degraded
    out_dir: Path | None = None
    source: str | None = None
    stage: str | None = None
    pct: float | None = None
    eta_s: float | None = None
    elapsed_s: float | None = None
    speakers: int | None = None
    duration_s: float | None = None
    transcript_md: Path | None = None
    error: str | None = None


def format_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def status(out_dir: Path | None = None, *, out_root: Path | None = None,
           max_age_s: float = STALE_S) -> Status:
    """Статус прогона. out_dir приоритетнее out_root (рекурсивный поиск)."""
    candidates = []
    if out_dir is not None:
        p = Path(out_dir) / PROGRESS_NAME
        if p.exists():
            candidates.append(p)
    elif out_root is not None:
        try:
            candidates = sorted(Path(out_root).rglob(PROGRESS_NAME),
                                key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            candidates = []

    broken: Path | None = None
    for c in candidates:
        try:
            state = json.loads(c.read_text())
        except Exception:
            broken = broken or c
            continue
        age = time.time() - c.stat().st_mtime
        if state.get("status") == "running" and age > max_age_s:
            continue
        return _from_state(c.parent, state)
    if broken is not None:
        return Status(kind="degraded", out_dir=broken.parent,
                      error="progress.json повреждён")
    return Status(kind="idle")


def _from_state(out_dir: Path, state: dict) -> Status:
    kind = state.get("status", "running")
    if kind not in ("running", "done", "error"):
        kind = "running"
    return Status(kind=kind, out_dir=out_dir,
                  source=state.get("source"),
                  stage=state.get("stage"),
                  pct=state.get("pct"),
                  eta_s=state.get("eta_s"),
                  elapsed_s=state.get("elapsed_s"),
                  speakers=state.get("speakers"),
                  duration_s=state.get("duration"),
                  transcript_md=(Path(state["transcript_md"])
                                 if state.get("transcript_md") else None),
                  error=state.get("error"))


def status_line(st: Status) -> str:
    if st.kind == "idle":
        return "нет активного прогона транскрибации"
    if st.kind == "degraded":
        return f"⚠ progress.json повреждён: {st.out_dir / PROGRESS_NAME}"
    if st.kind == "done":
        bits = ["✓ готово"]
        if st.speakers:
            bits.append(f"{st.speakers} спикер(ов)")
        if st.duration_s:
            bits.append(format_duration(st.duration_s))
        bits.append(f"elapsed {format_duration(st.elapsed_s or 0)}")
        if st.transcript_md:
            bits.append(str(st.transcript_md))
        return " · ".join(bits)
    if st.kind == "error":
        return f"✗ ошибка: {st.error or 'см. progress.json'}"
    label = _stage_label(st.stage, st.pct)
    parts = [label]
    if isinstance(st.eta_s, (int, float)):
        parts.append(f"ETA {format_duration(st.eta_s)}")
    parts.append(f"elapsed {format_duration(st.elapsed_s or 0)}")
    if st.source:
        parts.append(st.source)
    return "🎙 " + " · ".join(parts)


def _stage_label(stage: str | None, pct) -> str:
    if stage == "prep":
        return f"конвертация {round(pct)}%" if isinstance(pct, (int, float)) else "конвертация"
    if stage == "asr":
        return f"ASR {round(pct)}%" if isinstance(pct, (int, float)) else "ASR"
    if stage == "diar":
        return "диаризация"
    if stage == "merge":
        return "сборка"
    return stage or ""


def status_dict(st: Status) -> dict:
    if st.kind == "idle":
        return {"status": "idle"}
    if st.kind == "degraded":
        return {"status": "degraded", "path": str(st.out_dir / PROGRESS_NAME)}
    return {"status": st.kind, "out_dir": str(st.out_dir),
            "source": st.source, "stage": st.stage, "pct": st.pct,
            "eta_s": st.eta_s, "elapsed_s": st.elapsed_s,
            "speakers": st.speakers, "duration": st.duration_s,
            "transcript_md": str(st.transcript_md) if st.transcript_md else None,
            "error": st.error}


# ---------------------------------------------------------------------------
# run() — полный прогон. Внутренние швы для тестов: _ENGINE_FACTORY,
# _ffprobe_duration, _to_wav16k, _fetch_youtube_audio, _youtube_title.
# ---------------------------------------------------------------------------

DEFAULT_OUT_ROOT = Path("/Users/sereja/Downloads/transcripts")
FLUID = Path(__file__).resolve().parent.parent / "vendor" / "fluidaudiocli"


def _youtube_title(url: str) -> str:
    if not shutil.which("yt-dlp"):
        raise RunError("для YouTube нужен yt-dlp (brew install yt-dlp)")
    try:
        title = subprocess.run(
            ["yt-dlp", "--skip-download", "--print", "%(title)s", url],
            check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip()
        raise RunError(f"не удалось получить название YouTube-видео: {msg or url}") from exc
    return title


def _fetch_youtube_audio(url: str, workdir: Path) -> Path:
    if not shutil.which("yt-dlp"):
        raise RunError("для YouTube нужен yt-dlp (brew install yt-dlp)")
    out_tmpl = str(workdir / "yt_audio.%(ext)s")
    subprocess.run(["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "m4a",
                    "-o", out_tmpl, url], check=True, capture_output=True, text=True)
    files = list(workdir.glob("yt_audio.*"))
    if not files:
        raise RunError("yt-dlp не скачал аудио")
    return files[0]


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-loglevel", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _to_wav16k(src: Path, dst: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-ar", "16000", "-ac", "1", str(dst)],
                   check=True, capture_output=True, text=True)


def _load_last_rtf(out_root: Path) -> float:
    """Калибровка ETA для ASR: RTF из самого свежего прошлого manifest.json."""
    best = None
    for m in out_root.rglob("manifest.json"):
        try:
            rtf = json.loads(m.read_text()).get("asr_rtf")
        except Exception:
            continue
        if isinstance(rtf, (int, float)) and rtf > 0:
            ts = m.stat().st_mtime
            if best is None or ts > best[1]:
                best = (rtf, ts)
    return best[0] if best else DEFAULT_RTF


def _ENGINE_FACTORY(binary: Path, model: str, diar_mode: str) -> FluidAudioEngine:
    return FluidAudioEngine(binary=binary, model=model, diar_mode=diar_mode)


class _Tracker:
    """Live-трейсинг прогона в progress.json. Терминальный статус липкий."""

    STAGES = ("prep", "asr", "diar", "merge")

    def __init__(self, path: Path, source: str):
        self.path = path
        self.state = {
            "source": source, "status": "running", "stage": "init",
            "pct": None, "eta_s": None, "elapsed_s": 0,
            "pid": os.getpid(), "started_at": _now_iso(), "updated_at": _now_iso(),
        }
        self._stop = threading.Event()
        self._t0 = time.time()
        self._lock = threading.RLock()

    def set(self, **kw):
        with self._lock:
            self.state.update(kw)
            self.state["updated_at"] = _now_iso()

    def start(self, interval: float = 2.0):
        self._write()
        threading.Thread(target=self._loop, args=(interval,), daemon=True).start()

    def _write(self):
        with self._lock:
            payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".json.tmp")
        try:
            tmp.write_text(payload)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _loop(self, interval):
        while not self._stop.wait(interval):
            with self._lock:
                self.state["elapsed_s"] = round(time.time() - self._t0, 1)
                self.state["pct"], self.state["eta_s"] = self._estimate()
            self._write()

    def _estimate(self):
        stage = self.state.get("stage")
        elapsed = self.state.get("elapsed_s") or 0
        duration = self.state.get("duration") or 0
        if stage == "prep" and duration > 0:
            total = duration / 20.0
        elif stage == "asr" and duration > 0:
            total = duration / (self.state.get("rtf") or DEFAULT_RTF)
        else:
            return None, None
        if total <= 0:
            return None, None
        return min(99.0, elapsed / total * 100), max(0.0, total - elapsed)

    def finish(self, status: str, **kw):
        with self._lock:
            self._stop.set()
            self.state["elapsed_s"] = round(time.time() - self._t0, 1)
            self.state.update(status=status, **kw)
            self.state["updated_at"] = _now_iso()
            payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".json.tmp")
        try:
            tmp.write_text(payload)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hhmmss(sec: float) -> str:
    return format_duration(sec)


def _render_md(meta: dict, turns: list, multi: bool) -> str:
    fm = [
        "---",
        f"source: {meta['source']}",
        f"duration: {_hhmmss(meta['duration'])}",
        f"speakers: {meta['speakers']}",
        f"language: {meta['language']}",
        f"engine: {meta['engine']}",
        f"generated: {meta['generated']}",
        "---",
        "",
    ]
    body = []
    for t in turns:
        ts = _hhmmss(t["start"])
        if multi and t["speaker"]:
            body.append(f"**[{ts} · {t['speaker']}]** {t['text']}")
        else:
            body.append(f"**[{ts}]** {t['text']}")
        body.append("")
    return "\n".join(fm + body).rstrip() + "\n"


def run(input, *, out: Path | None = None, out_root: Path | None = None,
        speakers: str = "auto", lang: str = "auto", diar_mode: str = "streaming",
        asr_model: str = "v3", keep_tmp: bool = False) -> RunResult:
    """Полный прогон: preflight → prep → asr → диаризация → merge → артефакты."""
    if not FLUID.exists():
        raise RunError(f"не найден движок: {FLUID}")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RunError(f"требуется {tool}")
    if out is None and out_root is None:
        raise RunError("укажите --out или --out-root")

    is_url = "://" in str(input)
    is_youtube = is_url and YT_RE.search(str(input))
    if is_url and not is_youtube:
        raise RunError("поддерживаются локальные файлы и YouTube-ссылки")
    if not is_url and not Path(input).exists():
        raise RunError(f"файл не найден: {input}")

    if out is not None:
        out_dir = Path(out)
    elif is_youtube:
        out_dir = unique_dir(Path(out_root) / safe_folder_name(_youtube_title(str(input)), "youtube"))
    else:
        out_dir = unique_dir(Path(out_root) / safe_folder_name(Path(input).stem))
    out_dir.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="transcribe_"))
    timings = {}
    try:
        progress = _Tracker(out_dir / PROGRESS_NAME, str(input))
        progress.set(stage="prep")
        progress.start()

        src = _fetch_youtube_audio(str(input), workdir) if is_youtube else Path(input)
        wav = workdir / "audio_16k.wav"
        t0 = time.time()
        progress.set(duration=_ffprobe_duration(src))
        _to_wav16k(src, wav)
        timings["prep_s"] = round(time.time() - t0, 1)
        duration = _ffprobe_duration(wav)

        t0 = time.time()
        progress.set(stage="asr", duration=duration, rtf=_load_last_rtf(out_dir.parent))
        engine = _ENGINE_FACTORY(FLUID, asr_model, diar_mode)
        stage_marks = []
        result = engine.transcribe(wav, lang=lang, speakers=speakers,
                                   on_stage=lambda s: stage_marks.append((s, time.time())))
        elapsed = time.time() - t0
        asr_s = stage_marks[0][1] - t0 if len(stage_marks) > 1 else elapsed
        timings["asr_s"] = round(asr_s, 1)
        timings["diar_s"] = (round(elapsed - (stage_marks[1][1] - t0), 1)
                             if len(stage_marks) > 1 else None)
        if duration > 0 and timings["asr_s"] > 0:
            progress.set(rtf=round(duration / timings["asr_s"], 1))
        words = result.words
        n_speakers = max(result.speakers, 1)
        multi = n_speakers > 1

        progress.set(stage="merge")
        turns = merge_words_to_turns(words, result.segments)

        generated = _now_iso()
        meta = {"source": (str(input) if is_youtube else Path(input).name),
                "duration": duration, "speakers": n_speakers,
                "language": result.language, "engine": result.engine,
                "generated": generated}

        (out_dir / "transcript.md").write_text(_render_md(meta, turns, multi))
        (out_dir / "transcript.json").write_text(json.dumps(
            {**meta, "turns": turns, "words": words}, ensure_ascii=False, indent=2))

        rtf = round(duration / timings.get("asr_s", 1), 1) if timings.get("asr_s") else None
        manifest = {**meta, "out_dir": str(out_dir), "timings_s": timings,
                    "asr_rtf": rtf, "asr_model": asr_model,
                    "diar_mode": (diar_mode if multi or speakers != "off" else None),
                    "speakers_arg": speakers, "words": len(words), "turns": len(turns),
                    "engine_binary": str(FLUID)}
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

        progress.finish("done", out_dir=str(out_dir), speakers=n_speakers,
                        language=result.language, duration=duration, pct=100, eta_s=0,
                        transcript_md=str(out_dir / "transcript.md"))

        return RunResult(out_dir=out_dir,
                         transcript_md=out_dir / "transcript.md",
                         transcript_json=out_dir / "transcript.json",
                         manifest=out_dir / "manifest.json",
                         speakers=n_speakers, duration_s=duration,
                         asr_rtf=rtf, language=result.language)
    except EngineError as exc:
        progress.finish("error", error=str(exc))
        raise RunError(str(exc)) from exc
    except Exception:
        progress.finish("error", error="см. traceback")
        raise
    finally:
        if not keep_tmp:
            shutil.rmtree(workdir, ignore_errors=True)
