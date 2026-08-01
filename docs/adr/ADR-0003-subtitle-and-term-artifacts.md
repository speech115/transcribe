# Optional subtitle and deterministic term artifacts

## Status

Accepted — 2026-08-01

## Context

The run already produces merged speaker turns with millisecond-capable word
timings, but video workflows need subtitle files and domain audio often has a
small, known vocabulary of recognition errors. These are output concerns, not
new engine capabilities.

Two boundaries matter:

- subtitle files must remain derived from merged turns, so they do not trigger
  another engine pass or create a second timing model;
- term normalization must not destroy the raw recognition evidence used for
  exact slicing and QA.

## Decision

`run()` accepts optional `srt` and `vtt` formats. It writes
`transcript.srt` and/or `transcript.vtt` from the same turns used by
`transcript.md`; multi-speaker captions carry their `S1:`/`S2:` label.

`run()` also accepts an optional JSON object of exact, case-sensitive term
replacements. Replacements are applied in one pass to turn text only, with
longer keys taking precedence. The `transcript.json` `words` array and its
timings remain raw. The selected formats and dictionary path are recorded in
`manifest.json`.

## Alternatives considered

- Rewrite raw words: rejected because it corrupts the original recognition
  evidence and can make word-level slicing inconsistent.
- Run an LLM cleanup pass: rejected because it would weaken determinism,
  privacy, and reproducibility for a local CLI.
- Add subtitle generation to the engine seam: rejected because subtitle
  rendering is a pure artifact concern and requires no engine change.
