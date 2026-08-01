# Output

Every run writes the standard deliverables and a live-tracing file into the
output directory. SRT/VTT subtitle artifacts are written only when requested.

## transcript.md

The canonical reading file: a marked-up transcript with speaker turns.

```markdown
# call.m4a

Источник: call.m4a · 12:34 · ru · 3 спикера

## S1 — 00:00:01

Текст первой реплики первого спикера…

## S2 — 00:02:14

…
```

Speakers are labelled `S1..Sn` in order of first appearance. Read this file
first for any follow-up semantic work — summary, cleanup, extraction, QA.

## transcript.json

Machine-readable form of the same run: run metadata plus `turns` (speaker,
start, end, text) and `words` (per-word timings: start, end, text). Use it
only when exact timestamps, word-level slicing, or programmatic
post-processing are needed.

```json
{
  "source": "call.m4a",
  "duration": 754.2,
  "speakers": 3,
  "language": "ru",
  "turns": [{"speaker": "S1", "start": 1.2, "end": 8.9, "text": "…"}],
  "words":  [{"start": 1.2, "end": 1.6, "text": "…"}]
}
```

## manifest.json

Run metadata; the commit marker — it is written last, so its presence means
the run completed. Read it before reporting engine, language, duration,
processing speed, or speaker count.

| Field | Meaning |
| --- | --- |
| `source` | file name or YouTube URL |
| `source_path` | canonical local source path, or `null` for YouTube |
| `duration` | audio duration, seconds |
| `speakers` | number of speakers (≥ 1) |
| `language` | resolved label: `ru`, `en`, `mixed`, `auto` |
| `engine` | engine display name |
| `generated` | ISO timestamp of the run |
| `clean_fillers` | whether filler cleanup was enabled for turns |
| `out_dir` | artifact directory |
| `timings_s` | `prep_s`, `asr_s`, `diar_s` (may be null) |
| `asr_rtf` | real-time factor of the ASR pass (e.g. `61.0` ≈ 61× realtime) |
| `asr_model` | model generation (`v3`, `v2`) |
| `diar_mode` | applied diarization mode, or null when none ran |
| `speakers_arg` | the `--speakers` value as given |
| `words` / `turns` | counts |
| `engine_binary` | path of the vendored engine binary |
| `options_hash` | fingerprint of options that affect generated artifacts |
| `subtitle_formats` | requested subtitle formats, e.g. `srt`, `vtt` |
| `replacements_file` | replacement dictionary path, or `null` |

When `clean_fillers` is true, `transcript.json.turns` and `transcript.md` carry
cleaned text. `transcript.json.words` remains the raw ASR word stream with its
original timings.

## transcript.srt / transcript.vtt

Optional subtitle artifacts, requested with `--formats srt,vtt`. They use the
merged turn boundaries with millisecond timestamps. Multi-speaker subtitles
prefix each caption with its speaker label (`S1:`, `S2:`); a single-speaker
transcript has no label prefix.

## Replacement dictionary

`--replacements terms.json` applies exact, case-sensitive replacements to turn
text. The same transformed text appears in `transcript.md`, `transcript.json`
turns, and optional subtitles. The raw `transcript.json` `words` array is
never rewritten, so original recognition text and timings remain available.

```json
{
  "флюидаудио": "FluidAudio",
  "Ефим": "Ефимов"
}
```

## progress.json

Live run tracing, updated roughly every 2 seconds and finalized as `done`
or `error`. Holds `status`, `stage` (`prep`/`asr`/`diar`/`merge`), `pct`,
`eta_s`, `elapsed_s`, `rtf`, `pid`, `source`, and on completion `out_dir`,
`speakers`, `language`, `duration`, `transcript_md`. The final status is
sticky; a corrupt file reports as `degraded`, never as a silent idle.
See [status.md](status.md) for the agent-facing way to read it.

## Reading rules

- For a simple transcription request: report the `transcript.md` path and
  compact metrics. Do not read the transcript after generating it.
- Read `transcript.md` for follow-up semantic work.
- Open `transcript.json` only for exact timestamps, slicing, or
  programmatic processing.
- Report engine/language/duration/speaker counts only from `manifest.json`,
  never from memory.
