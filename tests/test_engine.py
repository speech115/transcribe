import json
from pathlib import Path

import pytest

from transcribe.engine import EngineError, FluidAudioEngine, _normalize_words, _normalize_diar


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


@pytest.mark.parametrize("speakers", ["autp", "0", "-1", "²", "2.5", "", "1" * 5000])
def test_invalid_speakers_fail_before_asr(monkeypatch, speakers):
    engine = FluidAudioEngine(binary=Path("engine"))
    def unexpected(*args):
        pytest.fail("ASR must not start with invalid arguments")
    monkeypatch.setattr(engine, "_run_transcribe", unexpected)
    with pytest.raises(EngineError, match="--speakers"):
        engine.transcribe(Path("in.wav"), speakers=speakers)


@pytest.mark.parametrize("word", [None, {}, {"startTime": None, "endTime": 1, "word": "hi"},
                                  {"startTime": 2, "endTime": 1, "word": "hi"},
                                  {"startTime": float("nan"), "endTime": 1, "word": "hi"},
                                  {"startTime": 0, "endTime": 1, "word": None}])
def test_malformed_words_are_engine_errors(word):
    with pytest.raises(EngineError, match="wordTimings"):
        _normalize_words({"wordTimings": [word]})


def test_malformed_diarization_uses_auto_fallback(monkeypatch, tmp_path):
    engine = FluidAudioEngine(binary=Path("engine"))
    monkeypatch.setattr(engine, "_run_transcribe", lambda *args: {
        "wordTimings": [{"startTime": 0, "endTime": 1, "word": "hello"}]})
    monkeypatch.setattr(engine, "_run_process", lambda *args: {"segments": [{"startTimeSeconds": None}]})
    result = engine.transcribe(tmp_path / "in.wav", speakers="auto")
    assert result.words and result.diar_status == "failed"
    assert "segments" in result.diar_error
    with pytest.raises(EngineError, match="segments"):
        engine.transcribe(tmp_path / "in.wav", speakers="2")


def test_engine_json_is_checked_and_removed(monkeypatch, tmp_path):
    outputs = []
    def fake_run(cmd, **kwargs):
        output = Path(cmd[-1])
        outputs.append(output)
        output.write_text("[]")
    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(EngineError, match="JSON-объект"):
        FluidAudioEngine(binary=Path("engine")).transcribe(tmp_path / "in.wav")
    assert outputs and not outputs[0].exists()


def test_normalization_orders_words_and_speakers():
    words = _normalize_words({"wordTimings": [
        {"startTime": 2, "endTime": 3, "word": "later"},
        {"startTime": 0, "endTime": 1, "word": "first"}]})
    diar, count = _normalize_diar({"segments": [
        {"startTimeSeconds": 2, "endTimeSeconds": 3, "speakerId": "b"},
        {"startTimeSeconds": 0, "endTimeSeconds": 1, "speakerId": "a"}]})
    assert [w["text"] for w in words] == ["first", "later"]
    assert count == 2 and [s[2] for s in diar] == ["S1", "S2"]
