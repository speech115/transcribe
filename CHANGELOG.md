# Changelog

All notable changes to transcribe. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
the `version` field of the skill definition in
[SKILL.md](SKILL.md). Rationale for each entry lives in the ADR it names
([docs/adr/README.md](docs/adr/README.md)).

## [Unreleased]

### Changed

- Vendored engine binary bumped FluidAudio v0.15.3 → v0.15.5: offline
  seam-merge artifact fixes, VBx re-clustering and Sortformer v3
  diarization fixes, ModelHub download rewrite
  ([#708](https://github.com/FluidInference/FluidAudio/pull/708),
  [#735](https://github.com/FluidInference/FluidAudio/pull/735),
  [#765](https://github.com/FluidInference/FluidAudio/pull/765)).

## [0.4.0] — 2026-08-01

Initial standalone release: the local offline transcription CLI extracted
from the agent-skills stack into its own repository, with the FluidAudio
engine vendored as a single binary.

### Added

- One-command run contract in `lib/run.py` ([ADR-0002](docs/adr/ADR-0002-run-module.md)):
  stages (`prep`/`asr`/`diar`/`merge`), ETA math, live `progress.json`
  tracing (best-effort writes, atomic finalization, sticky terminal status,
  `degraded` on corrupt state), artifact naming and schemas,
  `transcribe status` with RTF-calibrated ETA, and `manifest.json` as the
  commit marker (written last).
- Engine seam in `lib/engine.py` ([ADR-0001](docs/adr/ADR-0001-engine-seam.md)):
  one `Engine.transcribe()` port over the FluidAudio subprocess contract —
  `wordTimings`/`segments` JSON, `S1..Sn` relabelling, error classification
  as `EngineError(stage)`; cloud-ready by design, two-pass topology kept
  inside the adapter.
- Language resolution chain — explicit flag → engine answer → text
  heuristic — with the resolved label (`ru`/`en`/`mixed`/`auto`) written to
  `transcript.md`, `transcript.json`, and `manifest.json`.
- Turn merge from word timings and diarization segments into speaker turns
  (`lib/merge.py`).
- Sources: any ffmpeg-readable local file and YouTube watch URLs via
  `yt-dlp`, with output directories named from the real video title.
- Vendored arm64 macOS engine binary (`vendor/fluidaudiocli`) committed to
  the repository despite the global `vendor/` gitignore rule.
- Agent skill (`SKILL.md`) with routing rules: local CLI preferred,
  MacWhisper only on explicit request, existing transcripts never
  re-transcribed.
- Corpus collector (`scripts/collect_corpus.py`) for run metrics,
  appending to the locally ignored `docs/research/corpus.jsonl`.
- `--asr-model v3|v2`, `--diar-mode streaming|offline`, `--speakers
  auto|off|N`, `--lang`, `--out`, `--out-root`, `--keep-tmp`.
- Engine stage timings (`asr_s`/`diar_s`) and the applied `diar_mode`
  reported through the seam and into `manifest.json`, plus progress
  regression fixes on the same pass.
