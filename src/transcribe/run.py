"""Foreground transcription run and artifact generation."""
import json
import re
import shutil
import subprocess
import tempfile
import time
import wave
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from .engine import EngineError, FluidAudioEngine

YT_RE = re.compile(r"(youtube\.com|youtu\.be)", re.I)
BAD_PATH_CHARS_RE = re.compile(r"[\x00-\x1f/:]+")


def safe_folder_name(name: str, fallback: str = "transcript") -> str:
    """Human-readable folder name, preserving media title where possible."""
    clean = BAD_PATH_CHARS_RE.sub(" - ", name or "")
    clean = re.sub(r"\s+", " ", clean).strip(" .-_")
    return clean[:180] or fallback


def unique_dir(path: Path) -> Path:
    """Return path, or path (2), path (3), ... when path already exists."""
    if not path.exists():
        return path
    parent = path.parent
    stem = path.name
    index = 2
    while True:
        candidate = parent / f"{stem} ({index})"
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
    language: str
    workdir: Path | None = None
    subtitle_paths: tuple[Path, ...] = ()


def format_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


DEFAULT_OUT_ROOT = Path.home() / "Downloads" / "transcripts"
_REPO_FLUID = Path(__file__).resolve().parents[2] / "vendor" / "fluidaudiocli"
FLUID = _REPO_FLUID if _REPO_FLUID.exists() else Path(sys.prefix) / "share" / "transcribe" / "vendor" / "fluidaudiocli"


def assign_speaker(w_start: float, w_end: float, diar: list, max_nearest_gap: float = 5.0) -> str | None:
    word_dur = max(w_end - w_start, 0.001)
    overlaps, best, best_ov = [], None, 0.0
    for seg in diar:
        s, e, spk = seg[:3]
        quality = float(seg[3]) if len(seg) > 3 else 1.0
        ov = min(w_end, e) - max(w_start, s)
        if ov > best_ov:
            best_ov, best = ov, spk
        if ov > 0:
            overlaps.append((ov / word_dur, quality, ov, spk))
    if overlaps:
        significant = [item for item in overlaps if item[0] >= 0.35]
        if significant:
            return max(significant, key=lambda item: (item[1], item[0], item[2]))[3]
    if best is not None:
        return best
    nearest, nearest_gap = None, max_nearest_gap
    for seg in diar:
        s, e, spk = seg[:3]
        gap = s - w_end if w_end < s else w_start - e if w_start > e else 0.0
        if gap <= nearest_gap:
            nearest_gap, nearest = gap, spk
    return nearest


def merge_words_to_turns(words: list, diar: list, max_gap: float = 1.5, max_chars: int = 600) -> list[dict]:
    turns = []
    for word in words:
        speaker = assign_speaker(word["start"], word["end"], diar) if diar else None
        last = turns[-1] if turns else None
        if (last is not None and last["speaker"] == speaker
                and word["start"] - last["end"] <= max_gap
                and len(last["text"]) < max_chars):
            last["text"] += ("" if last["text"].endswith(" ") else " ") + word["text"].strip()
            last["end"] = word["end"]
        else:
            turns.append({"speaker": speaker, "start": word["start"], "end": word["end"],
                          "text": word["text"].strip()})
    return turns


def _fetch_youtube_audio(url: str, workdir: Path) -> tuple[Path, str]:
    if not shutil.which("yt-dlp"):
        raise RunError("для YouTube нужен yt-dlp (brew install yt-dlp)")
    out_tmpl = str(workdir / "yt_audio.%(ext)s")
    result = _run_checked_tool(
        ["yt-dlp", "--no-simulate", "--print", "after_move:%(title)s",
         "-f", "bestaudio", "-o", out_tmpl, url],
        "yt-dlp не смог скачать аудио")
    files = list(workdir.glob("yt_audio.*"))
    if not files:
        raise RunError("yt-dlp не скачал аудио")
    title = next((line.strip() for line in reversed(result.stdout.splitlines()) if line.strip()), "youtube")
    return files[0], title


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / wav.getframerate()
    except Exception:
        return 0.0


