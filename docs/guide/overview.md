# Overview

`transcribe` is a local offline transcription CLI for macOS (Apple Silicon).
One command turns a local audio/video file or a YouTube link into a marked-up
transcript with speaker diarization — reads, runs, and writes four standard
artifacts,
then exits. Nothing leaves the machine: no cloud backend, no uploads, no
API keys. After the first run caches the models, the tool is fully offline.

## Execution model

The normal invocation is one foreground run: preflight, prepare audio,
transcribe, and exit. Batch mode repeats that same run sequentially for each
source. Explicit `--watch DIR` is the only long-lived mode; it polls for stable
media files and reuses the same run contract.

The stages of a run, visible live in `progress.json`:

| Stage | Work |
| --- | --- |
| `prep` | YouTube fetch (if needed) + convert to 16 kHz mono WAV via `ffmpeg` |
| `asr` | speech recognition on the Apple Neural Engine (Parakeet TDT v3) |
| `diar` | speaker diarization (only when `--speakers` is not `off`) |
| `merge` | word timings + speaker segments merged into turns, artifacts written; optional cleanup/replacements change turns only |

Stage detail lives in [engine.md](engine.md); the merge contract lives in
[lib/run.py](../../lib/run.py) and [ADR-0002](../adr/ADR-0002-run-module.md).

## Sources

- **Local media** — any file `ffmpeg` can read: m4a, mp3, wav, mp4, mov, and so on.
- **YouTube** — a watch URL; audio is fetched with `yt-dlp`. The output
  directory is named from the real video title, not a URL slug.

Everything else — non-YouTube URLs, missing files, missing tools — is a
hard error (exit 1) before any model work starts.

## Output contract

Each run writes three deliverables and a live-tracing file into the output
directory. `transcript.srt` and `transcript.vtt` are optional subtitle
artifacts written with `--formats`; `--replacements` can normalize turn text
while raw word timings stay intact.

| File | Job |
| --- | --- |
| `transcript.md` | canonical reading file — turns by speaker, ready for AI agents |
| `transcript.json` | machine-readable turns + word timings for exact time ranges |
| `manifest.json` | run metadata — engine, source, duration, RTF, speaker count, command flags |
| `progress.json` | live run tracing, finalized `done` or `error` |
| `transcript.srt` / `transcript.vtt` | optional subtitles from merged turn timings |

`manifest.json` is the commit marker: it is written last, so its presence
means the run completed. Shapes and reading rules: [output.md](output.md).

## Where state lives

| Path | Contents |
| --- | --- |
| `<out-root>/<title>/` | artifacts; default out-root is `~/Downloads/transcripts` |
| `<out-root>/.transcribe-watch.json` | persistent source status for `--watch` |
| model cache | downloaded once on first run (≈1–3 GB), reused forever after |
| temp workdir | scratch audio; deleted unless `--keep-tmp` |

The out-root is overridable with `--out-root` (and per-run with `--out`).
See [transcribe.md](transcribe.md) for the naming rules.

## Exit codes

| Code | Meaning | Typical cause |
| --- | --- | --- |
| 0 | success | |
| 1 | run error | missing tool, missing file, unsupported URL, engine failure |

There is no separate "usage error" code: bad flags fail at argument parsing
with argparse's exit 2; everything runtime-related is exit 1.

## Privacy posture

Local processing is the only route: media is never uploaded anywhere, and
the CLI performs no network calls except fetching YouTube audio when the
source is a YouTube URL. Do not paste audio contents or transcripts into
chat; report artifact paths instead. See [SECURITY.md](../../SECURITY.md).

## Where to go next

- [install.md](install.md) — clone, symlink `transcribe`, first-run cache.
- [quickstart.md](quickstart.md) — a first transcription, one command at a time.
- [transcribe.md](transcribe.md) — the full flag surface and output naming.
- [status.md](status.md) — how to check a running or finished run.
- [README.md](../guide/README.md) — the full page index.
