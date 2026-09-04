---
name: transcribe
description: "Transcribe local audio/video and YouTube media with local FluidAudio/Parakeet, optional diarization, and standard transcript artifacts."
---

# Transcribe

Use the installed CLI directly:

```bash
transcribe <file-or-youtube-url> --speakers auto
```

Do not run from a source checkout, set `PYTHONPATH`, or call `python -m transcribe`.
If the executable is missing, repair the installation first with `uv tool install`.
Run `transcribe doctor` when installation health is unclear.

Language and speaker count are automatic. Use `--lang`, `--speakers`, `--out`,
`--out-root`, `--diar-mode`, and `--formats srt,vtt` when explicitly needed.

When running with `--speakers auto`, allow the local FluidAudio process to read
and write its model caches under `~/Library/Application Support/FluidAudio` and
`~/Library/Caches/fluidaudiocli`.

Every run writes non-empty `transcript.md`, `transcript.json`, and `manifest.json`;
subtitles are optional. Read `manifest.json` before reporting metrics, and read
`transcript.md` only for follow-up semantic work.

Keep private media local and never paste media, transcripts, or API keys into chat.
Do not silently switch engines. MacWhisper is allowed only when explicitly
requested or approved as a fallback after its doctor passes.

For YouTube, use `yt-dlp` through the CLI. Existing finished transcripts should
be processed directly rather than transcribed again.
