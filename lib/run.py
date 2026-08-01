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
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar
from urllib.parse import urlparse

from engine import EngineError, FluidAudioEngine
from merge import merge_words_to_turns

DEFAULT_RTF = 30.0
STALE_S = 60.0
PROGRESS_NAME = "progress.json"
WATCH_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".opus", ".mov", ".mp4"})
WATCH_TEMP_SUFFIXES = frozenset({".part", ".tmp"})
YOUTUBE_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
})
BAD_PATH_CHARS_RE = re.compile(r"[\x00-\x1f/:]+")


def safe_folder_name(name: str, fallback: str = "transcript") -> str:
    """Human-readable folder name, preserving media title where possible."""
    clean = BAD_PATH_CHARS_RE.sub(" - ", name or "")
    clean = re.sub(r"\s+", " ", clean).strip(" .-_")
    return clean[:180] or fallback


def watch_candidate(path: Path, state: dict) -> bool:
    """Return true after a supported media file is unchanged across two polls."""
    path = Path(path)
    if (not path.is_file() or path.name.startswith(".")
            or path.suffix.lower() in WATCH_TEMP_SUFFIXES
            or path.suffix.lower() not in WATCH_EXTENSIONS):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    key = str(path.resolve())
    signature = (stat.st_size, stat.st_mtime_ns)
    stable = state.get(key) == signature
    state[key] = signature
    return stable


def is_processed(source: Path, out_root: Path) -> bool:
    """Return true when a watch output already has a completed manifest."""
    source = Path(source)
    root = Path(out_root)
    base = root / safe_folder_name(source.stem)
    candidates = [base]
    try:
        candidates.extend(sorted(root.glob(f"{base.name}-*")))
    except OSError:
        return False

    for out_dir in candidates:
        manifest_path = out_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("status", "done") != "done":
            continue
        recorded_source = manifest.get("source")
        if recorded_source in (None, source.name, str(source)):
            return True
    return False


def unique_dir(path: Path) -> Path:
    """Return path, or path-2, path-3, ... when path already exists."""
    if not path.exists():
        return path
    parent = path.parent
    stem = path.name
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


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
    workdir: Path | None = None


@dataclass(frozen=True)
class PreparedSource:
    """Prepared source: where to write artifacts and what to transcribe."""
    out_dir: Path
    wav: Path
    duration: float
    source_label: str
    prep_s: float


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
# run() owns the full run. Test seams are _prepare_source (the main source
# preparation seam) and _ENGINE_FACTORY. Prep helpers (_youtube_title,
# _fetch_youtube_audio, _ffprobe_duration, _to_wav16k) stay behind that seam.
# ---------------------------------------------------------------------------

DEFAULT_OUT_ROOT = Path("/Users/sereja/Downloads/transcripts")
FLUID = Path(__file__).resolve().parent.parent / "vendor" / "fluidaudiocli"


@dataclass(frozen=True)
class Manifest:
    """Schema for manifest.json: the single interface for writers and readers.

    Field order in to_dict() also defines the corpus-row order.
    """
    source: str | None
    duration: float | None
    speakers: int | None
    language: str | None
    engine: str | None
    generated: str | None
    out_dir: str | None
    timings_s: dict | None
    asr_rtf: float | None
    asr_model: str | None
    diar_mode: str | None
    speakers_arg: str | None
    words: int | None
    turns: int | None
    engine_binary: str | None
    clean_fillers: bool | None = None
    status: str | None = None
    CORPUS_FIELDS: ClassVar[tuple[str, ...]] = (
        "source", "duration", "speakers", "language", "engine", "generated",
        "out_dir", "asr_rtf", "asr_model", "diar_mode", "speakers_arg",
        "words", "turns", "engine_binary",
    )

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, m: dict) -> "Manifest":
        """Fill missing keys with None so old manifests remain readable."""
        return cls(**{f.name: m.get(f.name) for f in fields(cls)})

    def to_corpus_row(self, manifest_path: Path) -> dict:
        """Project run fields, timings, and measured RTF into one corpus row."""
        row = {name: getattr(self, name) for name in self.CORPUS_FIELDS}
        t = self.timings_s or {}
        for k in ("prep_s", "asr_s", "diar_s"):
            row[k] = t.get(k)
        if self.duration and row.get("asr_s"):
            row["measured_rtf"] = round(self.duration / row["asr_s"], 2)
        row["manifest_path"] = str(manifest_path)
        return row


