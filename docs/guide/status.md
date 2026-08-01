# status — progress and run history

`transcribe status` reports a run's live progress without tailing logs, and
the final state of a finished run.

```bash
transcribe status                     # latest run under the default out-root
transcribe status --out <out-dir>     # a specific run
transcribe status --json              # machine-readable
```

Flags:

| Flag | Default | Effect |
| --- | --- | --- |
| `--out DIR` | — | read the run in a specific directory |
| `--out-root DIR` | `~/Downloads/transcripts` | root for locating the latest run |
| `--json` | off | structured output instead of a human line |
| `--max-age N` | `60` | seconds after which `progress.json` counts as stale (`idle`) |

## Output lines

- Running: `🎙 ASR 47% · ETA 01:18 · elapsed 02:30 · <source>`
- Done: `✓ готово · 3 спикер(ов) · 12:34 · elapsed 05:10 · <path>/transcript.md`
- Failed: `✗ ошибка: <reason>`
- Nothing found / stale: an idle line; with `--json`, status `idle` or
  `missing`.

With `--json`, the output is one object with `status`, `stage`, `pct`,
`eta_s`, `elapsed_s`, `rtf`, `pid`, `source`, and (when done) `out_dir`,
`speakers`, `language`, `duration`, `transcript_md`.

## ETA calibration

`pct` and `eta_s` are estimates, not measurements: the ASR ETA is calibrated
from the previous run's real-time factor (RTF) when one is available, and
falls back to a default otherwise. Diarization reports its stage without a
percentage. Treat the numbers as indicators.

## For agents

When asked about progress — including "сколько осталось", "как там
транскрибация", "проверь прогресс" — run `transcribe status` and report the
printed line verbatim. Never invent percentages or ETAs from memory.
