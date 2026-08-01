# transcribe — the command

One entrypoint; normal runs are foreground and sources run sequentially:

```bash
transcribe <file-or-youtube-url>... [flags]
```

## Flags

| Flag | Default | Effect |
| --- | --- | --- |
| `--speakers auto\|off\|N` | `auto` | `auto` detects the speaker count; `off` disables diarization (monologues, speed); `N` forces exactly N speakers |
| `--lang ru\|en\|auto` | `auto` | force a language, or auto-detect (default). The resolved label is written to the artifacts |
| `--out DIR` | — | explicit output directory for this run |
| `--out-root DIR` | `~/Downloads/transcripts` | root for default output naming |
| `--clean-fillers` | off | remove conservative filler words from turns; raw words stay unchanged |
| `--watch DIR` | — | poll a folder for stable new media; cannot be combined with inputs or `--out` |
| `--diar-mode streaming\|offline` | `streaming` | streaming is fast (~61x realtime); offline is slower but more accurate diarization |
| `--asr-model v3\|v2` | `v3` | Parakeet model generation |
| `--keep-tmp` | off | keep the scratch directory (raw ASR/diarization JSON) for debugging |

Language is auto-detected by default; force `--lang ru` or `--lang en` only
when the user explicitly wants it. The resolution chain is
explicit argument → engine answer → text heuristic; the resulting label is
one of `ru`, `en`, `mixed`, `auto` (see [engine.md](engine.md)).

## Output naming

If neither `--out` nor `--out-root` is given, artifacts land in
`~/Downloads/transcripts/<title>` where `<title>` is:

- for a local file — the file name without extension (`call.m4a` → `call`),
- for YouTube — the actual video title from `yt-dlp`, minimally sanitized
  for filesystem safety (never a URL slug).

If the directory already exists, a numeric suffix is appended
(`call`, `call (2)`, `call (3)`, …). Pass `--out DIR` to take full control of
the location.

## Examples

```bash
# local file, auto everything
transcribe call.m4a

# forced speaker count, explicit output
transcribe video.mp4 --speakers 2 --out ~/Downloads/transcripts/video

# YouTube, explicit language
transcribe "https://www.youtube.com/watch?v=…" --lang ru --speakers auto

# fastest possible (no diarization, v2 model)
transcribe lecture.m4a --speakers off --asr-model v2

# debug a run: keep the raw engine JSON
transcribe call.m4a --keep-tmp --out /tmp/tt_debug

# clean hesitation words from readable turns
transcribe call.m4a --clean-fillers

# batch and watched-folder modes
transcribe a.wav b.m4a --out-root ~/Downloads/transcripts
transcribe --watch ~/Downloads/inbox --out-root ~/Downloads/transcripts
```

## Batch and watch modes

Multiple sources run sequentially. `--out` is rejected for a batch because it
would make every source collide; use `--out-root` instead. A source failure is
printed to stderr, the remaining sources still run, and the command exits 1
after the batch.

`--watch DIR` polls every 10 seconds. A supported media file must be unchanged
across two polls before it is processed. Hidden files and `.part`/`.tmp`
temporary files are ignored. A completed `manifest.json` prevents the same
source from being processed again; a failed source is blacklisted until the
watch process is restarted. Ctrl-C stops the polling loop.

## Preflight checks

Before any model work, the CLI verifies, and fails fast with exit 1 if:

- the vendored engine binary is missing;
- `ffmpeg`/`ffprobe` are not on PATH;
- the source is a non-YouTube URL (only local files and YouTube are
  supported);
- a local file does not exist;
- neither `--out` nor `--out-root` is given.

## Errors

Runtime failures print `transcribe: error: <reason>` to stderr and exit 1.
Once the output directory is known, a failed run finalizes `progress.json`
with status `error`, so a status check explains what happened.

## Reading the result

For a simple "transcribe this" request, report the `transcript.md` path and
compact metrics from `manifest.json`. Read `transcript.md` only for follow-up
work (summary, cleanup, extraction, QA), and `transcript.json` only when
exact timestamps or programmatic slicing are needed. See [output.md](output.md).
