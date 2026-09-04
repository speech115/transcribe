import json
from pathlib import Path

import pytest

from lib.engine import EngineError, FluidAudioEngine


def test_engine_reads_asr_and_diar(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("--output-json" if "transcribe" in cmd else "--output") + 1])
        out.write_text(json.dumps({"wordTimings": [{"startTime": 0, "endTime": 1, "word": "hello"}], "text": "hello"}
                                  if "transcribe" in cmd else {"segments": []}))
    monkeypatch.setattr("subprocess.run", fake_run)
    tr = FluidAudioEngine(binary=Path("engine")).transcribe(tmp_path / "in.wav", speakers="off")
    assert tr.words[0]["text"] == "hello"


def test_engine_reports_subprocess_failure(monkeypatch):
    import subprocess
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="boom")
    monkeypatch.setattr("subprocess.run", fail)
    with pytest.raises(EngineError, match="boom"):
        FluidAudioEngine(binary=Path("engine")).transcribe(Path("in.wav"), speakers="off")
