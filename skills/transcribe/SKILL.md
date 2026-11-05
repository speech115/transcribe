---
name: transcribe
description: "Transcribe local audio/video files and YouTube URLs offline with FluidAudio/Parakeet, with optional speaker diarization and SRT/VTT subtitles. Use for requests to transcribe, расшифровать, сделать транскрибацию или субтитры, or find out who said what in a call, interview, podcast, lecture or video. Not for media that already has a finished transcript (process that transcript instead) or for Even Conversate recordings (use conversate-sync)."
---

# Transcribe

## Before running

Check for an existing transcript first. Default outputs live in
`~/Downloads/transcripts/<title>/`; match the request against the `source` field
of each `manifest.json` there. If one matches, work from it instead of
transcribing again.

## Run

```bash
transcribe <file-or-youtube-url> --speakers auto > /dev/null
```

Redirect stdout: the CLI prints the whole transcript there, and a long recording
floods the context. The artifact paths and a one-line summary go to stderr.

Invoke the installed `transcribe` directly. Do not run it from a source
checkout, set `PYTHONPATH`, or call `python -m transcribe`. If it is not on PATH,
repair the installation with
`uv tool install git+https://github.com/speech115/transcribe.git`. Run
`transcribe doctor` when installation health is unclear.

Language and speaker count are automatic. Use these flags only when needed:

- `--lang ru|en`, `--speakers off|N`
- `--out DIR` for one source, `--out-root DIR` for several (`--out` rejects
  multiple sources)
- `--overwrite` to replace artifacts in an existing `--out`; without `--out`,
  a repeated title gets a new `<title> (2)` folder
- `--diar-mode offline` for more accurate speaker turns at lower speed
- `--formats srt,vtt` for subtitles

With several sources the CLI keeps going after a failure and exits 1 at the end;
report which sources failed.

YouTube needs `yt-dlp` (`brew install yt-dlp`). Run long downloads in the
background.

When running with `--speakers auto`, allow the local FluidAudio process to read
and write these paths; CoreML/E5RT diarization can fail inside a restricted
sandbox otherwise:

- `~/Library/Application Support/FluidAudio`
- `~/Library/Caches/fluidaudiocli`

## Results

Every run writes non-empty `transcript.md`, `transcript.json`, and
`manifest.json`; subtitles are optional. Read `manifest.json` before reporting
metrics. If `diarization.status` is `failed`, tell the user the transcript has
no speaker labels and include `diarization.error`. Read `transcript.md` only
for follow-up work with the text.

## Privacy and engines

Keep private media local. Never paste media, API keys, or a full transcript into
chat; summaries and short quotes the user asks for are fine.

Do not silently switch engines. MacWhisper (`~/bin/mw transcribe`) is allowed
only when the user explicitly requests it or approves it as a fallback, and only
after `mw version` and `mw models` succeed.
