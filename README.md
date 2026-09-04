# transcribe

Local, offline transcription for macOS Apple Silicon. Turn audio/video or a
YouTube URL into a readable transcript with optional speaker diarization.

## Install

```bash
uv tool install git+https://github.com/speech115/transcribe.git
```

Requires `ffmpeg`; install `yt-dlp` for YouTube sources.

Verify the installed executable and print the bundled agent skill with:

```bash
transcribe doctor
transcribe skill
```

## Quick start

```bash
transcribe call.m4a --speakers auto
```

The command prepares audio, runs vendored FluidAudio/Parakeet, optionally
diarizes, merges turns, and writes `transcript.md`, `transcript.json`, and
`manifest.json` (plus requested SRT/VTT subtitles).

Language and speaker count are automatic by default. Use `--lang`,
`--speakers`, `--out`, `--out-root`, and `--formats` when needed.

## Privacy

Processing is local after the model cache is present. Media is not uploaded;
network access is used only for the initial model cache and YouTube download.

## Status

v0.5.0 · single-maintainer project · Apache-2.0
