---
name: transcribe
description: "Transcribe local audio/video files and YouTube media into transcript.md, transcript.json, manifest.json, and optional SRT/VTT subtitles, with optional speaker diarization and timestamps. Use for calls, voice notes, interviews, podcasts, lectures, recordings, or requests to identify speakers. Prefer the local offline FluidAudio/Parakeet CLI for private or routine work; use MacWhisper only when explicitly requested and its doctor passes."
---

# Transcribe

<!-- skill-index-metadata
tags: [transcription, asr, diarization, audio, video, media, parakeet, fluidaudio, macwhisper]
aliases: [audio transcribe, transcribe media, audio transcription, video transcription, diarization, speaker diarization, транскрибация, транскрибировать аудио, транскрибировать видео, диаризация, распознать спикеров]
namespace: workspace
dependencies: []
version: 0.5.0
-->

This skill directory is the canonical source of truth. Host-specific skill
directories may symlink here; edit the target, not copied or linked views.

## Route and workflow

Use the local offline `transcribe` CLI for local media and for YouTube when
fresh ASR or diarization is needed. If usable YouTube subtitles are enough,
use `video-transcript-downloader`. For an explicit MacWhisper request (or an
approved fallback), run `macwhisper-transcribe doctor --json` first and use it
only when healthy. Never silently switch engines; an existing finished
transcript should be processed directly.

1. Classify the source and select the route above.
2. For local files, verify the path is readable. Never paste API keys or media
   contents into chat.
3. Run the default command shown below; for several sources, pass them in one
   invocation with `--out-root`.
4. Verify the standard artifacts below are non-empty. If subtitles were
   requested, verify each requested subtitle too; multi-speaker labels must not
   be blank.
5. Read `manifest.json` before reporting the engine, language, duration,
   processing speed, or speaker count.
6. For a simple transcription request, return the artifact path and compact
   metrics. Do not add a summary unless requested.
7. Read `transcript.md` for follow-up semantic work. Use `transcript.json` only
   for exact timestamps, word-level slicing, or programmatic processing.
8. If the selected route fails, report the failure and the next viable route.

## CLI defaults and output

The default route is local `transcribe` with automatic speakers and language:

```bash
transcribe <file-or-youtube-url> --speakers auto
```

Force language only when explicitly requested:

```bash
transcribe <file-or-youtube-url> --lang ru --speakers auto --out <output-dir>
transcribe <file-or-youtube-url> --lang en --speakers auto --out <output-dir>
```

The CLI must be available in `PATH`. Check with `command -v transcribe` and
`transcribe --help` before attempting repair or installation.

If `--out` is not provided, output goes under
`~/Downloads/transcripts/<video-or-file-title>`: the local filename without
extension or the minimally sanitized actual YouTube title.

Every run writes:

- `transcript.md` — canonical transcript deliverable; read it first for follow-up agent work.
- `transcript.json` — structured turns and word timings for exact time ranges.
- `manifest.json` — engine, source, timings, RTF, speaker count, and run metadata.
- `transcript.srt` / `transcript.vtt` — optional subtitle artifacts requested
  with `--formats`; they use turn timings and include speaker labels for
  multi-speaker runs.
- Language is auto-detected and written as `ru`, `en`, `mixed`, or `auto`.

Reading rule: for a simple transcription, report the `transcript.md` path
without reading it. Read `transcript.md` for follow-up semantic work; open
`transcript.json` only for exact timestamps, word-level slicing, or code.

## Engine (primary local route)

The standard engine is FluidAudio / Parakeet:

- ASR: Parakeet TDT v3 via FluidAudio.
- Diarization: FluidAudio pyannote-style diarization, streaming mode by default.
- Runtime: local Apple Silicon path; after models are cached, it is offline.
- Vendored binary: `vendor/fluidaudiocli`.

This route provides a MacWhisper-style local workflow without depending on the
MacWhisper app or its history database.

## MacWhisper fallback

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

- `--speakers N` forces a known number of speakers.
- `--speakers off` disables diarization for monologues or when speed matters more.
- `--diar-mode streaming` is the default and fast.
- `--diar-mode offline` is slower; use only when diarization quality is clearly more important than speed.
- `--keep-tmp` preserves raw ASR/diarization JSON for debugging.
- `--formats srt,vtt` writes optional subtitle artifacts from the merged turns.
- Multiple positional sources run sequentially under `--out-root`; a failed
  source is reported and the remaining sources still run, with exit 1 at the
  end if any source failed. `--out` is single-source only.

## Guardrails

- Prefer local processing for private calls, voice notes, and interviews.
- Never upload media to cloud services; the local CLI is the only
  transcription route.
- Do not use the MacWhisper GUI for agent workflows.
- Do not rely on the old `mw` Python shim or direct SQLite scraping;
  MacWhisper updates can break those surfaces.
- Do not trust the old `mlx_whisper` 1971x benchmark; it was a bad timing capture. Use fresh end-to-end wall time from `manifest.json`.
- For YouTube, this CLI downloads audio through `yt-dlp` and still produces the same diarized standard output. If the user only wants existing subtitles, the `video-transcript-downloader` skill can still be a cheaper route.

## Quick verification

```bash
command -v transcribe
transcribe --help
```

Expected shape: non-empty `transcript.md`, `transcript.json`, and
`manifest.json`; multi-speaker markdown has `S1`/`S2`-style labels.

## Reference map

- The main local CLI implementation lives in this repository: `bin/transcribe`,
  `lib/`, `tests/`, `vendor/fluidaudiocli`.