def _youtube_title(url: str) -> str:
    if not shutil.which("yt-dlp"):
        raise RunError("для YouTube нужен yt-dlp (brew install yt-dlp)")
    try:
        title = subprocess.run(
            ["yt-dlp", "--skip-download", "--print", "%(title)s", url],
            check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = (getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or "").strip()
        raise RunError(f"не удалось получить название YouTube-видео: {msg or url}") from exc
    return title


def _fetch_youtube_audio(url: str, workdir: Path) -> Path:
    if not shutil.which("yt-dlp"):
        raise RunError("для YouTube нужен yt-dlp (brew install yt-dlp)")
    out_tmpl = str(workdir / "yt_audio.%(ext)s")
    try:
        subprocess.run(["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "m4a",
                        "-o", out_tmpl, url], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = (getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or "").strip()
        raise RunError(f"yt-dlp не скачал аудио: {msg or url}") from exc
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
    except Exception as exc:
        detail = (getattr(exc, "stderr", "") or "").strip()[:200]
        raise RunError(f"ffprobe не смог прочитать аудио {path}: {detail or exc}") from exc


def _to_wav16k(src: Path, dst: Path):
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-ar", "16000", "-ac", "1", str(dst)],
                       check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = (getattr(exc, "stderr", "") or "").strip()[:300]
        raise RunError(f"ffmpeg не смог сконвертировать аудио: {msg or src}") from exc


def _is_youtube_url(source: str) -> bool:
    """Return true only for supported YouTube hostnames and web schemes."""
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme.lower() in {"http", "https"} and host in YOUTUBE_HOSTS


def _prepare_source(source, *, out: Path | None, out_root: Path | None,
                    workdir: Path,
                    on_out_dir: Callable[[Path], None] | None = None,
                    on_src_duration: Callable[[float], None] | None = None) -> PreparedSource:
    """Prepare a source into an output directory and audio_16k.wav.

    Owns local/YouTube branching, directory naming, and the full audio
    chain (yt-dlp, ffprobe, ffmpeg); failures are reported as RunError.
    on_out_dir runs after naming and before fetch so the tracker exists before
    the long download; on_src_duration runs after probing the source and
    before conversion so prep ETA can use the duration.
    """
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RunError(f"требуется {tool}")

    t0 = time.time()
    source_text = str(source)
    is_url = "://" in source_text
    is_youtube = is_url and _is_youtube_url(source_text)
    if is_url and not is_youtube:
        raise RunError("поддерживаются локальные файлы и YouTube-ссылки")
    if not is_url and not Path(source).exists():
        raise RunError(f"файл не найден: {source}")

    if out is not None:
        out_dir = Path(out)
    elif is_youtube:
        title = _youtube_title(str(source))
        out_dir = unique_dir(Path(out_root) / safe_folder_name(title, "youtube"))
    else:
        out_dir = unique_dir(Path(out_root) / safe_folder_name(Path(source).stem))
    if on_out_dir is not None:
        on_out_dir(out_dir)

    src = _fetch_youtube_audio(str(source), workdir) if is_youtube else Path(source)
    wav = workdir / "audio_16k.wav"
    src_duration = _ffprobe_duration(src)
    if on_src_duration is not None:
        on_src_duration(src_duration)
    _to_wav16k(src, wav)
    duration = _ffprobe_duration(wav)
    prep_s = round(time.time() - t0, 1)
    return PreparedSource(out_dir=out_dir, wav=wav, duration=duration,
                          source_label=str(source) if is_youtube else Path(source).name,
                          prep_s=prep_s)


def _load_last_rtf(out_root: Path) -> float:
    """Калибровка ETA для ASR: RTF из самого свежего прошлого manifest.json."""
    best = None
    for m in out_root.rglob("manifest.json"):
        try:
            rtf = Manifest.from_dict(json.loads(m.read_text())).asr_rtf
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


def _clear_run_markers(out_dir: Path) -> None:
    """Remove markers from an explicit output before starting a new run."""
    for name in ("manifest.json", PROGRESS_NAME):
        try:
            (out_dir / name).unlink()
        except FileNotFoundError:
            pass


def run(input, *, out: Path | None = None, out_root: Path | None = None,
        speakers: str = "auto", lang: str = "auto", diar_mode: str = "streaming",
        asr_model: str = "v3", keep_tmp: bool = False,
        clean_fillers: bool = False) -> RunResult:
    """Полный прогон: preflight → prep → asr → диаризация → merge → артефакты."""
    if not FLUID.exists():
        raise RunError(f"не найден движок: {FLUID}")
    if out is None and out_root is None:
        raise RunError("укажите --out или --out-root")
    if out is not None:
        _clear_run_markers(Path(out))

    workdir = Path(tempfile.mkdtemp(prefix="transcribe_"))
    timings = {}
    tracker = None
    try:
        def _on_out_dir(out_dir: Path):
            nonlocal tracker
            out_dir.mkdir(parents=True, exist_ok=True)
            tracker = _Tracker(out_dir / PROGRESS_NAME, str(input))
            tracker.set(stage="prep")
            tracker.start()

        prepared = _prepare_source(str(input), out=out, out_root=out_root,
                                   workdir=workdir,
                                   on_out_dir=_on_out_dir,
                                   on_src_duration=lambda d: tracker.set(duration=d))
        out_dir = prepared.out_dir
        timings["prep_s"] = prepared.prep_s
        duration = prepared.duration

        tracker.set(duration=duration, rtf=_load_last_rtf(out_dir.parent))
        engine = _ENGINE_FACTORY(FLUID, asr_model, diar_mode)
        result = engine.transcribe(prepared.wav, lang=lang, speakers=speakers,
                                   on_stage=lambda s: tracker.set(stage=s))
        timings["asr_s"] = round(result.timings.asr_s, 1)
        timings["diar_s"] = (round(result.timings.diar_s, 1)
                             if result.timings.diar_s is not None else None)
        words = result.words
        n_speakers = max(result.speakers, 1)
        multi = n_speakers > 1

        tracker.set(stage="merge")
        turns = merge_words_to_turns(words, result.segments,
                                     clean_fillers=clean_fillers,
                                     lang=result.language)

        generated = _now_iso()
        meta = {"source": prepared.source_label, "duration": duration,
                "speakers": n_speakers, "language": result.language,
                "engine": result.engine, "generated": generated,
                "clean_fillers": clean_fillers}

        (out_dir / "transcript.md").write_text(_render_md(meta, turns, multi))
        (out_dir / "transcript.json").write_text(json.dumps(
            {**meta, "turns": turns, "words": words}, ensure_ascii=False, indent=2))

        rtf = (round(duration / timings["asr_s"], 1)
               if duration > 0 and timings["asr_s"] > 0 else None)
        manifest = Manifest(**meta, out_dir=str(out_dir), timings_s=timings,
                            asr_rtf=rtf, asr_model=asr_model,
                            diar_mode=result.diar_mode, speakers_arg=speakers,
                            words=len(words), turns=len(turns),
                            engine_binary=str(FLUID), status="done")
        (out_dir / "manifest.json").write_text(json.dumps(
            manifest.to_dict(), ensure_ascii=False, indent=2))

        tracker.finish("done", out_dir=str(out_dir), speakers=n_speakers,
                       language=result.language, duration=duration, pct=100, eta_s=0,
                       transcript_md=str(out_dir / "transcript.md"))

        return RunResult(out_dir=out_dir,
                         transcript_md=out_dir / "transcript.md",
                         transcript_json=out_dir / "transcript.json",
                         manifest=out_dir / "manifest.json",
                         speakers=n_speakers, duration_s=duration,
                         asr_rtf=rtf, language=result.language,
                         workdir=(workdir if keep_tmp else None))
    except EngineError as exc:
        if tracker is not None:
            tracker.finish("error", error=str(exc))
        raise RunError(str(exc)) from exc
    except Exception as exc:
        if tracker is not None:
            tracker.finish("error", error=str(exc))
        raise
    finally:
        if not keep_tmp:
            shutil.rmtree(workdir, ignore_errors=True)