def _to_wav16k(src: Path, dst: Path):
    _run_checked_tool(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-ar", "16000", "-ac", "1", str(dst)],
        "ffmpeg не смог подготовить аудио")


def _run_checked_tool(command: list[str], label: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RunError(f"{label}: {detail or 'команда завершилась с ошибкой'}") from exc
    except OSError as exc:
        raise RunError(f"{label}: {exc}") from exc


def _render_md(meta: dict, turns: list, multi: bool) -> str:
    fm = [
        "---",
        f"source: {meta['source']}",
        f"duration: {format_duration(meta['duration'])}",
        f"speakers: {meta['speakers']}",
        f"language: {meta['language']}",
        f"engine: {meta['engine']}",
        f"generated: {meta['generated']}",
        "---",
        "",
    ]
    body = []
    for t in turns:
        ts = format_duration(t["start"])
        if multi and t["speaker"]:
            body.append(f"**[{ts} · {t['speaker']}]** {t['text']}")
        else:
            body.append(f"**[{ts}]** {t['text']}")
        body.append("")
    return "\n".join(fm + body).rstrip() + "\n"


def _subtitle_timestamp(sec: float, separator: str) -> str:
    """Render a non-negative timestamp with millisecond precision."""
    total_ms = max(0, int(round(float(sec) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _render_subtitles(turns: list, multi: bool, fmt: str) -> str:
    separator = "," if fmt == "srt" else "."
    blocks = []
    for index, turn in enumerate(turns, 1):
        timing = (f"{_subtitle_timestamp(turn['start'], separator)} --> "
                  f"{_subtitle_timestamp(turn['end'], separator)}")
        text = turn["text"].strip()
        if multi:
            text = f"{turn.get('speaker') or 'UNKNOWN'}: {text}"
        if fmt == "srt":
            blocks.append(f"{index}\n{timing}\n{text}")
        else:
            blocks.append(f"{timing}\n{text}")
    if fmt == "vtt":
        return "WEBVTT\n\n" + ("\n\n".join(blocks) + "\n" if blocks else "")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def normalize_formats(formats) -> tuple[str, ...]:
    """Normalize and validate optional subtitle formats for the run contract."""
    if formats is None:
        return ()
    if isinstance(formats, str):
        formats = formats.split(",")
    normalized = tuple(dict.fromkeys(
        str(fmt).strip().lower() for fmt in formats if str(fmt).strip()))
    invalid = [fmt for fmt in normalized if fmt not in {"srt", "vtt"}]
    if invalid:
        raise RunError(f"unsupported subtitle format: {', '.join(invalid)}")
    return normalized


def run(input, *, out: Path | None = None, out_root: Path | None = None,
        speakers: str = "auto", lang: str = "auto", diar_mode: str = "streaming",
        asr_model: str = "v3", keep_tmp: bool = False, formats=(),
        overwrite: bool = False, on_stage: Callable[[str], None] | None = None) -> RunResult:
    """Полный прогон: preflight → prep → asr → диаризация → merge → артефакты."""
    subtitle_formats = normalize_formats(formats)
    if not FLUID.exists():
        raise RunError(f"не найден движок: {FLUID}")
    if not shutil.which("ffmpeg"):
        raise RunError("требуется ffmpeg")
    if out is None and out_root is None:
        raise RunError("укажите --out или --out-root")

    is_url = "://" in str(input)
    is_youtube = is_url and YT_RE.search(str(input))
    if is_url and not is_youtube:
        raise RunError("поддерживаются локальные файлы и YouTube-ссылки")
    if not is_url and not Path(input).exists():
        raise RunError(f"файл не найден: {input}")

    source_path = None if is_youtube else Path(input).resolve()

    workdir = Path(tempfile.mkdtemp(prefix="transcribe_"))
    timings = {}
    total_t0 = time.time()
    try:
        if on_stage:
            on_stage("preparing")
        if is_youtube:
            src, title = _fetch_youtube_audio(str(input), workdir)
        else:
            src = Path(input)
            title = Path(input).stem
        out_dir = (Path(out) if out is not None else
                   unique_dir(Path(out_root) / safe_folder_name(title, "youtube" if is_youtube else "transcript")))
        if out is not None and not overwrite:
            standard = (out_dir / "transcript.md", out_dir / "transcript.json", out_dir / "manifest.json")
            if any(path.exists() for path in standard):
                raise RunError("output already exists; use --overwrite")
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = workdir / "audio_16k.wav"
        t0 = time.time()
        _to_wav16k(src, wav)
        timings["prep_s"] = round(time.time() - t0, 1)
        duration = _wav_duration(wav)

        engine = FluidAudioEngine(binary=FLUID, model=asr_model, diar_mode=diar_mode)
        result = engine.transcribe(wav, lang=lang, speakers=speakers, on_stage=on_stage)
        timings["asr_s"] = round(result.asr_s, 1)
        timings["diar_s"] = (round(result.diar_s, 1)
                             if result.diar_s is not None else None)
        words = result.words
        n_speakers = max(result.speakers, 1)
        multi = n_speakers > 1

        turns = merge_words_to_turns(words, result.segments)

        generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = {"source": (str(input) if is_youtube else Path(input).name),
                "source_path": (None if source_path is None else str(source_path)),
                "duration": duration,
                "speakers": n_speakers, "language": result.language,
                "engine": result.engine, "generated": generated,
                "subtitle_formats": list(subtitle_formats)}

        if on_stage:
            on_stage("writing")
        (out_dir / "transcript.md").write_text(_render_md(meta, turns, multi))
        (out_dir / "transcript.json").write_text(json.dumps(
            {**meta, "turns": turns, "words": words}, ensure_ascii=False, indent=2))
        for stale_fmt in ("srt", "vtt"):
            if stale_fmt not in subtitle_formats:
                (out_dir / f"transcript.{stale_fmt}").unlink(missing_ok=True)
        subtitle_paths = []
        for fmt in subtitle_formats:
            subtitle_path = out_dir / f"transcript.{fmt}"
            subtitle_path.write_text(_render_subtitles(turns, multi, fmt))
            subtitle_paths.append(subtitle_path)

        rtf = (round(duration / timings["asr_s"], 1)
               if duration > 0 and timings["asr_s"] > 0 else None)
        manifest = {**meta, "out_dir": str(out_dir), "timings_s": timings,
                    "asr_rtf": rtf, "asr_model": asr_model,
                    "diar_mode": result.diar_mode,
                    "speakers_arg": speakers, "words": len(words), "turns": len(turns),
                    "engine_binary": str(FLUID)}
        timings["total_s"] = round(time.time() - total_t0, 1)
        manifest["diarization"] = {
            "requested": speakers != "off",
            "status": result.diar_status,
            "fallback": "single-speaker" if result.diar_status == "failed" else None,
            "error": result.diar_error,
        }
        (out_dir / "manifest.json").write_text(json.dumps(
            manifest, ensure_ascii=False, indent=2))

        return RunResult(out_dir=out_dir,
                         transcript_md=out_dir / "transcript.md",
                         transcript_json=out_dir / "transcript.json",
                         manifest=out_dir / "manifest.json",
                         speakers=n_speakers, duration_s=duration,
                         language=result.language,
                         workdir=(workdir if keep_tmp else None),
                         subtitle_paths=tuple(subtitle_paths))
    except EngineError as exc:
        raise RunError(str(exc)) from exc
    finally:
        if not keep_tmp:
            shutil.rmtree(workdir, ignore_errors=True)
