# transcribe guide

Task-shaped pages for using `transcribe`: one page per area, each answering
"how do I transcribe X" with real invocations and the artifacts you get back.

Three documents describe this tool, and they do not overlap:

| Document | Audience | Job |
| --- | --- | --- |
| **this guide** | humans | how to perform a task, with worked examples |
| [SKILL.md](../../SKILL.md) | agents | routing table and recipes, loaded into context |
| [CONTEXT.md](../../CONTEXT.md) | both | the domain vocabulary — run, source, engine, turn, speaker, artifacts |

## Start

| Page | Covers |
| --- | --- |
| [overview](overview.md) | execution model, stages, artifacts, where state lives |
| [install](install.md) | clone, PATH linking, dependencies, first-run model cache |
| [quickstart](quickstart.md) | a first transcription end to end |

## Operation

| Page | Covers |
| --- | --- |
| [transcribe](transcribe.md) | the one command, all flags, sources, output naming |
| [output](output.md) | `transcript.md`, `transcript.json`, `manifest.json` — shapes and reading rules |
| [status](status.md) | `transcribe status` — live progress, ETA, and run history |

## Engine

| Page | Covers |
| --- | --- |
| [engine](engine.md) | FluidAudio Parakeet TDT v3, diarization modes, language resolution, model cache |

## See also

- [docs/adr/](../adr/README.md) — why each behaviour is the way it is.
- [CHANGELOG.md](../../CHANGELOG.md) — what changed between versions.
- [SKILL.md](../../SKILL.md) — the agent-facing contract for transcription runs.
