#!/usr/bin/env python3
"""Tests for bin/transcribe wiring into the run-module contract."""
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import RunError, RunResult

BIN = Path(__file__).resolve().parent.parent / "bin" / "transcribe"


def _load_cli():
    loader = SourceFileLoader("transcribe_cli", str(BIN))
    spec = importlib.util.spec_from_loader("transcribe_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_cli_batch_continues_after_one_source_error():
    cli = _load_cli()
    calls = []
    original_run = cli.run

    def fake_run(source, **kwargs):
        calls.append((source, kwargs))
        if source == "bad.wav":
            raise RunError("файл не найден")
        return RunResult(out_dir=Path("/tmp/good"),
                         transcript_md=Path("/tmp/good/transcript.md"),
                         transcript_json=Path("/tmp/good/transcript.json"),
                         manifest=Path("/tmp/good/manifest.json"),
                         speakers=1, duration_s=2.0, asr_rtf=3.0, language="en")

    original_argv = sys.argv[:]
    output = io.StringIO()
    errors = io.StringIO()
    try:
        cli.run = fake_run
        sys.argv = ["transcribe", "good.wav", "bad.wav", "--out-root", "/tmp/batch"]
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                cli.main()
            except SystemExit as exc:
                assert exc.code == 1
    finally:
        cli.run = original_run
        sys.argv = original_argv

    assert [source for source, _ in calls] == ["good.wav", "bad.wav"]
    assert calls[0][1]["out_root"] == Path("/tmp/batch")
    assert "transcript.md" in output.getvalue()
    assert "bad.wav" in errors.getvalue()


def test_cli_rejects_out_with_multiple_inputs():
    cli = _load_cli()
    original_argv = sys.argv[:]
    try:
        sys.argv = ["transcribe", "a.wav", "b.wav", "--out", "/tmp/one"]
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("expected argparse usage error")
    finally:
        sys.argv = original_argv


def test_cli_passes_subtitle_formats_and_replacements_to_run():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_argv = sys.argv[:]
    try:
        def fake_run(source, **kwargs):
            calls.append((source, kwargs))
            return RunResult(out_dir=Path("/tmp/good"),
                             transcript_md=Path("/tmp/good/transcript.md"),
                             transcript_json=Path("/tmp/good/transcript.json"),
                             manifest=Path("/tmp/good/manifest.json"),
                             speakers=1, duration_s=2.0, asr_rtf=3.0, language="en")

        cli.run = fake_run
        replacements = Path("/tmp/terms.json")
        sys.argv = ["transcribe", "good.wav", "--out-root", "/tmp/batch",
                    "--formats", "srt,vtt", "--replacements", str(replacements)]
        cli.main()
    finally:
        cli.run = original_run
        sys.argv = original_argv

    assert calls[0][1]["formats"] == ("srt", "vtt")
    assert calls[0][1]["replacements_file"] == replacements


def test_cli_watch_transcribes_candidate_and_stops_on_interrupt():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_candidate = cli.watch_candidate
    original_processed = cli.is_processed
    original_sleep = cli.time.sleep

    def fake_run(source, **kwargs):
        calls.append((source, kwargs))
        return RunResult(out_dir=Path("/tmp/watch-out"),
                         transcript_md=Path("/tmp/watch-out/transcript.md"),
                         transcript_json=Path("/tmp/watch-out/transcript.json"),
                         manifest=Path("/tmp/watch-out/manifest.json"),
                         speakers=1, duration_s=2.0, asr_rtf=3.0, language="en")

    original_argv = sys.argv[:]
    output = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            inbox.mkdir()
            source = inbox / "call.wav"
            source.write_bytes(b"audio")

            cli.run = fake_run
            cli.watch_candidate = lambda path, state: True
            cli.is_processed = lambda path, out_root, options_hash=None, signature=None: False
            cli.time.sleep = lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(Path(td) / "out"),
                        "--clean-fillers"]
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                cli.main()
    finally:
        cli.run = original_run
        cli.watch_candidate = original_candidate
        cli.is_processed = original_processed
        cli.time.sleep = original_sleep
        sys.argv = original_argv

    assert len(calls) == 1
    assert Path(calls[0][0]) == source
    assert calls[0][1]["clean_fillers"] is True
    assert calls[0][1]["out_root"] == Path(td) / "out"
    assert "transcript.md" in output.getvalue()


