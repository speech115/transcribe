# Install

`transcribe` requires macOS on Apple Silicon and `ffmpeg`/`ffprobe` on your
PATH. Python is only needed to run the test suite; the CLI itself is a
Python script that ships with the repo.

## Requirements

```bash
brew install ffmpeg        # audio conversion
brew install yt-dlp        # only for YouTube sources
```

The ASR/diarization engine is vendored as a single binary in this repo
(`vendor/fluidaudiocli`, arm64 macOS) — no separate engine install.

## Clone and link

```bash
git clone https://github.com/speech115/transcribe.git ~/Projects/tools/transcribe
ln -s ~/Projects/tools/transcribe/bin/transcribe ~/bin/transcribe   # put it on PATH
```

For AI agents, symlink the skill definition into the agent skills directory:

```bash
ln -s ~/Projects/tools/transcribe ~/.agents/skills/transcribe
```

## First run: model cache

The first run downloads the ASR and diarization models (≈1–3 GB) and caches
them. After that the tool is fully offline — no network access happens on
subsequent runs (except fetching YouTube audio when the source is a YouTube
URL).

```bash
transcribe /tmp/call_5min.wav --speakers auto --out /tmp/tt_call
```

## Verify

```bash
transcribe --help
python3 -m pytest tests/ -q
```

Expected test result: `43 passed`.

A smoke run against a short local file should produce `transcript.md`,
`transcript.json`, and `manifest.json` in the output directory, with
speaker labels (`S1`/`S2`/…) in `transcript.md` when diarization finds more
than one speaker.
