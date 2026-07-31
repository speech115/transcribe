<!--
One coherent slice per PR. Unrelated cleanup, tooling, and product behavior
belong in separate PRs. Full rules: CONTRIBUTING.md and AGENTS.md.
-->

## What and why

<!-- The change in a few lines, and the problem it solves. -->

## Scope

- Kind: <!-- bug fix | docs | tooling | new behavior (ADR: ____) -->
- Authorized by: <!-- issue #N, ADR-NNNN, or "bug fix: reproducing test" -->

## Evidence

<!--
Paste the real tail of ./scripts/gate.sh — never "tests pass".
A bug fix shows the reproducing test failing before the fix, passing after.
-->

```
$ ./scripts/gate.sh

```

## Documentation

- [ ] `docs/guide/` updated (flags, output naming, exit codes, engine behaviour)
- [ ] `README.md` reflects the public flags and the output contract
- [ ] `SKILL.md` updated when agent routing or recipes change
- [ ] ADR added and indexed in `docs/adr/README.md` (architectural decision)
- [ ] `CHANGELOG.md` entry added for user-visible changes

## Privacy

- [ ] No media, transcripts, personal data, or identifying paths/titles in the diff or in this description
- [ ] Engine knowledge stayed behind `lib/engine.py`; the run contract stayed in `lib/run.py`
- [ ] Artifact writes remain atomic and fail the run on deliverable errors
