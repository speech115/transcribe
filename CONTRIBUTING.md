# Contributing

Run `python -m pytest tests/ -q` before submitting changes.

`src/transcribe/engine.py` owns the FluidAudio subprocess and JSON contract;
`src/transcribe/run.py` owns preparation, merging, and artifacts.

Never commit media, transcripts, or local engine output.
