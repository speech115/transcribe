# Contributing to transcribe

Thanks for looking. This page is the short, human version of the rules; the
canonical contract is [AGENTS.md](AGENTS.md) and it wins wherever the two
disagree.

## What lands here

This is a small, single-maintainer tool in daily local use.

- **Bug fix** — welcome. It starts from a failing test that reproduces the
  bug, then the minimal fix.
- **New behavior** — welcome, but talk to the maintainer first (open an
  issue). New behavior that changes the run contract or the engine seam
  needs an ADR before any code.
- **Docs, tooling, packaging** — welcome as their own pull request, kept
  separate from product behavior.

When in doubt whether something is a fix or a feature, open an issue and ask.

## Setup

```bash
git clone https://github.com/speech115/transcribe.git
cd transcribe
python3 -m pytest tests/ -q
```

No engine binary and no audio are needed for the suite: it is pure-stdlib
tests over the engine seam, language resolution, merge, and run contract
(fixtures in `tests/fixtures/fluidaudio/`). Requires Python 3.10+.

## The gate

One command runs exactly what CI runs:

```bash
./scripts/gate.sh
```

That is `python3 -m pytest tests/ -q`. Run it before every commit and quote
its real output in the pull request — never "tests pass".

## Working rules

- **TDD.** Failing test → minimal code → green → commit. No production code
  without a test that demanded it.
- **Test at public seams.** Engine behavior is verified against fixture
  JSON through the `Engine.transcribe()` port, never by poking at
  `vendor/fluidaudiocli` internals. Run behavior is verified through
  `lib/run.py`'s `run()`/`status()` and the artifact shapes they produce.
- **The engine seam is one-way.** `lib/engine.py` is the only module that
  knows the FluidAudio contract; merge, run, and the CLI never parse engine
  JSON or know its stage topology ([ADR-0001](docs/adr/ADR-0001-engine-seam.md)).
- **The run contract is one module.** Stages, ETA math, artifact names and
  schemas live only in `lib/run.py`
  ([ADR-0002](docs/adr/ADR-0002-run-module.md)); the CLI wrapper must not
  re-implement them.
- **Deliverables are strict, progress is best-effort.** `transcript.md`,
  `transcript.json`, and `manifest.json` are commit markers — failures
  there fail the run. `progress.json` writes never take the run down.
- **Artifacts write atomically.** Final `progress.json` is replaced via
  tmp + `os.replace`, never appended to in place.

## Documentation duties

These are part of the change, not follow-up work:

| Changed | Also update, in the same commit |
| --- | --- |
| CLI flags, output naming, exit codes | [docs/guide/transcribe.md](docs/guide/transcribe.md), [docs/guide/output.md](docs/guide/output.md), and the flags table in [README.md](README.md) |
| Engine behaviour (models, modes, language) | [docs/guide/engine.md](docs/guide/engine.md) |
| Agent-facing routing or recipes | [SKILL.md](SKILL.md) |
| An architectural decision | a new `ADR-NNNN-slug.md` in [docs/adr/](docs/adr/) plus its row in the index |
| Anything user-visible, at release time | a `CHANGELOG.md` entry |

The domain vocabulary in [CONTEXT.md](CONTEXT.md) is normative: use its
terms (run, source, engine, turn, speaker, stage, artifacts) and never
drift to the synonyms it explicitly avoids.

## Pull requests

- One coherent slice per pull request. Unrelated cleanup, tooling, and
  behavior belong in separate ones.
- Commits use a single-line imperative summary (`Add corpus collector`).
- Review fixes go onto the head of the pull request under review — one
  branch per slice, not per review round.
- Never merge while head-SHA checks are pending or red.

## Never commit

Audio and video files, transcripts, `progress.json`/`manifest.json`
artifacts, `docs/research/corpus.jsonl` (it accumulates personal video
titles and paths), downloaded models, or anything from
`~/Downloads/transcripts/`. Media contents and transcripts never enter this
repository, including in issue and pull-request bodies — see
[SECURITY.md](SECURITY.md).

## Language

Conversation with the maintainer may be in Russian. Everything committed —
code, comments, docs, commit messages, CLI output — is English, except
verbatim CLI output lines and the glossary/ADR documents that already live
in Russian.
