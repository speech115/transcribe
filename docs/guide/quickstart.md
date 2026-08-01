# Quickstart

A first transcription, one command at a time. This page assumes
[installation is done](install.md).

## 1. Transcribe a local file

```bash
transcribe call.m4a --speakers auto
```

`--speakers auto` is the default; diarization detects the number of
speakers. Output goes to `~/Downloads/transcripts/call/` (the out-root plus
the file name without extension).

## 2. Pick your own output directory

```bash
transcribe video.mp4 --speakers 2 --out /Users/sereja/Downloads/transcripts/video
```

`--speakers 2` forces exactly two speaker labels instead of auto-detection.

## 3. Transcribe a YouTube video

```bash
transcribe "https://www.youtube.com/watch?v=…" --speakers auto
```

Audio is fetched with `yt-dlp`; the output directory is named from the real
video title.

## 4. Batch or clean a run

```bash
transcribe call-a.wav call-b.m4a --out-root ~/Downloads/transcripts
transcribe call.m4a --clean-fillers
```

Batch sources run sequentially; use `--out-root` because `--out` is for one
source only. Filler cleanup changes readable turns but preserves raw word
timings.

To process an inbox as files arrive:

```bash
transcribe --watch ~/Downloads/inbox --out-root ~/Downloads/transcripts
```

## 5. Check what came back

The run prints one summary line, and a successful run leaves three deliverables
plus live progress in the directory:

```bash
✓ 3 спикер(ов) · 12:34 · ASR 61x · ru
  /Users/sereja/Downloads/transcripts/call/transcript.md
  /Users/sereja/Downloads/transcripts/call/transcript.json
  /Users/sereja/Downloads/transcripts/call/manifest.json
```

- `transcript.md` — read this for anything semantic (summary, cleanup, QA).
- `transcript.json` — only when exact timestamps or word-level slicing matter.
- `manifest.json` — engine, language, duration, RTF, speaker count; read it
  before reporting metrics.

## 6. Watch progress from another terminal

```bash
transcribe status
```

Prints e.g. `🎙 ASR 47% · ETA 01:18 · elapsed 02:30 · call.m4a` while
running, and a done line once finished. See [status.md](status.md).

## Next

- [transcribe.md](transcribe.md) — every flag and the naming rules.
- [output.md](output.md) — artifact shapes in detail.
- [engine.md](engine.md) — what happens inside the run.