def test_cli_watch_defaults_to_standard_output_root():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_candidate = cli.watch_candidate
    original_processed = cli.is_processed
    original_sleep = cli.time.sleep
    original_default = cli.DEFAULT_OUT_ROOT
    original_argv = sys.argv[:]
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            inbox.mkdir()
            source = inbox / "call.wav"
            source.write_bytes(b"audio")
            default_root = Path(td) / "default-transcripts"

            def fake_run(source, **kwargs):
                calls.append((source, kwargs))
                return RunResult(out_dir=default_root / "call",
                                 transcript_md=default_root / "call/transcript.md",
                                 transcript_json=default_root / "call/transcript.json",
                                 manifest=default_root / "call/manifest.json",
                                 speakers=1, duration_s=2.0, asr_rtf=3.0,
                                 language="en")

            cli.run = fake_run
            cli.DEFAULT_OUT_ROOT = default_root
            cli.watch_candidate = lambda path, state: True
            cli.is_processed = lambda path, out_root, options_hash=None, signature=None: False
            cli.time.sleep = lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
            sys.argv = ["transcribe", "--watch", str(inbox)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()

            assert len(calls) == 1
            assert calls[0][1]["out_root"] == default_root
    finally:
        cli.run = original_run
        cli.watch_candidate = original_candidate
        cli.is_processed = original_processed
        cli.time.sleep = original_sleep
        cli.DEFAULT_OUT_ROOT = original_default
        sys.argv = original_argv


def test_cli_watch_persists_failure_and_skips_it_after_restart():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_candidate = cli.watch_candidate
    original_processed = cli.is_processed
    original_sleep = cli.time.sleep
    original_argv = sys.argv[:]
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            inbox.mkdir()
            source = inbox / "call.wav"
            source.write_bytes(b"audio")
            out_root = Path(td) / "out"

            def failing_run(source, **kwargs):
                calls.append((source, kwargs))
                raise RunError("движок упал")

            cli.run = failing_run
            cli.watch_candidate = lambda path, state: True
            cli.is_processed = lambda path, out_root, options_hash=None, signature=None: False
            sleeps = iter([None, "stop"])

            def fake_sleep(_):
                if next(sleeps) == "stop":
                    raise KeyboardInterrupt

            cli.time.sleep = fake_sleep
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(out_root)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()

            state = json.loads((out_root / ".transcribe-watch.json").read_text())
            assert len(calls) == 1
            assert next(iter(state["sources"].values()))["status"] == "failed"

            sleeps = iter(["stop"])
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(out_root)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()
            assert len(calls) == 1

            def successful_run(source, **kwargs):
                calls.append((source, kwargs))
                return RunResult(out_dir=out_root / "call",
                                 transcript_md=out_root / "call/transcript.md",
                                 transcript_json=out_root / "call/transcript.json",
                                 manifest=out_root / "call/manifest.json",
                                 speakers=1, duration_s=2.0, asr_rtf=3.0,
                                 language="en")

            cli.run = successful_run
            sleeps = iter(["stop"])
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(out_root), "--retry-failed"]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()
            state = json.loads((out_root / ".transcribe-watch.json").read_text())
            assert len(calls) == 2
            assert next(iter(state["sources"].values()))["status"] == "done"
    finally:
        cli.run = original_run
        cli.watch_candidate = original_candidate
        cli.is_processed = original_processed
        cli.time.sleep = original_sleep
        sys.argv = original_argv


def test_cli_watch_reprocesses_done_state_when_manifest_is_missing():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_candidate = cli.watch_candidate
    original_processed = cli.is_processed
    original_sleep = cli.time.sleep
    original_argv = sys.argv[:]
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            inbox.mkdir()
            source = inbox / "call.wav"
            source.write_bytes(b"audio")
            out_root = Path(td) / "out"
            options_hash = cli.processing_options_hash(
                speakers="auto", lang="auto", diar_mode="streaming", asr_model="v3",
                clean_fillers=False, formats=(), replacements={})
            (out_root).mkdir()
            (out_root / ".transcribe-watch.json").write_text(json.dumps({
                "version": 1,
                "sources": {str(source.resolve()): {
                    "signature": [source.stat().st_size, source.stat().st_mtime_ns],
                    "options_hash": options_hash, "status": "done",
                    "attempts": 1}}
            }))

            def fake_run(source, **kwargs):
                calls.append((source, kwargs))
                return RunResult(out_dir=out_root / "call",
                                 transcript_md=out_root / "call/transcript.md",
                                 transcript_json=out_root / "call/transcript.json",
                                 manifest=out_root / "call/manifest.json",
                                 speakers=1, duration_s=2.0, asr_rtf=3.0,
                                 language="en")

            cli.run = fake_run
            cli.watch_candidate = lambda path, state: True
            cli.is_processed = lambda path, out_root, options_hash=None, signature=None: False
            cli.time.sleep = lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(out_root)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()

            assert len(calls) == 1
    finally:
        cli.run = original_run
        cli.watch_candidate = original_candidate
        cli.is_processed = original_processed
        cli.time.sleep = original_sleep
        sys.argv = original_argv


def test_cli_watch_reprocesses_changed_source_even_with_old_manifest():
    cli = _load_cli()
    calls = []
    original_run = cli.run
    original_candidate = cli.watch_candidate
    original_sleep = cli.time.sleep
    original_argv = sys.argv[:]
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            inbox.mkdir()
            source = inbox / "call.wav"
            source.write_bytes(b"new-audio")
            out_root = Path(td) / "out"
            output = out_root / "call"
            output.mkdir(parents=True)
            options_hash = cli.processing_options_hash(
                speakers="auto", lang="auto", diar_mode="streaming", asr_model="v3",
                clean_fillers=False, formats=(), replacements={})
            (output / "manifest.json").write_text(json.dumps({
                "status": "done", "source": source.name, "options_hash": options_hash
            }))
            (out_root / ".transcribe-watch.json").write_text(json.dumps({
                "version": 1,
                "sources": {str(source.resolve()): {
                    "signature": [1, source.stat().st_mtime_ns],
                    "options_hash": options_hash, "status": "done",
                    "attempts": 1}}
            }))

            def fake_run(source, **kwargs):
                calls.append((source, kwargs))
                return RunResult(out_dir=out_root / "call (2)",
                                 transcript_md=out_root / "call (2)/transcript.md",
                                 transcript_json=out_root / "call (2)/transcript.json",
                                 manifest=out_root / "call (2)/manifest.json",
                                 speakers=1, duration_s=2.0, asr_rtf=3.0,
                                 language="en")

            cli.run = fake_run
            cli.watch_candidate = lambda path, state: True
            cli.time.sleep = lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
            sys.argv = ["transcribe", "--watch", str(inbox),
                        "--out-root", str(out_root)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main()

            assert len(calls) == 1
    finally:
        cli.run = original_run
        cli.watch_candidate = original_candidate
        cli.time.sleep = original_sleep
        sys.argv = original_argv


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
