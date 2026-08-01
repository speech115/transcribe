#!/usr/bin/env python3
"""Tests for bin/transcribe wiring into the run-module contract."""
import importlib.util
import io
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import RunError, RunResult, Status

BIN = Path(__file__).resolve().parent.parent / "bin" / "transcribe"


def _load_cli():
    loader = SourceFileLoader("transcribe_cli", str(BIN))
    spec = importlib.util.spec_from_loader("transcribe_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_cli_status_forwards_only_explicit_max_age():
    cli = _load_cli()
    calls = []
    original = cli.status

    def recorder(out_dir=None, *, out_root=None, **kwargs):
        calls.append(kwargs)
        return Status(kind="idle")

    cli.status = recorder
    original_argv = sys.argv[:]
    try:
        sys.argv = ["transcribe", "status"]
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 0
        sys.argv = ["transcribe", "status", "--max-age", "30"]
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        cli.status = original
        sys.argv = original_argv

    assert calls[0] == {}
    assert calls[1] == {"max_age_s": 30.0}


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
            cli.is_processed = lambda path, out_root: False
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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\nALL {len(fns)} TESTS PASSED")
