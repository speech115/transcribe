---
name: transcribe
description: "Transcribe local audio/video files and YouTube media into transcript.md, transcript.json, and manifest.json, with optional speaker diarization and timestamps. Use for calls, voice notes, interviews, podcasts, lectures, recordings, or requests to identify speakers. Prefer the local offline FluidAudio/Parakeet CLI for private or routine work; use MacWhisper only when explicitly requested and its doctor passes, and use cloud APIs only with explicit approval."
---

# Transcribe

<!-- skill-index-metadata
tags: [transcription, asr, diarization, audio, video, media, parakeet, fluidaudio, macwhisper, openai-transcribe, deepgram]
aliases: [audio transcribe, transcribe media, audio transcription, video transcription, diarization, speaker diarization, транскрибация, транскрибировать аудио, транскрибировать видео, диаризация, распознать спикеров]
namespace: workspace
dependencies: []
version: 0.4.0
-->

This skill directory is the canonical source of truth. Host-specific skill
directories may symlink here; edit the target, not copied or linked views.

## Routing

- Local audio/video: use the offline `transcribe` CLI.
- YouTube with usable existing subtitles: use `video-transcript-downloader`.
- YouTube requiring fresh ASR or diarization: pass the URL to `transcribe`.
- Explicit MacWhisper request: run `macwhisper-transcribe doctor --json` first
  and use that route only when healthy.
- Explicit cloud request, known-speaker references, or an unavailable local
  engine: read `references/api.md`; obtain approval before uploading private
  media.
- Existing finished transcript: do not transcribe again; perform the requested
  cleanup, summary, extraction, or analysis directly.

Do not silently switch engines. A fallback can change privacy, cost, output
shape, speaker labeling, and transcription quality.

## Workflow

1. Classify the source and select the route above.
2. For local files, verify the path is readable. Never paste API keys or media
   contents into chat.
3. Run `transcribe <source> --speakers auto`. Keep automatic language detection
   unless the user explicitly requests a language.
4. Verify that `transcript.md`, `transcript.json`, and `manifest.json` exist and
   are non-empty. For multi-speaker output, confirm that speaker labels are not
   blank.
5. Read `manifest.json` before reporting the engine, language, duration,
   processing speed, or speaker count.
6. For a simple transcription request, return the artifact path and compact
   metrics. Do not add a summary unless requested.
7. Read `transcript.md` for follow-up semantic work. Use `transcript.json` only
   for exact timestamps, word-level slicing, or programmatic processing.
8. If the selected route fails, report the failure and the next viable route;
   do not switch to MacWhisper or a cloud backend silently.
