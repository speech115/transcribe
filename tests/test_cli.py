import importlib.util
import os
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from importlib.machinery import SourceFileLoader

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from run import RunError, RunResult

BIN = Path(__file__).resolve().parent.parent / "bin" / "transcribe"


def _load_cli():
    loader = SourceFileLoader("transcribe_cli", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_cli_batch_continues_after_error(monkeypatch):
    cli = _load_cli()
    calls = []

    def fake_run(source, **kwargs):
        calls.append(source)
        if source == "bad.wav":
            raise RunError("файл не найден")
        return RunResult(Path("/tmp/good"), Path("/tmp/good/transcript.md"),
                         Path("/tmp/good/transcript.json"), Path("/tmp/good/manifest.json"), 1, 2, "en")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["transcribe", "good.wav", "bad.wav"])
    err = StringIO()
    with redirect_stderr(err):
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 1
    assert calls == ["good.wav", "bad.wav"]
    assert "bad.wav" in err.getvalue()
