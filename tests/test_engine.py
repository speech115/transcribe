import json
from pathlib import Path

import pytest

from transcribe.engine import EngineError, FluidAudioEngine


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


def test_auto_diarization_failure_returns_asr_once(monkeypatch, tmp_path):
    calls = {"asr": 0, "diar": 0}
    engine = FluidAudioEngine(binary=Path("engine"))

    def asr(wav, lang):
        calls["asr"] += 1
        return {"wordTimings": [{"startTime": 0, "endTime": 1, "word": "hello"}], "text": "hello"}

    def diar(wav, num):
        calls["diar"] += 1
        raise EngineError("diar", "CoreML boom")

    monkeypatch.setattr(engine, "_run_transcribe", asr)
    monkeypatch.setattr(engine, "_run_process", diar)
    result = engine.transcribe(tmp_path / "in.wav", speakers="auto")
    assert calls == {"asr": 1, "diar": 1}
    assert result.words and result.diar_status == "failed"
    assert result.diar_error == "CoreML boom"


def test_explicit_diarization_failure_remains_fatal(monkeypatch, tmp_path):
    engine = FluidAudioEngine(binary=Path("engine"))
    monkeypatch.setattr(engine, "_run_transcribe", lambda wav, lang: {
        "wordTimings": [{"startTime": 0, "endTime": 1, "word": "hello"}], "text": "hello"})
    monkeypatch.setattr(engine, "_run_process", lambda wav, num: (_ for _ in ()).throw(
        EngineError("diar", "CoreML boom")))
    with pytest.raises(EngineError, match="CoreML boom"):
        engine.transcribe(tmp_path / "in.wav", speakers="2")