9. If the user asks about progress or status of a run (including "сколько
   осталось", "как там транскрибация", "проверь прогресс"), run
   `transcribe status` and report the printed line verbatim. Do not invent
   percentages or ETAs from memory.

## Progress tracking (по запросу)

Every run writes a live-tracing file `progress.json` next to the transcript
artifacts, updated roughly every 2 seconds, and finalized as `done` or `error`
when the run finishes. It holds `status`, `stage` (`prep`/`asr`/`diar`/`merge`),
`pct`, `eta_s`, `elapsed_s`, `rtf`, `pid`, `source`, and (on completion)
`out_dir`, `speakers`, `transcript_md`.

Agent-facing status command:

```bash
transcribe status                     # последний прогон в <out-root> (default ~/Downloads/transcripts)
transcribe status --out <out-dir>     # конкретный прогон
transcribe status --json              # машинный вывод для программной обработки
```

- Running run prints e.g. `🎙 ASR 47% · ETA 01:18 · elapsed 02:30 · <source>`.
- Finished run prints `✓ готово · 3 спикер(ов) · 12:34 · elapsed 05:10 · <path>/transcript.md`.
- Failed run prints `✗ ошибка: <reason>`.
- `pct`/`eta_s` are estimates (ASR calibrated from the last run's RTF, else a
  default); treat them as indicators, not measurements. Diarization reports
  the stage without a percentage.

## Default Route (preferred)

Use the local `transcribe` CLI. Let it auto-detect language:

```bash
transcribe <file-or-youtube-url> --speakers auto
```

Only force language when the user explicitly requests it:

```bash
transcribe <file-or-youtube-url> --lang ru --speakers auto --out <output-dir>
transcribe <file-or-youtube-url> --lang en --speakers auto --out <output-dir>
```

The CLI must be available in `PATH`. Check with `command -v transcribe` and
`transcribe --help` before attempting repair or installation.

If `--out` is not provided, output goes under `/Users/sereja/Downloads/transcripts/<video-or-file-title>`. For local media this is the filename without extension. For YouTube this is the actual video title, minimally sanitized for filesystem safety.

## Standard Output

Every run writes:

- `transcript.md` — canonical transcript deliverable; read it first for follow-up agent work.
- `transcript.json` — structured turns and word timings for exact time ranges.
- `manifest.json` — engine, source, timings, RTF, speaker count, and run metadata.
- `progress.json` — live run tracing (status/stage/pct/ETA); finalized `done` or `error`.
- Language is auto-detected and written as `ru`, `en`, `mixed`, or `auto`.

Default reading rule for simple transcription: do not read the transcript after generation; report its path. Read `transcript.md` only when doing follow-up agent work such as summary, cleanup, extraction, or QA. Open `transcript.json` only when exact timestamps, word-level slicing, or programmatic post-processing is needed.

## Engine (primary local route)

The standard engine is FluidAudio / Parakeet:

- ASR: Parakeet TDT v3 via FluidAudio.
- Diarization: FluidAudio pyannote-style diarization, streaming mode by default.
- Runtime: local Apple Silicon path; after models are cached, it is offline.
- Vendored binary: `vendor/fluidaudiocli`.

This route provides a MacWhisper-style local workflow without depending on the
MacWhisper app or its history database.

## MacWhisper route

MacWhisper is not the default engine for this skill. Some hosts may provide an
agent wrapper named `macwhisper-transcribe` around the official MacWhisper CLI.

Before using it:

```bash
macwhisper-transcribe doctor --json
```

Use it only when the user explicitly requests MacWhisper or approves it as a
fallback and the doctor is green. Do not invoke the GUI, scrape the application
database directly, or assume that an installed `.app` means its CLI is healthy.

## Flags

- `--speakers auto` is the default. Use it unless the user gives a known count.
- `--lang auto` is the default. Prefer auto-detection even for Russian/English; the final language label is written to `manifest.json` and `transcript.md`.
- `--speakers N` forces a known number of speakers.
- `--speakers off` disables diarization for monologues or when speed matters more.
- `--diar-mode streaming` is the default and fast.
- `--diar-mode offline` is slower; use only when diarization quality is clearly more important than speed.
- `--keep-tmp` preserves raw ASR/diarization JSON for debugging.

## Guardrails

- Prefer local processing for private calls, voice notes, and interviews.
- Never upload media to OpenAI, Deepgram, or another service without explicit
  approval for that source.
- Do not use the MacWhisper GUI for agent workflows.
- Do not rely on the old `mw` Python shim or direct SQLite scraping;
  MacWhisper updates can break those surfaces.
- Do not trust the old `mlx_whisper` 1971x benchmark; it was a bad timing capture. Use fresh end-to-end wall time from `manifest.json`.
- For YouTube, this CLI downloads audio through `yt-dlp` and still produces the same diarized standard output. If the user only wants existing subtitles, the `video-transcript-downloader` skill can still be a cheaper route.

## Quick Verification

```bash
command -v transcribe
transcribe --help
transcribe status --json
```

Known smoke check from setup:

```bash
transcribe /tmp/call_5min.wav --speakers auto --out /tmp/tt_call
```

Expected shape: `transcript.md`, `transcript.json`, `manifest.json`, speaker labels in markdown such as `S1`/`S2` when there is more than one speaker, and no blank speaker labels in a multi-speaker file.

## Alternative cloud backends (API)

When the local Parakeet/FluidAudio route is unavailable or the user explicitly
requests cloud models or known-speaker references via API:

See `references/api.md` in this skill directory and the helper `scripts/transcribe_diarize.py`.

Quick examples follow. Never ask the user to paste an API key into chat.

Single file (fast text):
```bash
python3 scripts/transcribe_diarize.py \
  path/to/audio.wav \
  --backend openai \
  --out transcript.txt
```

Diarization + known speakers (OpenAI):
```bash
python3 scripts/transcribe_diarize.py \
  meeting.m4a \
  --backend openai \
  --model gpt-4o-transcribe-diarize \
  --known-speaker "Alice=refs/alice.wav" \
  --known-speaker "Bob=refs/bob.wav" \
  --response-format diarized_json \
  --out-dir output/transcribe/meeting
```

Deepgram multilingual:
```bash
python3 scripts/transcribe_diarize.py \
  interview.mp3 \
  --backend deepgram \
  --model nova-3 \
  --response-format diarized_json \
  --out interview.json
```

See `references/api.md` for limits, formats, and known-speaker details.

## Reference map

- `references/api.md` — cloud backend details (OpenAI gpt-4o-transcribe models, Deepgram nova-3).
- The main local CLI implementation lives in this repository: `bin/transcribe`,
  `lib/`, `tests/`, `vendor/fluidaudiocli`.
