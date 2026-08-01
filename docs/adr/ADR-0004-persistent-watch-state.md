# Persistent watch state and option-aware idempotency

## Status

Accepted — 2026-08-01

## Context

`--watch` originally kept its stable-file map and failed-source blacklist only
in memory. Restarting the process therefore forgot failures, while a completed
manifest could not distinguish a run made with different output options.

The intended workflow is a long-lived local folder monitor that is safe to
restart and does not silently reprocess unchanged media.

## Decision

Watch mode stores an atomically written `.transcribe-watch.json` under
`<out-root>`. It records, per canonical source path, the source signature
(size and modification time), the processing-options fingerprint, status,
attempt count, and the latest error/output directory.

Completed work is still confirmed by a matching `manifest.json` whose
`source_path` identifies the canonical local source; the state file is
coordination state, not a replacement for run artifacts. The manifest records
the same `options_hash`, so changing speakers, language, engine mode, model,
cleanup, subtitle formats, or replacement contents makes the source eligible
for a new run.

Failed sources remain skipped across restarts by default. `--retry-failed`
allows one retry per failed source in the current watch process. A changed
source signature or options fingerprint is eligible without that flag.

Batch and watch remain sequential. Parallel engine runs are deliberately not
part of this decision until an Apple Silicon throughput benchmark justifies
them.

## Alternatives considered

- SQLite queue: rejected for a small dependency-free CLI; the state is a
  single atomic JSON document.
- Delete failed state on restart: rejected because it causes silent retry
  loops and hides persistent source failures.
- Use output directory names as identity: rejected because names do not encode
  source changes or processing options.
