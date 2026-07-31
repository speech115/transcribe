# Engine

All recognition happens locally through one engine seam
([ADR-0001](../adr/ADR-0001-engine-seam.md)). The CLI never talks to a cloud
backend; the vendored binary is the only route.

## ASR — Parakeet TDT v3

Speech recognition runs on the Apple Neural Engine via FluidAudio's
Parakeet TDT v3 (`--asr-model v3`, default; `v2` is the previous
generation). After the model cache is warm, the ASR pass is fully offline
and typically runs at ~61× realtime on Apple Silicon — a 12-minute file
takes about 12 seconds.

## Diarization — streaming vs offline

Speaker diarization is pyannote-style, controlled by `--diar-mode`:

| Mode | When | Speed |
| --- | --- | --- |
| `streaming` (default) | most runs; the fast path | ~61× realtime |
| `offline` | when diarization quality clearly matters more than speed | slower, better DER |

Diarization runs whenever `--speakers` is not `off`; the rule "when
diarization applies" lives in the engine, and the applied mode is reported
in `manifest.json` as `diar_mode` (null when it did not run).

## Language resolution

`--lang ru|en` forces a language; the default chain is:

1. explicit `--lang` argument (if given),
2. the engine's own answer,
3. a heuristic over the recognized text.

The resolved label is written to `transcript.md`, `transcript.json`, and
`manifest.json` as one of `ru`, `en`, `mixed`, `auto`. Prefer
auto-detection even for Russian and English.

## Model cache and offline guarantee

The first run downloads the ASR and diarization models (≈1–3 GB) and caches
them. Every subsequent run is 100% local: no network access at all except
`yt-dlp` fetching YouTube audio when the source is a YouTube URL. There is
no telemetry, no model ping, no license check over the wire.

## Vendored binary

The engine ships as a single arm64 macOS binary at
`vendor/fluidaudiocli` and is required in the repo (it is re-added to the
repository despite the global gitignore rule for `vendor/`). Its
command-line contract, JSON schemas (`wordTimings`/`segments`), speaker
relabelling, and error classification live behind `lib/engine.py`; nothing
else in the codebase knows the engine's format
([ADR-0001](../adr/ADR-0001-engine-seam.md)).

### Rebuilding

The binary is built from the [FluidAudio](https://github.com/FluidInference/FluidAudio)
Swift package at the pinned tag (currently **v0.15.5**, built 2026-08-01
with Xcode 26.6 / Swift 6.3):

```bash
git clone --depth 1 --branch v0.15.5 https://github.com/FluidInference/FluidAudio.git
cd FluidAudio && swift build -c release
cp .build/release/fluidaudiocli vendor/fluidaudiocli
```

When bumping the engine, verify the seam against real speech (a full
`bin/transcribe` run with `--speakers`), confirm the 43-fixture test suite
stays green, and record the new tag here.
