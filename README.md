# transcribe

Local offline transcription CLI with speaker diarization for macOS (Apple
Silicon), plus the agent skill definition (`SKILL.md`) that drives it in
Claude Code / Codex / opencode.

Engine: FluidAudio Parakeet TDT v3 (ASR, on Apple Neural Engine) + pyannote
diarization, vendored as a single binary. Sources: local media files and
YouTube (`yt-dlp`). 100% local after model cache; no cloud.

## Install

```bash
git clone https://github.com/speech115/transcribe.git ~/Projects/tools/transcribe
ln -s ~/Projects/tools/transcribe ~/.agents/skills/transcribe   # skill for agents
```

The CLI is expected in `PATH` as `transcribe`; symlink it if needed:

```bash
ln -s ~/Projects/tools/transcribe/bin/transcribe ~/bin/transcribe
```

Requires `ffmpeg`/`ffprobe` (`brew install ffmpeg`) and, for YouTube,
`yt-dlp` (`brew install yt-dlp`). First run downloads the ASR/diarization
models (~1–3 GB) and caches them.

## Usage

```bash
transcribe <file-or-youtube-url> --speakers auto
```

```bash
transcribe call.m4a --speakers auto --out /Users/sereja/Downloads/transcripts/call
transcribe video.mp4 --speakers 2 --out /Users/sereja/Downloads/transcripts/video
transcribe "https://www.youtube.com/watch?v=..." --speakers auto
```

If `--out` and `--out-root` are omitted, output goes to
`/Users/sereja/Downloads/transcripts/<video-or-file-title>`. For local files
this is the filename without extension. For YouTube this is the actual video
title from `yt-dlp`, not a URL slug.

Language is auto-detected by default. Use `--lang ru` or `--lang en` only when
the user explicitly wants to force a language. The detected label is written to
`transcript.md`, `transcript.json`, and `manifest.json` as `ru`, `en`, `mixed`,
or `auto`.

## Output

Each run writes:

- `transcript.md` — canonical reading file for AI agents.
- `transcript.json` — structured turns and word timings.
- `manifest.json` — engine, timings, source, duration, speaker count, and run metadata.
- `progress.json` — live run tracing, updated every ~2 s, finalized `done`/`error`.

For a simple "transcribe this" request, report the `transcript.md` path and
compact metrics. Read `transcript.md` only for follow-up work such as summary,
cleanup, extraction, or QA. Use `transcript.json` only when exact timestamps or
programmatic slicing are needed.

## Progress tracking (on demand)

Agents can check a run's progress without tailing logs:

```bash
transcribe status                     # latest run under the default out-root
transcribe status --out <out-dir>     # a specific run
transcribe status --json              # machine-readable
```

Prints `🎙 ASR 47% · ETA 01:18 · elapsed 02:30 · <source>` while running,
`✓ готово · N спикер(ов) · mm:ss · <path>/transcript.md` when done, and
`✗ ошибка: <reason>` on failure. `pct`/`eta_s` are estimates; ASR ETA is
calibrated from the previous run's RTF when available.

## Engine

- ASR: FluidAudio Parakeet TDT v3.
- Diarization: FluidAudio pyannote-style diarization.
- Default diarization mode: `streaming`.
- Vendored binary: `vendor/fluidaudiocli`.

The CLI is symlinked into `/Users/sereja/bin/transcribe`.

## Verification

```bash
python3 tests/test_merge.py
transcribe --help
```

Setup smoke used during creation:

```bash
transcribe /tmp/call_5min.wav --speakers auto --out /tmp/tt_call
```

Expected shape: `transcript.md`, `transcript.json`, and `manifest.json`, with
speaker labels such as `S1`/`S2` in `transcript.md` when diarization finds more
than one speaker.
