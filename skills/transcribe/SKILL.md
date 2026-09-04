---
name: transcribe
description: "Transcribe local audio/video and YouTube media with local FluidAudio/Parakeet, optional diarization, and standard transcript artifacts."
---

# Transcribe

Use the local offline CLI for private or routine media:

```bash
transcribe <file-or-youtube-url> --speakers auto
```

Language and speaker count are automatic. Use `--lang`, `--speakers`, `--out`
or `--out-root`, `--diar-mode`, and `--formats srt,vtt` when explicitly needed.

Every run writes non-empty `transcript.md`, `transcript.json`, and
`manifest.json`; subtitles are optional. Read `manifest.json` before reporting
metrics, and read `transcript.md` only for follow-up semantic work.

Keep private media local and never paste media, transcripts, or API keys into
chat. Do not silently switch engines. MacWhisper is allowed only when the user
explicitly requests it or approves it as a fallback after its doctor passes.

For YouTube, use `yt-dlp` through the CLI. Existing finished transcripts should
be processed directly rather than transcribed again.

The package lives in `src/transcribe`; the vendored engine is
`vendor/fluidaudiocli`.
